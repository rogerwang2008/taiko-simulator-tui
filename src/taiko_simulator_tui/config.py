"""The zone boundaries, persisted as JSON in the user config directory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import platformdirs

from .keyboard import clamp_boundaries, default_boundaries

APP_NAME = "taiko-simulator-tui"
VERSION = 1


@dataclass
class Config:
    version: int = VERSION
    boundaries: tuple[float, float, float] = default_boundaries()


def config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.json"


def load() -> Config:
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()

    boundaries = raw.get("boundaries") if isinstance(raw, dict) else None
    numbers = (
        isinstance(boundaries, list)
        and len(boundaries) == 3
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in boundaries)
    )
    if not numbers:
        return Config()
    return Config(boundaries=clamp_boundaries(boundaries))


def save(config: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
