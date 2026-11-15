"""Codes of text values: an index into their sorted distinct labels, for the files the UI server reads without polars."""

from __future__ import annotations

import numpy as np
import polars as pl


def text_codes(values: pl.Series) -> tuple[np.ndarray, list]:
    """Return the values as text, as Int32 codes into their sorted distinct labels; -1 for a null.

    Parameters
    ----------
    values : polars.Series
        The values, of any type.

    Returns
    -------
    numpy.ndarray
        The codes, as int32.
    list
        The labels: the distinct values as text, sorted.
    """
    text = values.cast(pl.String)
    labels = text.drop_nulls().unique().sort()
    codes = text.replace_strict(
        labels, list(range(len(labels))), default=-1, return_dtype=pl.Int32
    )
    return codes.to_numpy(), labels.to_list()
