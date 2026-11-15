"""The settings of ddviz: their definition, their checks and the files they are read from.

The values are layered key by key (`docs/spec.md`, "設定"): the defaults of
the dataclasses below, then ``config/settings.toml``, then
``config/settings.local.toml`` beside it, which the Preferences dialog writes
(`ddviz.server.settings_store`).
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path

from ddviz.server.settings_files import merge_tables, read_table
from ddviz.shared.scatter import MAX_AXIS_LEVELS, MAX_LEVELS

# Most columns the column list shows by default. 1,000 lists as fast as 200
# did; thousands make each search slow to draw (`docs/spec.md`, "列リストの件数").
MAX_LISTED = 1000
# Most keywords the search history of the column list keeps (`docs/spec.md`, "列リスト").
MAX_HISTORY = 20
# Opacity of the series made inactive in the legend (`docs/spec.md`, "凡例クリック").
INACTIVE_OPACITY = 0.15
# Resolutions the graph image copy may use; the first is the default
# (`docs/spec.md`, "グラフ画像のコピー").
IMAGE_COPY_DPIS = (300, 96)
# Bytes of a gigabyte in the sizes of the settings.
GB = 2**30
# Name of the file beside ``settings.toml`` whose keys win over its own.
LOCAL_NAME = "settings.local.toml"


def _number(value: object) -> bool:
    """Return whether `value` is an int or a float, not a bool."""
    return not isinstance(value, bool) and isinstance(value, int | float)


def positive_int(key: str, value: object) -> int:
    """Return `value` when it is a positive integer.

    Raises
    ------
    ValueError
        Otherwise, naming `key`.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} needs a positive integer: {value!r}")
    return value


def positive_number(key: str, value: object) -> float:
    """Return `value` when it is a finite number above 0.

    Raises
    ------
    ValueError
        Otherwise, naming `key`.
    """
    if not _number(value) or not 0 < value < math.inf:
        raise ValueError(f"{key} needs a positive number: {value!r}")
    return value


def non_negative_number(key: str, value: object) -> float:
    """Return `value` when it is a finite number of 0 or more.

    Raises
    ------
    ValueError
        Otherwise, naming `key`.
    """
    if not _number(value) or not 0 <= value < math.inf:
        raise ValueError(f"{key} needs a finite number of 0 or more: {value!r}")
    return value


def fraction(key: str, value: object) -> float:
    """Return `value` as a float when it is a number from 0 to 1.

    Raises
    ------
    ValueError
        Otherwise, naming `key`.
    """
    if not _number(value) or not 0 <= value <= 1:
        raise ValueError(f"{key} needs a number from 0 to 1: {value!r}")
    return float(value)


def dpi(key: str, value: object) -> int:
    """Return `value` when it is one of `IMAGE_COPY_DPIS`.

    Raises
    ------
    ValueError
        Otherwise, naming `key`.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value not in IMAGE_COPY_DPIS
    ):
        raise ValueError(f"{key} needs the integer 96 or 300: {value!r}")
    return value


def _setting(default: object, check: Callable[[str, object], object]) -> object:
    """Return a field of a settings dataclass: its default and the check of its values."""
    return field(default=default, metadata={"check": check})


@dataclass(frozen=True)
class CacheSettings:
    """Limits of the column cache.

    Parameters
    ----------
    max_gb : float
        Total size, in GB, of the column files; past it the least recently
        used go.
    max_unused_days : float
        Column files unused for longer go.
    """

    max_gb: float = _setting(10, non_negative_number)
    max_unused_days: float = _setting(30, non_negative_number)

    @property
    def max_bytes(self) -> int:
        """Return `max_gb` in bytes."""
        return int(self.max_gb * GB)


@dataclass(frozen=True)
class LegendSettings:
    """Looks of the legend's series.

    Parameters
    ----------
    inactive_opacity : float
        Opacity, from 0 to 1, of the series made inactive in the legend; 0
        hides them, and the hover does not find them.
    """

    inactive_opacity: float = _setting(INACTIVE_OPACITY, fraction)


@dataclass(frozen=True)
class ImageCopySettings:
    """Resolution of the graph image the plot's menu copies.

    Parameters
    ----------
    dpi : int
        Dots per inch of the PNG, 96 or 300; 96 CSS px make an inch.
    """

    dpi: int = _setting(IMAGE_COPY_DPIS[0], dpi)


@dataclass(frozen=True)
class PlotSettings:
    """Limits of a plot.

    Parameters
    ----------
    max_levels : int
        Most levels a categorical column on Color, Symbol, Group X, Group Y
        or Wrap may have.
    max_axis_levels : int
        Most levels a categorical column on X or Y may have.
    legend : LegendSettings
        Looks of the legend's series.
    image_copy : ImageCopySettings
        Resolution of the copied graph image.
    """

    max_levels: int = _setting(MAX_LEVELS, positive_int)
    max_axis_levels: int = _setting(MAX_AXIS_LEVELS, positive_int)
    legend: LegendSettings = LegendSettings()
    image_copy: ImageCopySettings = ImageCopySettings()


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

    max_listed: int = _setting(MAX_LISTED, positive_int)
    max_history: int = _setting(MAX_HISTORY, positive_int)


@dataclass(frozen=True)
class HoverSettings:
    """Limits of the hover files.

    Parameters
    ----------
    max_temp_gb : float
        Most GB the hover files of the open results (the overview and the
        view) take together in the temporary folder.
    """

    max_temp_gb: float = _setting(2, positive_number)

    @property
    def max_temp_bytes(self) -> int:
        """Return `max_temp_gb` in bytes."""
        return int(self.max_temp_gb * GB)


@dataclass(frozen=True)
class Settings:
    """All settings of ddviz; each field of a leaf dataclass is a key of the files.

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


