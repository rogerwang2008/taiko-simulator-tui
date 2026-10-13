"""Low-latency stereo playback for the taiko samples."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import miniaudio
import numpy as np
import sounddevice as sd
import soxr

# The samples ship with ~70 ms of leading silence; left in place that silence
# becomes perceived input latency, so the head and tail are trimmed on load.
TRIM_THRESHOLD = 0.005  # fraction of peak below which audio counts as silence
TRIM_HEAD_MS = 0.5  # silence kept before the first audible frame
TRIM_TAIL_MS = 30.0  # silence kept after the last audible frame
FADE_IN_MS = 0.5
FADE_OUT_MS = 8.0

# Both sides are frequently hit at once; keeping each below 0.6 avoids clipping
# the mix without needing a limiter.
NORMALISE_PEAK = 0.6

BLOCKSIZE = 64  # ~1.3 ms at 48 kHz: how quickly a hit reaches the output buffer
RING_SECONDS = 3.0

SOUNDS = {"center": "center1", "rim": "rim1"}

_ASSETS = files("taiko_simulator_tui") / "assets" / "audio"


@dataclass(frozen=True)
class Sample:
    """A trimmed, normalised hit, pre-panned once per output channel."""

    duration: float
    panned: tuple[np.ndarray, np.ndarray]  # index 0 = left, 1 = right; each (n, 2) float32


@dataclass
class OutputDevice:
    index: int
    name: str
    host_api: str
    sample_rate: int
    latency: float = 0.0  # seconds, filled in once the stream is open


def pick_output_device() -> OutputDevice:
    """Prefer the WASAPI default output: PortAudio's own default is usually MME, which adds ~100 ms."""
    host_apis = sd.query_hostapis()
    for api in host_apis:
        if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
            index = api["default_output_device"]
            break
    else:
        index = sd.default.device[1]
        if index < 0:
            raise RuntimeError("no audio output device available")
    info = sd.query_devices(index)
    return OutputDevice(
        index=index,
        name=info["name"],
        host_api=host_apis[info["hostapi"]]["name"],
        sample_rate=int(info["default_samplerate"]),
    )


def _trim(mono: np.ndarray, rate: int) -> np.ndarray:
    peak = float(np.abs(mono).max())
    if peak <= 0.0:
        return mono
    audible = np.flatnonzero(np.abs(mono) > peak * TRIM_THRESHOLD)
    start = max(int(audible[0]) - round(rate * TRIM_HEAD_MS / 1000), 0)
    end = min(int(audible[-1]) + round(rate * TRIM_TAIL_MS / 1000) + 1, len(mono))
    cut = mono[start:end].copy()

    fade_in = max(round(rate * FADE_IN_MS / 1000), 1)
    cut[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    fade_out = min(max(round(rate * FADE_OUT_MS / 1000), 1), len(cut))
    cut[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)

    return cut * (NORMALISE_PEAK / (float(np.abs(cut).max()) or 1.0))


def load_sample(stem: str, rate: int) -> Sample:
    decoded = miniaudio.decode_file(str(Path(str(_ASSETS / f"{stem}.mp3"))))
    if decoded.sample_width != 2:
        raise ValueError(f"{stem}: expected 16-bit samples, got {decoded.sample_width * 8}-bit")
    pcm = np.frombuffer(decoded.samples, dtype=np.int16).reshape(-1, decoded.nchannels)

    # Downmix to mono: the sources are stereo, and the app assigns the channel.
    mono = pcm.astype(np.float32).mean(axis=1) / 32768.0
    mono = _trim(mono, decoded.sample_rate)
    if decoded.sample_rate != rate:
        mono = soxr.resample(mono, decoded.sample_rate, rate, quality="VHQ")
    mono = np.ascontiguousarray(mono, dtype=np.float32)

    panned = []
    for channel in (0, 1):
        stereo = np.zeros((len(mono), 2), dtype=np.float32)
        stereo[:, channel] = mono
        panned.append(stereo)
    return Sample(duration=len(mono) / rate, panned=(panned[0], panned[1]))


class AudioEngine:
    """One always-running stream; a hit is an additive write at the read cursor."""

    def __init__(self) -> None:
        self.device = pick_output_device()
        rate = self.device.sample_rate
        self.samples = {name: load_sample(stem, rate) for name, stem in SOUNDS.items()}

        longest = max(sample.duration for sample in self.samples.values())
        frames = max(round(rate * RING_SECONDS), round(rate * longest) + rate // 4)
        self._ring = np.zeros((frames, 2), dtype=np.float32)
        self._cursor = 0
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None

    def start(self) -> None:
        self._stream = sd.OutputStream(
            samplerate=self.device.sample_rate,
            blocksize=BLOCKSIZE,
            device=self.device.index,
            channels=2,
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        self._stream.start()
        self.device.latency = float(self._stream.latency)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.close()

    def hit(self, sound: str, channel: int) -> None:
        """Schedule `sound` on `channel` (0 = left, 1 = right) to start at the next block."""
        data = self.samples[sound].panned[channel]
        total = self._ring.shape[0]
        count = data.shape[0]
        with self._lock:
            start = self._cursor
            end = start + count
            if end <= total:
                self._ring[start:end] += data
            else:
                head = total - start
                self._ring[start:] += data[:head]
                self._ring[: count - head] += data[head:]

    def _callback(self, outdata: np.ndarray, frames: int, time_info: float, status) -> None:
        ring = self._ring
        total = ring.shape[0]
        with self._lock:
            start = self._cursor
            end = start + frames
            if end <= total:
                outdata[:] = ring[start:end]
                ring[start:end] = 0.0
                self._cursor = end
            else:
                head = total - start
                outdata[:head] = ring[start:]
                ring[start:] = 0.0
                outdata[head:] = ring[: frames - head]
                ring[: frames - head] = 0.0
                self._cursor = frames - head
            # Overlapping hits measured up to 1.06 on a fast roll; clamp here so the
            # result is the same whatever format the device mixes in.
            np.clip(outdata, -1.0, 1.0, out=outdata)
