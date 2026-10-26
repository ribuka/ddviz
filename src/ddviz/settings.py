"""Settings read from ``config/settings.toml`` next to the app."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CacheSettings:
    """Limits of the column cache.

    Parameters
    ----------
    max_bytes : int
        Total size of the column files; past it the least recently used go.
    max_unused_days : float
        Column files unused for longer go.
    """

    max_bytes: int = 10 * 2**30
    max_unused_days: float = 30.0


@dataclass(frozen=True)
class Settings:
    """All settings of ddviz.

    Parameters
    ----------
    cache : CacheSettings
        Limits of the column cache.
    """

    cache: CacheSettings = CacheSettings()


def settings_path() -> Path:
    """Return where the settings file is: ``config/`` next to the exe, or at the repository root.

    Returns
    -------
    pathlib.Path
        The settings file, which may not exist.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parents[2]
    return base / "config" / "settings.toml"


def load_settings(path: Path | None = None) -> Settings:
    """Read the settings; a missing file or key takes the default.

    Parameters
    ----------
    path : pathlib.Path, optional
        Settings file; `settings_path` by default.

    Returns
    -------
    Settings
        The settings.
    """
    path = path or settings_path()
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cache = data.get("cache", {})
    default = CacheSettings()
    return Settings(
        cache=CacheSettings(
            max_bytes=int(cache["max_gb"] * 2**30)
            if "max_gb" in cache
            else default.max_bytes,
            max_unused_days=float(
                cache.get("max_unused_days", default.max_unused_days)
            ),
        )
    )
