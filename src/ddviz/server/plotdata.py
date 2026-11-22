"""The file of rows to save (`ddviz.compute.tasks.plotdata`, `ddviz.compute.joinrows`): its media type and name."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ddviz.shared.inputs import input_name

FORMATS = {
    "csv": "text/csv; charset=utf-8",
    "parquet": "application/vnd.apache.parquet",
}
# What a file's name holds before the time, after the input's name, for the
# rows it holds (`file_name`): the selected rows, or those of a join.
SELECTED = "selected"
JOIN_ROWS = "join_rows"


def file_name(source: list[str], file_format: str, moment: datetime, kind: str = "") -> str:
    """Return the name of a saved file: ``<input's name>[_<kind>]_<YYYYMMDD-HHMMSS>.<format>``.

    Characters a file name may not hold, and spaces, become ``_``. For
    several files, the name is the first one's, then ``_and_<n>_more``.

    Parameters
    ----------
    source : list of str
        The input plotted: a Parquet file or folder, or several Parquet
        files (`ddviz.shared.inputs.input_name`).
    file_format : str
        ``"csv"`` or ``"parquet"``.
    moment : datetime.datetime
        When the file is saved.
    kind : str
        What rows the file holds besides those of the plot, put before the
        time with ``_``: `SELECTED` or `JOIN_ROWS`; empty for none.

    Returns
    -------
    str
        The file's name.
    """
    first, more = input_name([Path(p) for p in source])
    stem = first.removesuffix(".parquet")
    if more:
        stem = f"{stem} and {more} more"
    stem = re.sub(r'[\/:*?"<>|\s\x00-\x1f]+', "_", stem).strip("_.")
    suffix = f"_{kind}" if kind else ""
    return f"{stem or 'ddviz'}{suffix}_{moment:%Y%m%d-%H%M%S}.{file_format}"
