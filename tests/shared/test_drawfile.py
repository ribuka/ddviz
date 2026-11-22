"""The file of the drawing settings: build, read and find its data (`ddviz.shared.drawfile`, Issue #287, #345)."""

from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path, PureWindowsPath

import pytest

from ddviz.shared.drawfile import (
    DrawFile,
    DrawFileIO,
    Missing,
    build,
    column_kind,
    default_name,
    parse,
    relative_paths,
    resolve,
)

#: Drawing settings of the page's shape (`captureSettings()` of app.js).
SETTINGS = {
    "zones": {
        "encoding": {
            "x": ["amount"],
            "y": ["shop"],
            "color": None,
            "symbol": "shop",
            "row": None,
            "col": None,
            "wrap": None,
            "elements": ["points"],
        },
        "numeric": [["amount", True], ["shop", False]],
        "temporal": [["amount", None], ["shop", None]],
        "stashed": ["symbol"],
    },
    "elements": {"chosen": ["points"], "blocked": ["smooth"]},
    "options": {
        "colorBins": None,
        "smoothing": {"method": "lowess", "frac": 0.3},
        "shapeSize": 9,
        "lineWidth": None,
        "lineAggregation": "mean",
        "showNullRows": {"color": True},
        "keepLevels": {"color": False, "symbol": False},
        "wrapCols": None,
        "levelSizes": [["shop", {"a": 4}]],
        "levelShapes": {"column": "shop", "shapes": {"a": "square"}},
    },
    "axes": {
        "dialog": [
            [
                "amount",
                {
                    "dtick": None,
                    "unit": None,
                    "minor": None,
                    "lines": [{"type": "sigma", "value": 2, "color": "#c00", "dash": "dash"}],
                    "format": "auto",
                    "digits": None,
                    "separators": False,
                },
            ]
        ],
        "angles": [["x:amount", 45]],
        "logs": {"x": ["amount"], "y": []},
        "reversed": {"x": [], "y": []},
        "keepLevels": [],
    },
    "filters": [
        {
            "name": "shop",
            "numeric": False,
            "range": None,
            "levels": ["a"],
            "contains": "",
            "nulls": {"pick": False},
            "mode": "pick",
            "query": "",
            "order": "name",
        }
    ],
}
COLUMNS = {"amount": "numeric", "shop": "categorical"}


def _with(path: str, value: object) -> dict:
    """Return `SETTINGS` with the key at the dotted `path` set to `value`, or removed for `...`."""
    settings = copy.deepcopy(SETTINGS)
    *parents, last = path.split(".")
    place = settings
    for key in parents:
        place = place[int(key)] if isinstance(place, list) else place[key]
    if value is ...:
        del place[last]
    else:
        place[last] = value
    return settings


def _text(**changes: object) -> str:
    """Return the text of a valid file, with `changes` to its keys (None removes one)."""
    content = build(SETTINGS, COLUMNS, [r"D:\data\a.parquet"], False, None, "0.1.6")
    for key, value in changes.items():
        if value is None:
            del content[key]
        else:
            content[key] = value
    return json.dumps(content)


