"""Textual front end: play the drum and edit the four keyboard zones."""

from __future__ import annotations

from functools import partial

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from . import config as config_store
from .audio import AudioEngine
from .keyboard import (
    BOUNDARY_STEP,
    CELL_COLUMNS,
    CHANNEL_NAMES,
    KEY_POSITIONS,
    LAYOUT,
    ZONES,
    ZONE_CHANNELS,
    ZONE_SOUNDS,
    clamp_boundaries,
    default_boundaries,
    key_zones,
    zone_keys,
    zone_of,
)

# Taiko convention: the face (don) is red, the rim (ka) is blue. Hex so the same
# value works both as a Rich style and in Textual CSS.
ZONE_COLORS = ("#2f8fff", "#ff5a4d", "#ff5a4d", "#2f8fff")
SOUND_LABELS = {"rim": "鼓边 (ka)", "center": "鼓面 (don)"}
HIT_FLASH_SECONDS = 0.1


class KeyboardView(Widget):
    """The four keyboard rows, coloured by zone, with the movable boundaries underneath."""

    DEFAULT_CSS = """
    KeyboardView {
        height: auto;
        padding: 1 2 0 2;
    }
    """

    def __init__(self, boundaries: tuple[float, float, float], **kwargs) -> None:
        super().__init__(**kwargs)
        self._boundaries = boundaries
        self._selected = 0
        self._hit_zone: int | None = None
        self._flash_timer = None

    def set_boundaries(self, boundaries: tuple[float, float, float], selected: int) -> None:
        self._boundaries = boundaries
        self._selected = selected
        self.refresh()

    def set_selected(self, selected: int) -> None:
        self._selected = selected
        self.refresh()

    def flash(self, zone: int) -> None:
        self._hit_zone = zone
        self.refresh()
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(HIT_FLASH_SECONDS, self._clear_flash)

    def _clear_flash(self) -> None:
        self._hit_zone = None
        self.refresh()

    def render(self) -> Text:
        zones = key_zones(self._boundaries)
        picture = Text()
        for row in LAYOUT:
            line = Text()
            for cap in row:
                self._pad(line, round(cap.x * CELL_COLUMNS))
                style = f"on {ZONE_COLORS[zones[cap.char]]}"
                if zones[cap.char] == self._hit_zone:
                    style = f"bold reverse {style}"
                line.append(f" {cap.char.upper()} ", style=style)
                line.append(" ")
            picture.append_text(line)
            picture.append("\n")

        picture.append("\n")
        markers = Text()
        for index, boundary in enumerate(self._boundaries):
            self._pad(markers, round(boundary * CELL_COLUMNS))
            selected = index == self._selected
            markers.append(
                f"^{index + 1}",
                style="bold bright_yellow" if selected else "dim",
            )
        picture.append_text(markers)
        picture.append("\n")
        picture.append(
            "  ^1 ^2 ^3 = 分区边界，↑/↓ 选择，←/→ 移动",
            style="dim",
        )
        return picture

    @staticmethod
    def _pad(line: Text, column: int) -> None:
        gap = column - line.cell_len
        if gap > 0:
            line.append(" " * gap)


class ZonePanel(Static):
    """One zone: what it sounds like, which ear it goes to, and which keys drive it."""

    DEFAULT_CSS = f"""
    ZonePanel {{
        height: auto;
        width: 1fr;
        margin: 0 1;
        padding: 0 1;
        border: tall $panel;
    }}
    ZonePanel.rim {{
        border: tall {ZONE_COLORS[0]};
    }}
    ZonePanel.center {{
        border: tall {ZONE_COLORS[1]};
    }}
    ZonePanel.hit {{
        background: $boost;
        text-style: bold;
    }}
    """

    def __init__(self, zone: int, *, classes: str = "", **kwargs) -> None:
        super().__init__(classes=f"{classes} {'rim' if ZONE_SOUNDS[zone] == 'rim' else 'center'}".strip(), **kwargs)
        self._zone = zone
        self._flash_timer = None
        self.border_title = ZONES[zone]

    def show_keys(self, keys: list[str]) -> None:
        body = Text()
        body.append(f"{SOUND_LABELS[ZONE_SOUNDS[self._zone]]} · ", style="bold")
        channel = CHANNEL_NAMES[ZONE_CHANNELS[self._zone]]
        body.append(f"← {channel}" if ZONE_CHANNELS[self._zone] == 0 else f"{channel} →")
        body.append("\n")
        body.append(" ".join(key.upper() for key in keys) if keys else "（无按键）", style="dim")
        self.update(body)

    def flash(self) -> None:
        self.add_class("hit")
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(HIT_FLASH_SECONDS, partial(self.remove_class, "hit"))


