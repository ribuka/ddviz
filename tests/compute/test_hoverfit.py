"""Tests of choosing the hover columns that fit the limit of the hover files."""

from __future__ import annotations

from ddviz.compute.hoverfit import BIN_BYTES, NPY_HEADER, fit_hover, hover_size

COLUMNS = {"x": 8, "y": 8, "label": 4, "color": 4, "facet": 8}
AXES = ["x", "y"]


def _size(names: list[str]) -> int:
    """Return the hover bytes of 100 bins with 50 bytes of occupancy and `names`."""
    return hover_size(100, 50, [COLUMNS[c] for c in names])


def test_hover_size_counts_every_file() -> None:
    """Keys, count, index, occupancy and each column, with a header per file."""
    assert hover_size(100, 50, [8, 4]) == 100 * (BIN_BYTES + 12) + 50 + 6 * NPY_HEADER


def test_without_a_limit_every_column_is_kept() -> None:
    """No limit keeps the columns in the hover's order."""
    assert fit_hover(COLUMNS, AXES, 100, 50, None) == list(COLUMNS)


def test_columns_off_the_axes_go_last_first() -> None:
    """Past the limit, the last column off the axes goes first, until the files fit."""
    full = _size(list(COLUMNS))
    assert fit_hover(COLUMNS, AXES, 100, 50, full) == list(COLUMNS)
    assert fit_hover(COLUMNS, AXES, 100, 50, full - 1) == ["x", "y", "label", "color"]
    tight = _size(["x", "y", "label"])
    assert fit_hover(COLUMNS, AXES, 100, 50, tight) == ["x", "y", "label"]
    assert fit_hover(COLUMNS, AXES, 100, 50, _size(AXES)) == AXES


def test_no_files_when_the_axes_alone_do_not_fit() -> None:
    """The axis columns stay while the files can have any; else there are none."""
    assert fit_hover(COLUMNS, AXES, 100, 50, _size(AXES) - 1) is None
    assert fit_hover(COLUMNS, AXES, 100, 50, 0) is None
