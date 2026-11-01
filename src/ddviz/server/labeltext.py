"""Text of the figure's labels made from the data: levels as shown, fitted to their room.

The data's levels and column names can be of any length and hold any
characters (docs/spec.md, "最悪のデータでの表示"). A facet label longer than
its panels ends in "…" instead of running over its neighbors, and an empty
string is shown by a placeholder. plotly reads a label's text as its own
markup, so the text that goes to plotly is escaped.
"""

from __future__ import annotations

import html
import unicodedata

# Shown for a level that is an empty string; the same as `EMPTY_LEVEL` in
# ``static/js/names.js``.
EMPTY_LEVEL = "（空文字列）"
# Width of a character of plotly's 12px font, in pixels: a wide one (CJK) and
# the others. Taken a little wide, so that a fitted label is not cut.
WIDE_PX = 12.0
NARROW_PX = 7.0
ELLIPSIS = "…"
# Fewest characters of a facet column's name kept before its level is cut instead.
MIN_NAME = 4


def level_text(level: object) -> str:
    """Return a level as shown: the placeholder for an empty string.

    Parameters
    ----------
    level : object
        A level of a column.

    Returns
    -------
    str
        Its text, or `EMPTY_LEVEL` for "".
    """
    text = str(level)
    return EMPTY_LEVEL if text == "" else text


def text_width(text: str) -> float:
    """Return the estimated width of a text in plotly's 12px font.

    Parameters
    ----------
    text : str
        A label.

    Returns
    -------
    float
        Its width in pixels: `WIDE_PX` for each wide or full-width
        character, `NARROW_PX` for the others.
    """
    return sum(
        WIDE_PX if unicodedata.east_asian_width(c) in "WF" else NARROW_PX
        for c in text
    )


def fit_text(text: str, pixels: float) -> str:
    """Return a text cut to fit a room, ending in "…" when cut.

    Parameters
    ----------
    text : str
        A label.
    pixels : float
        The room along the text, in pixels.

    Returns
    -------
    str
        The text itself when it fits, else its longest head that fits with
        the "…" after it (the "…" alone when none does).
    """
    if text_width(text) <= pixels:
        return text
    room = pixels - NARROW_PX
    used = 0.0
    for i, c in enumerate(text):
        used += text_width(c)
        if used > room:
            return text[:i] + ELLIPSIS
    return text + ELLIPSIS


def facet_text(column: str, level: object, pixels: float) -> str:
    """Return a facet label, "column = level", fitted to its room.

    The level tells the panels apart, so the column's name is cut first;
    the level alone is cut when the room has not even a few characters of
    the name left.

    Parameters
    ----------
    column : str
        The facet column's name.
    level : object
        The panel's level.
    pixels : float
        The room along the label, in pixels.

    Returns
    -------
    str
        The label, cut where it does not fit.
    """
    suffix = f" = {level_text(level)}"
    text = column + suffix
    if text_width(text) <= pixels:
        return text
    room = pixels - text_width(suffix)
    if room >= MIN_NAME * NARROW_PX:
        return fit_text(column, room) + suffix
    return fit_text(level_text(level), pixels)


def plotly_text(text: str) -> str:
    """Return a label's text for plotly, which reads it as its markup.

    Parameters
    ----------
    text : str
        A label made from the data.

    Returns
    -------
    str
        The text with "&", "<" and ">" escaped.
    """
    return html.escape(text, quote=False)