def test_build_writes_the_format_and_the_paths_from_the_file() -> None:
    """The file holds the format, the input with its paths from the file's folder, the columns and the settings."""
    saved_at = dt.datetime(2026, 11, 18, 14, 30, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    content = build(
        SETTINGS,
        COLUMNS,
        [r"D:\data\sales\2026.parquet", r"d:\DATA\other"],
        True,
        PureWindowsPath(r"D:\data\graph.ddviz.json"),
        "0.1.6",
        saved_at,
    )
    assert content == {
        "format": "ddviz-draw-settings",
        "version": 5,
        "app_version": "0.1.6",
        "saved_at": "2026-11-18T14:30:00+09:00",
        "source": {
            "paths": [r"D:\data\sales\2026.parquet", r"d:\DATA\other"],
            "relative": [r"sales\2026.parquet", "other"],
            "recursive": True,
            "join": None,
        },
        "columns": COLUMNS,
        "settings": SETTINGS,
    }


def test_relative_paths_go_up_and_are_none_on_another_drive() -> None:
    """A path above the file goes up with `..`; any path on another drive makes them all None."""
    json_path = PureWindowsPath(r"C:\work\graphs\g.json")
    paths = [PureWindowsPath(r"C:\work\data\a.parquet"), PureWindowsPath(r"C:\work\graphs")]
    assert relative_paths(paths, json_path) == [r"..\data\a.parquet", "."]
    paths.append(PureWindowsPath(r"D:\data\b.parquet"))
    assert relative_paths(paths, json_path) is None
    assert (
        build(SETTINGS, COLUMNS, [str(p) for p in paths], False, json_path, "0")["source"]["relative"]
        is None
    )


def test_a_browsers_file_has_no_relative_paths() -> None:
    """Without where the file goes (a download), `relative` is null."""
    content = build(SETTINGS, COLUMNS, [r"C:\a.parquet"], False, None, "0")
    assert content["source"]["relative"] is None


def test_parse_reads_what_build_wrote() -> None:
    """A file built reads back with its input and content."""
    draw = parse(_text())
    assert draw == DrawFile(
        paths=[r"D:\data\a.parquet"],
        relative=None,
        recursive=False,
        content=json.loads(_text()),
        join=None,
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "Could not read the drawing settings file: not JSON ("),
        ("[]", "Could not read the drawing settings file: not a JSON object"),
        (
            _text(format="other"),
            "Could not read the drawing settings file: format is not ddviz-draw-settings",
        ),
        (_text(version=None), "Could not read the drawing settings file: key version is missing"),
        (_text(settings=None), "Could not read the drawing settings file: key settings is missing"),
        (_text(columns=None), "Could not read the drawing settings file: key columns is missing"),
        (
            _text(source={"paths": ["a"], "recursive": False, "join": None}),
            "Could not read the drawing settings file: key source.relative is missing",
        ),
        (
            _text(source={"paths": [], "relative": None, "recursive": False, "join": None}),
            "Could not read the drawing settings file: key source.paths has a value of the wrong shape",
        ),
        (_text(version=1), "These drawing settings cannot be read (version 1; this ddviz reads version 5)."),
        (_text(version=2), "These drawing settings cannot be read (version 2; this ddviz reads version 5)."),
        (_text(version=3), "These drawing settings cannot be read (version 3; this ddviz reads version 5)."),
        (_text(version=4), "These drawing settings cannot be read (version 4; this ddviz reads version 5)."),
    ],
    ids=[
        "broken", "not-object", "format", "version-key", "settings", "columns", "relative", "paths", "version-1",
        "version-2", "version-3", "version-4",
    ],
)
def test_parse_refuses_with_the_message_shown(text: str, message: str) -> None:
    """Broken JSON, another format, a key missing or of the wrong form and another version are refused with the chooser's message."""
    with pytest.raises(ValueError) as caught:
        parse(text)
    assert str(caught.value).startswith(message)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        ("elements", ..., "key settings.elements is missing"),
        ("zones.encoding.x", "amount", "key settings.zones.encoding.x has a value of the wrong shape"),
        ("zones.encoding.wrap", ..., "key settings.zones.encoding.wrap is missing"),
        ("zones.numeric", [["amount"]], "key settings.zones.numeric[0] has a value of the wrong shape"),
        ("options.levelSizes", None, "key settings.options.levelSizes has a value of the wrong shape"),
        ("options.levelShapes", {"column": "shop"}, "key settings.options.levelShapes.shapes is missing"),
        ("axes.logs", {"x": []}, "key settings.axes.logs.y is missing"),
        ("axes.dialog", [["amount", 1]], "key settings.axes.dialog[0][1] has a value of the wrong shape"),
        ("filters.0.name", ..., "key settings.filters[0].name is missing"),
        ("filters.0.numeric", 0, "key settings.filters[0].numeric has a value of the wrong shape"),
        ("options.smoothing", None, "key settings.options.smoothing has a value of the wrong shape"),
        ("options.smoothing", {}, "key settings.options.smoothing.method is missing"),
        ("options.smoothing", {"method": "spline"}, "key settings.options.smoothing.method has a value of the wrong shape"),
        ("options.colorBins", 5, "key settings.options.colorBins has a value of the wrong shape"),
        ("options.shapeSize", "9", "key settings.options.shapeSize has a value of the wrong shape"),
        ("options.lineAggregation", None, "key settings.options.lineAggregation has a value of the wrong shape"),
        ("axes.dialog.0.1.lines", [{"type": "mean"}], "key settings.axes.dialog[0][1].lines[0].type has a value of the wrong shape"),
        ("axes.dialog.0.1.format", ..., "key settings.axes.dialog[0][1].format is missing"),
        ("axes.angles", [["x:amount", "45"]], "key settings.axes.angles[0][1] has a value of the wrong shape"),
        ("filters.0.mode", None, "key settings.filters[0].mode has a value of the wrong shape"),
    ],
    ids=[
        "elements", "x", "wrap", "numeric", "level-sizes", "level-shapes", "logs", "dialog", "card-name",
        "card-numeric", "smoothing-null", "smoothing-empty", "smoothing-method", "color-bins", "shape-size",
        "line-aggregation", "line-type", "dialog-format", "angle", "card-mode",
    ],
)
def test_parse_refuses_settings_the_page_cannot_apply(path: str, value: object, reason: str) -> None:
    """A key of the settings the page reads, missing or of the wrong form, is refused before the data opens (review of PR #336)."""
    with pytest.raises(ValueError) as caught:
        parse(_text(settings=_with(path, value)))
    assert str(caught.value) == f"Could not read the drawing settings file: {reason}"


