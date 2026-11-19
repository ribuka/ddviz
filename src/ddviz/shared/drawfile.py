"""The file of the drawing settings: the settings of a graph and where its data was (Issue #287).

The graph's page saves its drawing settings (`captureSettings()` of
``static/js/app.js``) with the input it loaded as JSON; the window's chooser
opens such a file, finds the data and loads it with the settings
(``docs/spec.md``, "描画設定のファイル"). This module builds the file
(`build`), reads it (`parse`) and finds its data (`resolve`); it touches the
file system only in `resolve`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePath

#: The value of the file's ``format``.
FORMAT = "ddviz-draw-settings"
#: The version of the format this ddviz writes and reads; raised with every change of the format.
VERSION = 1
#: The suffix of the file's default name, after the first input's name.
SUFFIX = ".ddviz.json"


@dataclass(frozen=True)
class DrawFile:
    """A file of the drawing settings, as `parse` read it.

    Attributes
    ----------
    paths : list of str
        Absolute paths of the input, in the order loaded.
    relative : list of str or None
        The same paths from the file's folder, or None when one could not be
        made relative (or the file was downloaded by a browser).
    recursive : bool
        For a folder, whether its subfolders were read too.
    content : dict
        The whole file, which the page reads its ``settings`` and
        ``columns`` from.
    """

    paths: list[str]
    relative: list[str] | None
    recursive: bool
    content: dict


@dataclass(frozen=True)
class Missing:
    """The inputs of a file of the drawing settings found at neither of their paths.

    Attributes
    ----------
    paths : list of str
        Their absolute paths, in the order of the input.
    """

    paths: list[str]


def column_kind(column: dict) -> str:
    """Return the kind of a column the drawing settings compare: as the page tells them apart.

    Parameters
    ----------
    column : dict
        A column of the schema (``{"name", "dtype", "numeric", "temporal"}``,
        `ddviz.server.source.Source.schema`).

    Returns
    -------
    str
        ``"temporal:<kind>"`` (`ddviz.shared.temporal.KINDS`) for a temporal
        column, else ``"numeric"`` or ``"categorical"``.
    """
    if column.get("temporal"):
        return f"temporal:{column['temporal']}"
    return "numeric" if column["numeric"] else "categorical"


def default_name(path: PurePath, is_dir: bool) -> str:
    """Return the default name of the file for an input whose first item is `path`.

    Parameters
    ----------
    path : pathlib.PurePath
        The first input's path.
    is_dir : bool
        Whether it is a folder, whose name has no extension to drop.

    Returns
    -------
    str
        ``<name without its extension>.ddviz.json``.
    """
    return f"{path.name if is_dir else path.stem}{SUFFIX}"


def _same(a: str, b: str, flavor: type[PurePath]) -> bool:
    """Return whether two parts of a path are the same for the paths of `flavor` (Windows: in any case)."""
    return flavor(a) == flavor(b)


def relative_paths(paths: list[PurePath], json_path: PurePath) -> list[str] | None:
    """Return the paths of the input from the folder of the file `json_path`.

    Parameters
    ----------
    paths : list of pathlib.PurePath
        Absolute paths of the input.
    json_path : pathlib.PurePath
        Absolute path of the file of the drawing settings; of the same flavor
        as `paths` (Windows paths compare in any case).

    Returns
    -------
    list of str or None
        Each path from the file's folder (``..`` to go up), or None when any
        path is on another drive or root than the file.
    """
    folder = json_path.parent
    flavor = type(folder)
    found = []
    for path in paths:
        if not _same(path.anchor, folder.anchor, flavor):
            return None
        own, base = path.parts[1:], folder.parts[1:]
        common = 0
        while common < min(len(own), len(base)) and _same(own[common], base[common], flavor):
            common += 1
        parts = [".."] * (len(base) - common) + list(own[common:])
        found.append(str(flavor(*parts)) if parts else ".")
    return found


def build(
    settings: dict,
    columns: dict[str, str],
    paths: list[str],
    recursive: bool,
    json_path: PurePath | None,
    app_version: str,
    saved_at: dt.datetime | None = None,
) -> dict:
    """Return the content of the file of the drawing settings.

    Parameters
    ----------
    settings : dict
        The drawing settings (`captureSettings()` of the page).
    columns : dict
        Every column the settings refer to, with its kind (`column_kind`).
    paths : list of str
        Absolute paths of the input, in the order loaded.
    recursive : bool
        For a folder, whether its subfolders were read too.
    json_path : pathlib.PurePath or None
        Where the file is written, for ``source.relative``; None when it is
        not known (a browser's download), which leaves it None.
    app_version : str
        ddviz's version.
    saved_at : datetime.datetime, optional
        When it was saved; now, in the local zone, by default.

    Returns
    -------
    dict
        The file's content (``docs/spec.md``, "描画設定のファイル").
    """
    when = saved_at or dt.datetime.now().astimezone()
    relative = None
    if json_path is not None:
        relative = relative_paths([type(json_path)(p) for p in paths], json_path)
    return {
        "format": FORMAT,
        "version": VERSION,
        "app_version": app_version,
        "saved_at": when.isoformat(timespec="seconds"),
        "source": {"paths": list(paths), "relative": relative, "recursive": recursive},
        "columns": dict(columns),
        "settings": settings,
    }


def _unreadable(reason: str) -> ValueError:
    return ValueError(f"描画設定のファイルを読めませんでした：{reason}")


@dataclass(frozen=True)
class _List:
    """A JSON array whose items each have the shape `item`."""

    item: object


@dataclass(frozen=True)
class _Pair:
    """A JSON array of two items of the shapes `first` and `second` (an entry of a `Map`)."""

    first: object
    second: object


@dataclass(frozen=True)
class _Optional:
    """Null, or a value of the shape `shape`."""

    shape: object


#: Any value, which must only be there.
_ANY = object()
_NAMES = _List(str)
_COLUMN = (str, type(None))

#: The shape of ``settings`` (`captureSettings()` of ``static/js/app.js``)
#: that the page needs to apply them (`applySettings`) and to check their
#: columns (``static/js/drawfile.js``): an object's keys, the types of the
#: values the page reads, and arrays and objects it goes through. A file
#: without it is refused on the chooser before its data opens.
SETTINGS_SHAPE = {
    "zones": {
        "encoding": {
            "x": _NAMES,
            "y": _NAMES,
            "color": _COLUMN,
            "symbol": _COLUMN,
            "row": _COLUMN,
            "col": _COLUMN,
            "wrap": _COLUMN,
            "elements": _NAMES,
        },
        "numeric": _List(_Pair(str, (bool, type(None)))),
        "temporal": _List(_Pair(str, _COLUMN)),
        "stashed": _NAMES,
    },
    "elements": {"chosen": _NAMES, "blocked": _NAMES},
    "options": {
        "colorBins": _ANY,
        "smoothing": _ANY,
        "shapeSize": _ANY,
        "lineWidth": _ANY,
        "lineAggregation": _ANY,
        "showNullRows": dict,
        "keepLevels": dict,
        "wrapCols": _ANY,
        "levelSizes": _List(_Pair(str, dict)),
        "levelShapes": _Optional({"column": str, "shapes": dict}),
    },
    "axes": {
        "dialog": _List(_Pair(str, dict)),
        "angles": _List(_Pair(str, _ANY)),
        "logs": {"x": _NAMES, "y": _NAMES},
        "reversed": {"x": _NAMES, "y": _NAMES},
        "keepLevels": _NAMES,
    },
    "filters": _List(
        {
            "name": str,
            "numeric": bool,
            "range": (list, type(None)),
            "levels": list,
            "contains": _ANY,
            "nulls": dict,
            "mode": _ANY,
            "query": _ANY,
            "order": _ANY,
        }
    ),
}


def _check(value: object, shape: object, path: str) -> None:
    """Raise the chooser's `ValueError` unless `value` (at the key `path`) has the shape `shape`.

    A shape is `_ANY`, a type or a tuple of types, a dict of the shapes of
    an object's keys, `_List`, `_Pair` or `_Optional`.
    """
    if shape is _ANY:
        return
    if isinstance(shape, _Optional):
        if value is not None:
            _check(value, shape.shape, path)
        return
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            raise _unreadable(f"キー {path} の値の形が違います")
        for key, inner in shape.items():
            if key not in value:
                raise _unreadable(f"キー {path}.{key} がありません")
            _check(value[key], inner, f"{path}.{key}")
        return
    if isinstance(shape, _List):
        if not isinstance(value, list):
            raise _unreadable(f"キー {path} の値の形が違います")
        for index, item in enumerate(value):
            _check(item, shape.item, f"{path}[{index}]")
        return
    if isinstance(shape, _Pair):
        if not isinstance(value, list) or len(value) != 2:
            raise _unreadable(f"キー {path} の値の形が違います")
        _check(value[0], shape.first, f"{path}[0]")
        _check(value[1], shape.second, f"{path}[1]")
        return
    types = shape if isinstance(shape, tuple) else (shape,)
    # JSON's true and false are not the numbers a shape of int means.
    if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
        raise _unreadable(f"キー {path} の値の形が違います")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def parse(text: str) -> DrawFile:
    """Read the content of a file of the drawing settings.

    Parameters
    ----------
    text : str
        The file's text.

    Returns
    -------
    DrawFile
        What it holds.

    Raises
    ------
    ValueError
        With the message the chooser shows: ``描画設定のファイルを読めませんでした：<理由>``
        for text that is not JSON, another ``format`` or a key missing or of
        the wrong type, and ``この描画設定は読めません（版 <N>。この ddviz は版 1 を読みます）``
        for another ``version``.
    """
    try:
        content = json.loads(text)
    except json.JSONDecodeError as error:
        raise _unreadable(f"JSON ではありません（{error}）") from error
    if not isinstance(content, dict):
        raise _unreadable("JSON のオブジェクトではありません")
    if content.get("format") != FORMAT:
        raise _unreadable(f"format が {FORMAT} ではありません")
    if "version" not in content:
        raise _unreadable("キー version がありません")
    version = content["version"]
    if version != VERSION or isinstance(version, bool):
        raise ValueError(f"この描画設定は読めません（版 {version}。この ddviz は版 {VERSION} を読みます）")
    for key, kind in (("source", dict), ("columns", dict), ("settings", dict)):
        if key not in content:
            raise _unreadable(f"キー {key} がありません")
        if not isinstance(content[key], kind):
            raise _unreadable(f"キー {key} の値の形が違います")
    source = content["source"]
    for key in ("paths", "relative", "recursive"):
        if key not in source:
            raise _unreadable(f"キー source.{key} がありません")
    paths, relative, recursive = source["paths"], source["relative"], source["recursive"]
    if not _strings(paths) or not paths:
        raise _unreadable("キー source.paths の値の形が違います")
    if relative is not None and (not _strings(relative) or len(relative) != len(paths)):
        raise _unreadable("キー source.relative の値の形が違います")
    if not isinstance(recursive, bool):
        raise _unreadable("キー source.recursive の値の形が違います")
    if not all(isinstance(v, str) for v in content["columns"].values()):
        raise _unreadable("キー columns の値の形が違います")
    _check(content["settings"], SETTINGS_SHAPE, "settings")
    return DrawFile(paths=paths, relative=relative, recursive=recursive, content=content)


def _exists(path: Path) -> bool:
    return path.is_file() or path.is_dir()


def resolve(draw_file: DrawFile, json_path: Path) -> list[Path] | Missing:
    """Find the input of a file of the drawing settings: at its absolute path, else at its path from the file.

    Parameters
    ----------
    draw_file : DrawFile
        The file read.
    json_path : pathlib.Path
        Where the file is, which its relative paths start from.

    Returns
    -------
    list of pathlib.Path or Missing
        The path found for each input, in order; or the absolute paths of
        those found at neither.
    """
    found: list[Path] = []
    missing: list[str] = []
    for index, absolute in enumerate(draw_file.paths):
        candidates = [Path(absolute)]
        if draw_file.relative is not None:
            # Taken apart lexically, as Windows does: the folders that `..`
            # goes up from need not exist.
            candidates.append(Path(os.path.normpath(json_path.parent / draw_file.relative[index])))
        path = next((c for c in candidates if _exists(c)), None)
        if path is None:
            missing.append(absolute)
        else:
            found.append(path)
    return Missing(missing) if missing else found


@dataclass(frozen=True)
class Opened:
    """A file of the drawing settings opened on the window's chooser (`DrawFileIO.read`).

    Attributes
    ----------
    content : dict
        The whole file, for the page.
    recursive : bool
        For a folder, whether its subfolders were read too.
    found : list of str
        The path found for each input, in order; empty when any is missing.
    missing : list of str
        The absolute paths of the inputs found at neither of their paths.
    """

    content: dict
    recursive: bool
    found: list[str]
    missing: list[str]


class DrawFileIO:
    """What the window does with files of the drawing settings: open one on the chooser, name and write one saved.

    ``__main__`` hands it to the window (``ddviz.desktop.window.run_window``),
    which does not import `ddviz.shared`.
    """

    def read(self, json_path: Path) -> Opened:
        """Read the file `json_path` and find its data (`parse`, `resolve`).

        Parameters
        ----------
        json_path : pathlib.Path
            The file picked or dropped.

        Returns
        -------
        Opened
            The file and its data found or missing.

        Raises
        ------
        ValueError
            With the message the chooser shows, also for a file that cannot
            be read or is not UTF-8.
        """
        try:
            text = json_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            raise _unreadable(str(error)) from error
        draw = parse(text)
        found = resolve(draw, json_path)
        if isinstance(found, Missing):
            return Opened(draw.content, draw.recursive, [], found.paths)
        return Opened(draw.content, draw.recursive, [str(p) for p in found], [])

    def default_name(self, first: Path) -> str:
        """Return the default name of the file for an input whose first item is `first` (`default_name`)."""
        return default_name(first, first.is_dir())

    def write(self, content: dict, target: Path) -> None:
        """Write the file's `content` at `target`, with the input's paths from there (`relative_paths`).

        Raises
        ------
        OSError
            When it cannot be written.
        """
        paths = [Path(p) for p in content["source"]["paths"]]
        source = {**content["source"], "relative": relative_paths(paths, target)}
        text = json.dumps({**content, "source": source}, ensure_ascii=False, indent=2)
        target.write_text(text + "\n", encoding="utf-8")
