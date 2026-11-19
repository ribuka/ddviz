"""The file of the drawing settings: build, read and find its data (`ddviz.shared.drawfile`, Issue #287)."""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path, PureWindowsPath

import pytest

from ddviz.shared.drawfile import (
    DrawFile,
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
        "version": 1,
        "app_version": "0.1.6",
        "saved_at": "2026-11-18T14:30:00+09:00",
        "source": {
            "paths": [r"D:\data\sales\2026.parquet", r"d:\DATA\other"],
            "relative": [r"sales\2026.parquet", "other"],
            "recursive": True,
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
        paths=[r"D:\data\a.parquet"], relative=None, recursive=False, content=json.loads(_text())
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
            _text(source={"paths": ["a"], "recursive": False}),
            "描画設定のファイルを読めませんでした：キー source.relative がありません",
        ),
        (
            _text(source={"paths": [], "relative": None, "recursive": False}),
            "描画設定のファイルを読めませんでした：キー source.paths の値の形が違います",
        ),
        (_text(version=2), "この描画設定は読めません（版 2。この ddviz は版 1 を読みます）"),
    ],
    ids=["broken", "not-object", "format", "version-key", "settings", "columns", "relative", "paths", "version-2"],
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
    draw = DrawFile(
        paths=[str(tmp_path / "data" / "a.parquet"), str(tmp_path / "gone" / "b.parquet"), str(tmp_path / "data")],
        relative=["../data/x.parquet", "../moved/b.parquet", "../nothing"],
        recursive=False,
        content={},
    )
    assert resolve(draw, json_path) == [
        tmp_path / "data" / "a.parquet",
        tmp_path / "moved" / "b.parquet",
        tmp_path / "data",
    ]


def test_resolve_returns_the_absolute_paths_found_nowhere(tmp_path: Path) -> None:
    """An input at neither path is missing, by its absolute path; so is any without relative paths."""
    (tmp_path / "a.parquet").touch()
    gone = str(tmp_path / "gone.parquet")
    draw = DrawFile(paths=[str(tmp_path / "a.parquet"), gone], relative=None, recursive=False, content={})
    assert resolve(draw, tmp_path / "g.json") == Missing([gone])
    draw = DrawFile(
        paths=[gone], relative=["also-gone.parquet"], recursive=False, content={}
    )
    assert resolve(draw, tmp_path / "g.json") == Missing([gone])


def test_column_kind_and_default_name() -> None:
    """The kinds are the page's three; the default name drops a file's extension, not a folder's."""
    assert column_kind({"numeric": True, "temporal": "date"}) == "temporal:date"
    assert column_kind({"numeric": True, "temporal": None}) == "numeric"
    assert column_kind({"numeric": False, "temporal": None}) == "categorical"
    assert default_name(PureWindowsPath(r"D:\data\2026.parquet"), False) == "2026.ddviz.json"
    assert default_name(PureWindowsPath(r"D:\data\v1.2"), True) == "v1.2.ddviz.json"