def test_parse_takes_the_optional_and_any_values() -> None:
    """No shapes of the symbol levels, and any value of a setting the page passes on, are read."""
    settings = _with("options.levelShapes", None)
    settings["options"]["colorBins"] = {"n": 5, "by": "quantile"}
    settings["options"]["smoothing"] = {"method": "csaps", "p": None}
    assert parse(_text(settings=settings)).content["settings"] == settings


def test_resolve_takes_the_absolute_path_then_the_relative_one(tmp_path: Path) -> None:
    """Each input is found at its absolute path, else from the file's folder; a folder counts as found."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.parquet").touch()
    (tmp_path / "moved").mkdir()
    (tmp_path / "moved" / "b.parquet").touch()
    json_path = tmp_path / "graphs" / "g.json"
    paths = [str(tmp_path / "data" / "a.parquet"), str(tmp_path / "gone" / "b.parquet"), str(tmp_path / "data")]
    relative = ["../data/x.parquet", "../moved/b.parquet", "../nothing"]
    assert resolve(paths, relative, json_path) == [
        tmp_path / "data" / "a.parquet",
        tmp_path / "moved" / "b.parquet",
        tmp_path / "data",
    ]


def test_resolve_returns_the_absolute_paths_found_nowhere(tmp_path: Path) -> None:
    """An input at neither path is missing, by its absolute path; so is any without relative paths."""
    (tmp_path / "a.parquet").touch()
    gone = str(tmp_path / "gone.parquet")
    assert resolve([str(tmp_path / "a.parquet"), gone], None, tmp_path / "g.json") == Missing([gone])
    assert resolve([gone], ["also-gone.parquet"], tmp_path / "g.json") == Missing([gone])


def test_column_kind_and_default_name() -> None:
    """The kinds are the page's three; the default name drops a file's extension, not a folder's."""
    assert column_kind({"numeric": True, "temporal": "date"}) == "temporal:date"
    assert column_kind({"numeric": True, "temporal": None}) == "numeric"
    assert column_kind({"numeric": False, "temporal": None}) == "categorical"
    assert default_name(PureWindowsPath(r"D:\data\2026.parquet"), False) == "2026.ddviz.json"
    assert default_name(PureWindowsPath(r"D:\data\v1.2"), True) == "v1.2.ddviz.json"