class TaikoApp(App[None]):
    """大鼓模拟器：键盘左右四分区，实时发声并可视化配置。"""

    TITLE = "太鼓模拟器"
    SUB_TITLE = "键盘四分区 · WASAPI 低延迟"

    CSS = """
    Screen {
        align: center top;
    }
    #keyboard {
        width: auto;
    }
    #zones {
        height: auto;
        width: 100%;
        margin-bottom: 1;
    }
    #status {
        height: auto;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("left", "nudge(-1)", "边界左移"),
        Binding("right", "nudge(1)", "边界右移"),
        Binding("up", "select(-1)", "选择边界"),
        Binding("down", "select(1)", "", show=False),
        Binding("ctrl+r", "reset", "恢复默认"),
        Binding("escape", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = config_store.load()
        self._selected = 0
        self._engine: AudioEngine | None = None
        self._audio_error = ""

    def compose(self) -> ComposeResult:
        yield Header(icon="鼓")
        yield KeyboardView(self._config.boundaries, id="keyboard")
        with Horizontal(id="zones"):
            for zone in range(len(ZONES)):
                yield ZonePanel(zone, id=f"zone{zone}")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self._engine = AudioEngine()
            self._engine.start()
        except Exception as error:  # no device, or a driver/decoder we cannot use
            self._engine = None
            self._audio_error = f"{type(error).__name__}: {error}"
        self._sync()

    def shutdown_audio(self) -> None:
        if self._engine is not None:
            self._engine.stop()
            self._engine = None

    def on_key(self, event: events.Key) -> None:
        position = KEY_POSITIONS.get((event.character or "").lower())
        if position is None:
            return
        event.stop()
        event.prevent_default()

        zone = zone_of(position, self._config.boundaries)
        if self._engine is not None:
            self._engine.hit(ZONE_SOUNDS[zone], ZONE_CHANNELS[zone])
        self.query_one("#keyboard", KeyboardView).flash(zone)
        self.query_one(f"#zone{zone}", ZonePanel).flash()

    def action_nudge(self, direction: int) -> None:
        boundaries = list(self._config.boundaries)
        boundaries[self._selected] += direction * BOUNDARY_STEP
        self._apply(clamp_boundaries(boundaries))

    def action_select(self, direction: int) -> None:
        self._selected = (self._selected + direction) % len(self._config.boundaries)
        self.query_one("#keyboard", KeyboardView).set_selected(self._selected)

    def action_reset(self) -> None:
        self._apply(default_boundaries())

    def _apply(self, boundaries: tuple[float, float, float]) -> None:
        self._config.boundaries = boundaries
        self._sync()

    def _sync(self) -> None:
        boundaries = self._config.boundaries
        self.query_one("#keyboard", KeyboardView).set_boundaries(boundaries, self._selected)
        for zone in range(len(ZONES)):
            self.query_one(f"#zone{zone}", ZonePanel).show_keys(zone_keys(boundaries, zone))

        saved = ""
        try:
            config_store.save(self._config)
            saved = f"配置  {config_store.config_path()}"
        except OSError as error:
            saved = f"配置保存失败  {error}"

        if self._engine is None:
            audio = f"音频不可用  {self._audio_error}"
        else:
            device = self._engine.device
            audio = (
                f"音频  {device.name} · {device.host_api} · {device.sample_rate} Hz"
                f" · 输出缓冲 {device.latency * 1000:.1f} ms"
            )
        self.query_one("#status", Static).update(Text(f"{audio}\n{saved}"))
