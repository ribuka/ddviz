"""Tests of the figure's label text: levels as shown, fitted to their room."""

from __future__ import annotations

from ddviz.server.labeltext import (
    EMPTY_LEVEL,
    NARROW_PX,
    WIDE_PX,
    facet_text,
    fit_text,
    level_text,
    plotly_text,
    text_width,
)


def test_an_empty_level_shows_a_placeholder() -> None:
    """Only the empty string is replaced; other levels are their text."""
    assert level_text("") == EMPTY_LEVEL
    assert level_text(" ") == " "
    assert level_text(3) == "3"


def test_wide_characters_count_wider() -> None:
    """A CJK or full-width character takes the wide width, the others the narrow."""
    assert text_width("ab") == 2 * NARROW_PX
    assert text_width("日本Ａ") == 3 * WIDE_PX


def test_a_text_that_fits_stays_whole() -> None:
    """A text no wider than its room is not cut."""
    assert fit_text("abc", 3 * NARROW_PX) == "abc"


def test_a_long_text_ends_in_an_ellipsis_within_its_room() -> None:
    """A cut text keeps its longest head that fits with the "…"."""
    text = "x" * 200
    fitted = fit_text(text, 100)
    assert fitted.endswith("…")
    assert text_width(fitted[:-1]) + NARROW_PX <= 100
    assert text_width(fitted[:-1]) + 2 * NARROW_PX > 100
    assert fit_text(text, 1) == "…"
    assert fit_text("日本語の長い水準の名前", 5 * WIDE_PX).endswith("…")


def test_a_facet_label_cuts_the_column_name_before_the_level() -> None:
    """The level tells panels apart: the long column name is cut first, then the level alone."""
    name = "very_long_column_name_" * 5
    assert facet_text("g", "a", 200) == "g = a"
    cut = facet_text(name, "level_1", 200)
    assert cut.endswith("… = level_1")
    assert text_width(cut) <= 200
    # No room for a few characters of the name: the level alone, cut.
    alone = facet_text(name, "level_" + "x" * 50, 120)
    assert alone.startswith("level_") and alone.endswith("…")
    assert facet_text("g", "", 200) == f"g = {EMPTY_LEVEL}"


def test_text_for_plotly_is_escaped() -> None:
    """Plotly reads label text as markup; the data's "<", ">" and "&" stay text."""
    assert plotly_text("<b>a</b> & b") == "&lt;b&gt;a&lt;/b&gt; &amp; b"
