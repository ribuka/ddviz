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
# Width of each ASCII character in plotly's 12px font ('"Open Sans", verdana,
# arial, sans-serif'), in pixels, measured in Chrome on Windows 11
# (2026-11-01; docs/spec.md, "最悪のデータでの表示"). A wide or full-width
# character (CJK) takes `WIDE_PX`, an emoji or other symbol `SYMBOL_PX`, any
# other `OTHER_PX` (the widest of the common ASCII). `MARGIN` leaves room for
# a font that draws a little wider (another fallback, as on the CI runner).
_ASCII_PX = {
    **dict.fromkeys("0123456789$*_`", 7.63),
    **dict.fromkeys("#+<=>^~w", 9.82),
    **dict.fromkeys("()-/:;[\\]|", 5.45),
    **dict.fromkeys("{}", 7.62),
    **dict.fromkeys(",.", 4.37),
    " ": 4.22, "!": 4.72, '"': 5.51, "%": 12.91, "&": 8.72, "'": 3.22,
    "?": 6.54, "@": 12.0,
    "A": 8.2, "B": 8.23, "C": 8.38, "D": 9.25, "E": 7.59, "F": 6.9, "G": 9.3,
    "H": 9.02, "I": 5.05, "J": 5.46, "K": 8.31, "L": 6.68, "M": 10.11,
    "N": 8.98, "O": 9.45, "P": 7.24, "Q": 9.45, "R": 8.34, "S": 8.2, "T": 7.39,
    "U": 8.78, "V": 8.2, "W": 11.87, "X": 8.22, "Y": 7.38, "Z": 8.22,
    "a": 7.21, "b": 7.48, "c": 6.25, "d": 7.48, "e": 7.15, "f": 4.22, "g": 7.48,
    "h": 7.59, "i": 3.29, "j": 4.13, "k": 7.1, "l": 3.29, "m": 11.67, "n": 7.59,
    "o": 7.28, "p": 7.48, "q": 7.48, "r": 5.12, "s": 6.25, "t": 4.73, "u": 7.59,
    "v": 7.1, "x": 7.1, "y": 7.1, "z": 6.3,
}
WIDE_PX = 12.0
SYMBOL_PX = 16.5
OTHER_PX = 9.82
MARGIN = 1.1
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
        Its width in pixels, taken `MARGIN` times wider than measured.
    """
    return MARGIN * sum(_char_width(c) for c in text)


def _char_width(c: str) -> float:
    """Return the measured width of one character in pixels (see `_ASCII_PX`)."""
    if c in _ASCII_PX:
        return _ASCII_PX[c]
    # An emoji (outside the basic plane) is wider than a CJK character.
    if ord(c) > 0xFFFF:
        return SYMBOL_PX
    if unicodedata.east_asian_width(c) in "WF":
        return WIDE_PX
    if unicodedata.category(c) == "So":
        return SYMBOL_PX
    return OTHER_PX


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
    room = pixels - text_width(ELLIPSIS)
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
    if room >= text_width(column[:MIN_NAME] + ELLIPSIS):
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
