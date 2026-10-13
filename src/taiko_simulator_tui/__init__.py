"""大鼓模拟器 — a low-latency taiko drum TUI."""

from __future__ import annotations

import sys
from collections.abc import Callable

from .app import TaikoApp


def _use_utf8_console() -> Callable[[], None]:
    """Point the Windows console at UTF-8.

    Textual writes straight to `sys.__stdout__`, so on a legacy code page such as
    cp936 its own glyphs raise UnicodeEncodeError inside the writer thread and the
    screen silently stops updating.
    """
    if sys.platform != "win32":
        return lambda: None

    import ctypes

    kernel32 = ctypes.windll.kernel32
    previous = (kernel32.GetConsoleCP(), kernel32.GetConsoleOutputCP())
    kernel32.SetConsoleCP(65001)
    kernel32.SetConsoleOutputCP(65001)
    streams = [stream for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__) if stream is not None]
    for stream in streams:
        stream.reconfigure(encoding="utf-8")

    def restore() -> None:
        kernel32.SetConsoleCP(previous[0])
        kernel32.SetConsoleOutputCP(previous[1])

    return restore


def main() -> None:
    restore_console = _use_utf8_console()
    app = TaikoApp()
    try:
        app.run()
    finally:
        app.shutdown_audio()
        restore_console()
