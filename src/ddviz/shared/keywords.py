"""Matching of text against the keywords of a search input.

One rule for the search of column names (`ddviz.server.columns`) and the
substring filter of a categorical column (`ddviz.compute.rowfilter`): the
input splits on white space into lower-cased keywords, and a value matches
when its lower-cased text holds every keyword, in any order and literally.
Lower-casing uses `str.lower` here and `str.to_lowercase` in polars, not
`casefold`, which polars lacks. The module does not import polars, since the
UI server does not load it.
"""

from __future__ import annotations


def keywords(query: str) -> list[str]:
    """Return the keywords of a search input.

    Parameters
    ----------
    query : str
        The input; white space separates the keywords.

    Returns
    -------
    list of str
        The lower-cased keywords; empty for an empty or blank input.
    """
    return query.lower().split()


def matches(value: str, words: list[str]) -> bool:
    """Return whether a value holds every keyword.

    Parameters
    ----------
    value : str
        The text to look in.
    words : list of str
        Keywords from `keywords`; none matches every value.

    Returns
    -------
    bool
        True when the lower-cased value contains each keyword literally.
    """
    text = value.lower()
    return all(w in text for w in words)