def setting_keys(cls: type = Settings, prefix: str = "") -> list[str]:
    """Return the dotted keys of the settings, e.g. ``plot.legend.inactive_opacity``.

    Parameters
    ----------
    cls : type, optional
        Settings dataclass; `Settings` by default.
    prefix : str, optional
        Table of `cls` in the files, with its dot.

    Returns
    -------
    list of str
        The keys, in the order of the fields.
    """
    keys = []
    for f in fields(cls):
        if is_dataclass(f.default):
            keys += setting_keys(type(f.default), f"{prefix}{f.name}.")
        else:
            keys.append(f"{prefix}{f.name}")
    return keys


def values_of(settings: Settings) -> dict[str, object]:
    """Return the value of every key (`setting_keys`) of `settings`.

    Parameters
    ----------
    settings : Settings
        The settings.

    Returns
    -------
    dict
        Value by dotted key, as the files hold it (GB, not bytes).
    """
    values = {}
    for key in setting_keys():
        value: object = settings
        for name in key.split("."):
            value = getattr(value, name)
        values[key] = value
    return values


def check_value(key: str, value: object) -> object:
    """Return `value` checked as the value of `key`.

    Raises
    ------
    ValueError
        When `key` is not a setting, or `value` is not right for it.
    """
    table: object = Settings()
    for name in key.split(".")[:-1]:
        table = getattr(table, name, None)
        if not is_dataclass(table):
            raise ValueError(f"unknown setting: {key}")
    found = {f.name: f for f in fields(table)}.get(key.rsplit(".", 1)[-1])
    if found is None or is_dataclass(found.default):
        raise ValueError(f"unknown setting: {key}")
    return found.metadata["check"](key, value)


def settings_from(data: dict, cls: type = Settings, prefix: str = "") -> object:
    """Return the settings of a table of the files; a key left out takes its default.

    Keys that are not settings are ignored.

    Parameters
    ----------
    data : dict
        The table, as `tomllib` reads it.
    cls : type, optional
        Settings dataclass of the table; `Settings` by default.
    prefix : str, optional
        Dotted name of the table, with its dot, for the errors.

    Returns
    -------
    Settings
        The settings (an instance of `cls`).

    Raises
    ------
    ValueError
        When a value is not right for its key, or a table is not a table;
        the message names the key.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{prefix.removesuffix('.')} needs a table: {data!r}")  # noqa: TRY004 - a wrong value of the file, as the others
    found = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        key = f"{prefix}{f.name}"
        if is_dataclass(f.default):
            found[f.name] = settings_from(data[f.name], type(f.default), f"{key}.")
        else:
            found[f.name] = f.metadata["check"](key, data[f.name])
    return replace(cls(), **found)


def settings_path() -> Path:
    """Return where the shared settings file is: ``config/`` next to the exe, or at the repository root.

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


def local_path(path: Path) -> Path:
    """Return the local settings file beside the shared `path`, whose keys win over it.

    Parameters
    ----------
    path : pathlib.Path
        The shared settings file.

    Returns
    -------
    pathlib.Path
        ``settings.local.toml`` in the folder of `path`, which may not exist.
    """
    return path.with_name(LOCAL_NAME)


def load_settings(path: Path | None = None) -> Settings:
    """Read the settings: the defaults, then `path`, then its local file (`local_path`), key by key.

    A missing file adds nothing.

    Parameters
    ----------
    path : pathlib.Path, optional
        Shared settings file; `settings_path` by default.

    Returns
    -------
    Settings
        The settings.

    Raises
    ------
    ValueError
        When a file cannot be read or parsed (the message names the file),
        or a value of the merged files is not right for its key (the
        message names the key).
    """
    path = path or settings_path()
    data = merge_tables(read_table(path), read_table(local_path(path)))
    return settings_from(data)
