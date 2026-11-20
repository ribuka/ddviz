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
        "version": 2,
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
        ("{", "描画設定のファイルを読めませんでした：JSON ではありません"),
        ("[]", "描画設定のファイルを読めませんでした：JSON のオブジェクトではありません"),
        (
            _text(format="other"),
            "描画設定のファイルを読めませんでした：format が ddviz-draw-settings ではありません",
        ),
        (_text(version=None), "描画設定のファイルを読めませんでした：キー version がありません"),
        (_text(settings=None), "描画設定のファイルを読めませんでした：キー settings がありません"),
        (_text(columns=None), "描画設定のファイルを読めませんでした：キー columns がありません"),
        (
            _text(source={"paths": ["a"], "recursive": False, "join": None}),
            "描画設定のファイルを読めませんでした：キー source.relative がありません",
        ),
        (
            _text(source={"paths": [], "relative": None, "recursive": False, "join": None}),
            "描画設定のファイルを読めませんでした：キー source.paths の値の形が違います",
        ),
        (_text(version=1), "この描画設定は読めません（版 1。この ddviz は版 2 を読みます）"),
    ],
    ids=["broken", "not-object", "format", "version-key", "settings", "columns", "relative", "paths", "version-1"],
)
def test_parse_refuses_with_the_message_shown(text: str, message: str) -> None:
    """Broken JSON, another format, a key missing or of the wrong form and another version are refused with the chooser's message."""
    with pytest.raises(ValueError) as caught:
        parse(text)
    assert str(caught.value).startswith(message)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        ("elements", ..., "キー settings.elements がありません"),
        ("zones.encoding.x", "amount", "キー settings.zones.encoding.x の値の形が違います"),
        ("zones.encoding.wrap", ..., "キー settings.zones.encoding.wrap がありません"),
        ("zones.numeric", [["amount"]], "キー settings.zones.numeric[0] の値の形が違います"),
        ("options.levelSizes", None, "キー settings.options.levelSizes の値の形が違います"),
        ("options.levelShapes", {"column": "shop"}, "キー settings.options.levelShapes.shapes がありません"),
        ("axes.logs", {"x": []}, "キー settings.axes.logs.y がありません"),
        ("axes.dialog", [["amount", 1]], "キー settings.axes.dialog[0][1] の値の形が違います"),
        ("filters.0.name", ..., "キー settings.filters[0].name がありません"),
        ("filters.0.numeric", 0, "キー settings.filters[0].numeric の値の形が違います"),
        ("options.smoothing", None, "キー settings.options.smoothing の値の形が違います"),
        ("options.smoothing", {}, "キー settings.options.smoothing.method がありません"),
        ("options.smoothing", {"method": "spline"}, "キー settings.options.smoothing.method の値の形が違います"),
        ("options.colorBins", 5, "キー settings.options.colorBins の値の形が違います"),
        ("options.shapeSize", "9", "キー settings.options.shapeSize の値の形が違います"),
        ("options.lineAggregation", None, "キー settings.options.lineAggregation の値の形が違います"),
        ("axes.dialog.0.1.lines", [{"type": "mean"}], "キー settings.axes.dialog[0][1].lines[0].type の値の形が違います"),
        ("axes.dialog.0.1.format", ..., "キー settings.axes.dialog[0][1].format がありません"),
        ("axes.angles", [["x:amount", "45"]], "キー settings.axes.angles[0][1] の値の形が違います"),
        ("filters.0.mode", None, "キー settings.filters[0].mode の値の形が違います"),
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
    assert str(caught.value) == f"描画設定のファイルを読めませんでした：{reason}"


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


# ---- the table joined to the input (Issue #345) ----

#: A join by keys, as the file's `build` is given it.
JOIN = {
    "paths": [r"D:\data\lots\a.parquet", r"D:\data\lots\b.parquet"],
    "recursive": False,
    "kind": "key",
    "keys": [{"left": "lot", "right": "lot_id"}],
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


@pytest.mark.parametrize(
    "join",
    [None, _joined(), _joined(kind="rows", keys=[]), _joined(relative=["a", "b"], recursive=True)],
    ids=["null", "key", "rows", "relative"],
)
def test_parse_reads_a_join(join: dict | None) -> None:
    """A null join, or one of either kind with or without relative paths, reads back."""
    assert parse(_text(source=_source(join))).join == join


@pytest.mark.parametrize(
    ("join", "reason"),
    [
        ("absent", "キー source.join がありません"),
        (_joined(keys=...), "キー source.join の値の形が違います"),
        (_joined(relative=...), "キー source.join の値の形が違います"),
        (_joined(kind="outer"), "キー source.join の値の形が違います"),
        (_joined(keys=[]), "キー source.join の値の形が違います"),
        (_joined(kind="rows"), "キー source.join の値の形が違います"),
        (_joined(relative=["a"]), "キー source.join の値の形が違います"),
        (_joined(paths=[]), "キー source.join の値の形が違います"),
        (_joined(recursive=None), "キー source.join の値の形が違います"),
        (_joined(keys=[{"left": "lot"}]), "キー source.join の値の形が違います"),
        ([], "キー source.join の値の形が違います"),
    ],
    ids=[
        "absent", "keys-missing", "relative-missing", "kind", "key-without-keys", "rows-with-keys",
        "relative-length", "paths-empty", "recursive", "pair", "not-object",
    ],
)
def test_parse_refuses_a_join_of_the_wrong_form(join: object, reason: str) -> None:
    """A join missing a key, of another kind, with keys that do not fit its kind or relative paths of another length is refused."""
    source = _source(join)
    if join == "absent":
        del source["join"]
    with pytest.raises(ValueError) as caught:
        parse(_text(source=source))
    assert str(caught.value) == f"描画設定のファイルを読めませんでした：{reason}"


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
