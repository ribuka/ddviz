"""The missing level of the Color and Overlay roles: their rows whose value is null or NaN.

With ``Show null rows`` on (`ddviz.shared.scatter.ScatterSpec.null_roles`),
the rows of a color or overlay column whose value is null, or NaN, are drawn
as a level of their own, after the column's other levels. The level is
`MISSING`, a name no column's text can collide with in practice; the page
shows it as `MISSING_TEXT` and marks a real ``"(null)"`` text as text
(``static/js/names.js``).
"""

from __future__ import annotations

# The missing level among a role's levels, always the last one.
MISSING = "\x00null"
# How the page shows it.
MISSING_TEXT = "(null)"
# The mark of a real `MISSING_TEXT` text beside the missing level.
TEXT_NOTE = "（文字列）"
# Its default color, on the color role.
MISSING_COLOR = "#808080"
# Its default shape, on the overlay role when it draws shapes; the shapes
# the other overlay levels take by their place leave it out
# (`ddviz.shared.shapes.default_shape`).
MISSING_SHAPE = "x"
# Roles that can draw their missing level.
NULL_ROLES = ("color", "overlay")


def has_missing(levels: list) -> bool:
    """Return whether a role's levels end in the missing level.

    Parameters
    ----------
    levels : list
        The role's levels as text.

    Returns
    -------
    bool
        True when the last level is `MISSING`.
    """
    return bool(levels) and levels[-1] == MISSING


def shown_level(value: object, levels: list) -> str:
    """Return a level's name as shown: `MISSING_TEXT` for the missing level.

    Parameters
    ----------
    value : object
        The level.
    levels : list
        The role's levels; a real ``"(null)"`` text among them is marked as
        text when the missing level is drawn too (`TEXT_NOTE`).

    Returns
    -------
    str
        The name.
    """
    if value == MISSING:
        return MISSING_TEXT
    text = str(value)
    if text == MISSING_TEXT and has_missing(levels):
        return text + TEXT_NOTE
    return text