# ---- the table joined to the input (Issue #345, #358) ----

#: A join by keys, as the file's `build` is given it.
JOIN = {
    "paths": [r"D:\data\lots\a.parquet", r"D:\data\lots\b.parquet"],
    "recursive": False,
    "kind": "key",
    "keys": [{"left": "lot", "right": "lot_id"}],
    "columns": None,
    "same_names": "skip_equal",
}


def _joined(**changes: object) -> dict:
    """Return the ``source.join`` of a valid file, with `changes` to its keys (``...`` removes one)."""
    join = {**JOIN, "relative": None}
    for key, value in changes.items():
        if value is ...:
            del join[key]
        else:
            join[key] = value
    return join


def _source(join: object) -> dict:
    return {"paths": [r"D:\data\a.parquet"], "relative": None, "recursive": False, "join": join}


def test_build_writes_the_join_with_its_paths_from_the_file() -> None:
    """The join is kept as it was given, with its paths from the file's folder; null on another drive or without where the file goes."""
    json_path = PureWindowsPath(r"D:\data\graph.ddviz.json")
    content = build(SETTINGS, COLUMNS, [r"D:\data\a.parquet"], False, json_path, "0", join=JOIN)
    assert content["source"]["join"] == {**JOIN, "relative": [r"lots\a.parquet", r"lots\b.parquet"]}
    other = {**JOIN, "paths": [r"D:\data\lots\a.parquet", r"E:\b.parquet"]}
    content = build(SETTINGS, COLUMNS, [r"D:\data\a.parquet"], False, json_path, "0", join=other)
    assert content["source"]["join"]["relative"] is None
    content = build(SETTINGS, COLUMNS, [r"D:\data\a.parquet"], False, None, "0", join=JOIN)
    assert content["source"]["join"] == {**JOIN, "relative": None}
    assert build(SETTINGS, COLUMNS, [r"D:\data\a.parquet"], False, json_path, "0")["source"]["join"] is None
    for added in (
        {"columns": ["yield", "line"], "same_names": None},
        {"columns": None, "same_names": "skip"},
        {"columns": None, "same_names": "skip_equal"},
    ):
        content = build(SETTINGS, COLUMNS, [r"D:\data\a.parquet"], False, None, "0", join={**JOIN, **added})
        assert content["source"]["join"] == {**JOIN, **added, "relative": None}


@pytest.mark.parametrize(
    "join",
    [
        None,
        _joined(),
        _joined(kind="rows", keys=[]),
        _joined(relative=["a", "b"], recursive=True),
        _joined(columns=["yield", "line"], same_names=None),
        _joined(same_names="skip"),
        _joined(same_names="skip_equal"),
    ],
    ids=["null", "key", "rows", "relative", "columns", "skip", "skip-equal"],
)
def test_parse_reads_a_join(join: dict | None) -> None:
    """A null join, or one of either kind with or without relative paths, all its columns or some, reads back."""
    assert parse(_text(source=_source(join))).join == join


