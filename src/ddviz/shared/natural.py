"""Natural order of text: runs of digits compare by value (``2`` before ``10``).

Used for the files of a folder (`ddviz.shared.inputs`) and for the levels of
a categorical column (legend, bands, panels, filter cards).
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"(\d+)")


def natural_key(text: str) -> tuple:
    """Return the sort key of a text in natural order.

    Parameters
    ----------
    text : str
        The text, such as a level name or a part of a path.

    Returns
    -------
    tuple
        Its runs of text (without case) and of digits (by value), text
        before digits; the text itself last, so that the order is total
        (``A`` and ``a``, ``01`` and ``1`` keep a fixed order).
    """
    runs = tuple(
        (1, int(run)) if run.isdecimal() else (0, run.casefold())
        for run in _DIGITS.split(text)
        if run
    )
    return (runs, text)
