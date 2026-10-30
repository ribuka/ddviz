"""Settings read from ``config/settings.toml`` next to the app."""

from __future__ import annotations

import math
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ddviz.shared.scatter import MAX_LEVELS


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
class PlotSettings:
    """Limits of a plot.

    Parameters
    ----------
    max_levels : int
        Most levels a categorical column on color, Group X or Group Y may have.
    """

    max_levels: int = MAX_LEVELS


@dataclass(frozen=True)
class HoverSettings:
    """Limits of the hover files.

    Parameters
    ----------
    max_temp_bytes : int
        Most bytes the hover files of the open results (the overview and the
        view) take together in the temporary folder.
    """

    max_temp_bytes: int = 2 * 2**30


@dataclass(frozen=True)
class Settings:
    """All settings of ddviz.

    Parameters
    ----------
    cache : CacheSettings
        Limits of the column cache.
    plot : PlotSettings
        Limits of a plot.
    hover : HoverSettings
        Limits of the hover files.
    """

    cache: CacheSettings = CacheSettings()
    plot: PlotSettings = PlotSettings()
    hover: HoverSettings = HoverSettings()


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
        base = Path(__file__).resolve().parents[3]
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

    Raises
    ------
    ValueError
        When ``plot.max_levels`` is not a positive integer, or
        ``hover.max_temp_gb`` is not a positive number.
    """
    path = path or settings_path()
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cache = data.get("cache", {})
    default = CacheSettings()
    max_levels = data.get("plot", {}).get("max_levels", MAX_LEVELS)
    if (
        isinstance(max_levels, bool)
        or not isinstance(max_levels, int)
        or max_levels < 1
    ):
        raise ValueError(f"plot.max_levels needs a positive integer: {max_levels!r}")
    hover = data.get("hover", {})
    max_temp_gb = hover.get("max_temp_gb")
    if max_temp_gb is not None and (
        isinstance(max_temp_gb, bool)
        or not isinstance(max_temp_gb, int | float)
        or not 0 < max_temp_gb < math.inf
    ):
        raise ValueError(f"hover.max_temp_gb needs a positive number: {max_temp_gb!r}")
    return Settings(
        cache=CacheSettings(
            max_bytes=int(cache["max_gb"] * 2**30)
            if "max_gb" in cache
            else default.max_bytes,
            max_unused_days=float(
                cache.get("max_unused_days", default.max_unused_days)
            ),
        ),
        plot=PlotSettings(max_levels=max_levels),
        hover=HoverSettings()
        if max_temp_gb is None
        else HoverSettings(max_temp_bytes=int(max_temp_gb * 2**30)),
    )