@pytest.mark.parametrize(
    ("join", "reason"),
    [
        ("absent", "key source.join is missing"),
        (_joined(keys=...), "key source.join has a value of the wrong shape"),
        (_joined(relative=...), "key source.join has a value of the wrong shape"),
        (_joined(kind="outer"), "key source.join has a value of the wrong shape"),
        (_joined(keys=[]), "key source.join has a value of the wrong shape"),
        (_joined(kind="rows"), "key source.join has a value of the wrong shape"),
        (_joined(relative=["a"]), "key source.join has a value of the wrong shape"),
        (_joined(paths=[]), "key source.join has a value of the wrong shape"),
        (_joined(recursive=None), "key source.join has a value of the wrong shape"),
        (_joined(keys=[{"left": "lot"}]), "key source.join has a value of the wrong shape"),
        ([], "key source.join has a value of the wrong shape"),
        (_joined(columns=[]), "key source.join has a value of the wrong shape"),
        (_joined(columns=["yield", 1]), "key source.join has a value of the wrong shape"),
        (_joined(columns="yield"), "key source.join has a value of the wrong shape"),
        (_joined(same_names="drop"), "key source.join has a value of the wrong shape"),
        (_joined(same_names="rename"), "key source.join has a value of the wrong shape"),
        (_joined(same_names=None), "key source.join has a value of the wrong shape"),
        (_joined(columns=["yield"], same_names="skip_equal"), "key source.join has a value of the wrong shape"),
        (_joined(columns=["yield"], same_names="skip"), "key source.join has a value of the wrong shape"),
        (_joined(columns=["yield"], same_names="rename"), "key source.join has a value of the wrong shape"),
        (_joined(columns=...), "key source.join has a value of the wrong shape"),
        (_joined(same_names=...), "key source.join has a value of the wrong shape"),
    ],
    ids=[
        "absent", "keys-missing", "relative-missing", "kind", "key-without-keys", "rows-with-keys",
        "relative-length", "paths-empty", "recursive", "pair", "not-object", "columns-empty", "columns-not-text",
        "columns-text", "same-names", "rename", "same-names-null", "columns-with-skip-equal", "columns-with-skip",
        "columns-with-rename", "columns-missing",
        "same-names-missing",
    ],
)
def test_parse_refuses_a_join_of_the_wrong_form(join: object, reason: str) -> None:
    """A join missing a key, of another kind, with keys that do not fit its kind or relative paths of another length is refused."""
    source = _source(join)
    if join == "absent":
        del source["join"]
    with pytest.raises(ValueError) as caught:
        parse(_text(source=source))
    assert str(caught.value) == f"Could not read the drawing settings file: {reason}"


def test_draw_file_io_finds_the_join_and_writes_its_paths_from_the_file(tmp_path: Path) -> None:
    """`write` fills the join's relative paths from where it is saved; `read` finds the table joined there once moved, or tells the paths missing."""
    old = tmp_path / "old"
    (old / "lots").mkdir(parents=True)
    (old / "a.parquet").touch()
    (old / "lots" / "b.parquet").touch()
    join = {**JOIN, "paths": [str(old / "lots" / "b.parquet")]}
    content = build(SETTINGS, COLUMNS, [str(old / "a.parquet")], False, None, "0", join=join)
    io = DrawFileIO()
    io.write(content, old / "graph.json")
    written = json.loads((old / "graph.json").read_text(encoding="utf-8"))
    assert written["source"]["join"] == {**join, "relative": [str(Path("lots") / "b.parquet")]}

    new = tmp_path / "new"
    old.rename(new)
    opened = io.read(new / "graph.json")
    assert (opened.found, opened.missing) == ([str(new / "a.parquet")], [])
    assert (opened.join_found, opened.join_missing) == ([str(new / "lots" / "b.parquet")], [])
    (new / "lots" / "b.parquet").unlink()
    opened = io.read(new / "graph.json")
    assert (opened.join_found, opened.join_missing) == ([], [str(old / "lots" / "b.parquet")])
    io.write(build(SETTINGS, COLUMNS, [str(new / "a.parquet")], False, None, "0"), new / "plain.json")
    assert io.read(new / "plain.json").join_missing == []


@pytest.mark.skipif(sys.platform != "win32", reason="drives are Windows'")
def test_draw_file_io_writes_no_relative_join_on_another_drive(tmp_path: Path) -> None:
    """A table joined on another drive than where the file is saved has no relative paths."""
    drive = "Z:" if tmp_path.drive.upper() != "Z:" else "Y:"
    join = {**JOIN, "paths": [rf"{drive}\lots\b.parquet"]}
    content = build(SETTINGS, COLUMNS, [str(tmp_path / "a.parquet")], False, None, "0", join=join)
    DrawFileIO().write(content, tmp_path / "graph.json")
    written = json.loads((tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert written["source"]["join"]["relative"] is None
    assert written["source"]["relative"] == ["a.parquet"]
