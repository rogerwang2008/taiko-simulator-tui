"""The physical keyboard, split left-to-right into four taiko zones."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Zones run left to right across the keyboard.
ZONES = ("左鼓边", "左鼓面", "右鼓面", "右鼓边")
ZONE_SOUNDS = ("rim", "center", "center", "rim")
ZONE_CHANNELS = (0, 0, 1, 1)  # 0 = left, 1 = right
CHANNEL_NAMES = ("左声道", "右声道")

# US layout rows with their physical stagger, measured in key units.
ROWS = (
    ("1234567890-=", 0.0),
    ("qwertyuiop[]\\", 0.5),
    ("asdfghjkl;'", 0.75),
    ("zxcvbnm,./", 1.25),
)

CELL_COLUMNS = 4  # display columns per key unit
BOUNDARY_STEP = 0.25  # key units a boundary moves per keypress
MIN_BAND = 0.5  # key units, so no zone collapses away entirely

X_MIN = 0.0
X_MAX = max(stagger + len(row) - 1 for row, stagger in ROWS)


@dataclass(frozen=True)
class KeyCap:
    char: str
    x: float
    row: int


LAYOUT: tuple[tuple[KeyCap, ...], ...] = tuple(
    tuple(KeyCap(char, stagger + index, row) for index, char in enumerate(row_chars))
    for row, (row_chars, stagger) in enumerate(ROWS)
)

KEY_POSITIONS: dict[str, float] = {cap.char: cap.x for row in LAYOUT for cap in row}


def _snap(value: float) -> float:
    return math.floor(value / BOUNDARY_STEP + 0.5) * BOUNDARY_STEP


def default_boundaries() -> tuple[float, float, float]:
    span = X_MAX - X_MIN
    first, second, third = (_snap(X_MIN + span * fraction / 4) for fraction in (1, 2, 3))
    return first, second, third


def clamp_boundaries(values: tuple[float, float, float] | list[float]) -> tuple[float, float, float]:
    """Snap to the step grid, keep the three boundaries ordered and inside the keyboard."""
    low, high = X_MIN + MIN_BAND, X_MAX - MIN_BAND
    out = [min(max(_snap(value), low), high) for value in sorted(values)]
    for index in (1, 2):
        out[index] = min(max(out[index], out[index - 1] + MIN_BAND), high)
    for index in (1, 0):
        out[index] = max(min(out[index], out[index + 1] - MIN_BAND), low)
    return out[0], out[1], out[2]


def zone_of(x: float, boundaries: tuple[float, float, float]) -> int:
    return sum(x >= boundary for boundary in boundaries)


def key_zones(boundaries: tuple[float, float, float]) -> dict[str, int]:
    return {char: zone_of(x, boundaries) for char, x in KEY_POSITIONS.items()}


def zone_keys(boundaries: tuple[float, float, float], zone: int) -> list[str]:
    """Keycaps in `zone`, in reading order."""
    zones = key_zones(boundaries)
    return [cap.char for row in LAYOUT for cap in row if zones[cap.char] == zone]
