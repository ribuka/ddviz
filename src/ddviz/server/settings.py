"""Settings read from ``config/settings.toml`` next to the app."""

from __future__ import annotations

import math
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ddviz.shared.scatter import MAX_AXIS_LEVELS, MAX_LEVELS

# Most columns the column list shows by default. 1,000 lists as fast as 200
# did; thousands make each search slow to draw (`docs/spec.md`, "列リストの件数").
MAX_LISTED = 1000
# Most keywords the search history of the column list keeps (`docs/spec.md`, "列リスト").
MAX_HISTORY = 20
# Opacity of the series made inactive in the legend (`docs/spec.md`, "凡例クリック").
INACTIVE_OPACITY = 0.1


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
class LegendSettings:
    """Looks of the legend's series.

    Parameters
    ----------
    inactive_opacity : float
        Opacity, from 0 to 1, of the series made inactive in the legend; 0
        hides them, and the hover does not find them.
    """

    inactive_opacity: float = INACTIVE_OPACITY


@dataclass(frozen=True)
class PlotSettings:
    """Limits of a plot.

    Parameters
    ----------
    max_levels : int
        Most levels a categorical column on Color, Overlay, Group X, Group Y
        or Wrap may have.
    max_axis_levels : int
        Most levels a categorical column on X or Y may have.
    legend : LegendSettings
        Looks of the legend's series.
    """

    max_levels: int = MAX_LEVELS
    max_axis_levels: int = MAX_AXIS_LEVELS
    legend: LegendSettings = LegendSettings()


@dataclass(frozen=True)
class ColumnsSettings:
    """Limits of the column list.

    Parameters
    ----------
    max_listed : int
        Most matching columns the column list shows.
    max_history : int
        Most keywords the search history of the column list keeps per input.
    """

    max_listed: int = MAX_LISTED
    max_history: int = MAX_HISTORY


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
    columns : ColumnsSettings
        Limits of the column list.
    """

    cache: CacheSettings = CacheSettings()
    plot: PlotSettings = PlotSettings()
    hover: HoverSettings = HoverSettings()
    columns: ColumnsSettings = ColumnsSettings()


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
        When ``plot.max_levels``, ``plot.max_axis_levels``, ``columns.max_listed`` or
        ``columns.max_history`` is not a positive integer, ``hover.max_temp_gb`` is not a positive number, or
        ``plot.legend.inactive_opacity`` is not a number from 0 to 1.
    """
    path = path or settings_path()
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    cache = data.get("cache", {})
    default = CacheSettings()
    max_levels = _positive_int(data, "plot", "max_levels", MAX_LEVELS)
    max_axis_levels = _positive_int(data, "plot", "max_axis_levels", MAX_AXIS_LEVELS)
    max_listed = _positive_int(data, "columns", "max_listed", MAX_LISTED)
    max_history = _positive_int(data, "columns", "max_history", MAX_HISTORY)
    inactive_opacity = (
        data.get("plot", {}).get("legend", {}).get("inactive_opacity", INACTIVE_OPACITY)
    )
    if (
        isinstance(inactive_opacity, bool)
        or not isinstance(inactive_opacity, int | float)
        or not 0 <= inactive_opacity <= 1
    ):
        raise ValueError(
            "plot.legend.inactive_opacity needs a number from 0 to 1: "
            f"{inactive_opacity!r}"
        )
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
        plot=PlotSettings(
            max_levels=max_levels,
            max_axis_levels=max_axis_levels,
            legend=LegendSettings(inactive_opacity=float(inactive_opacity)),
        ),
        hover=HoverSettings()
        if max_temp_gb is None
        else HoverSettings(max_temp_bytes=int(max_temp_gb * 2**30)),
        columns=ColumnsSettings(max_listed=max_listed, max_history=max_history),
    )


def _positive_int(data: dict, table: str, key: str, default: int) -> int:
    """Return ``data[table][key]``, or `default` without it.

    Raises
    ------
    ValueError
        When the value is not a positive integer.
    """
    value = data.get(table, {}).get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{table}.{key} needs a positive integer: {value!r}")
    return value
