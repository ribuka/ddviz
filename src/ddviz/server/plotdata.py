"""The file of a plot's data to save (`ddviz.compute.tasks.plotdata`): its media type and name."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

FORMATS = {
    "csv": "text/csv; charset=utf-8",
    "parquet": "application/vnd.apache.parquet",
}


def file_name(source: str, file_format: str, moment: datetime) -> str:
    """Return the name of a saved file: ``<input's name>_<YYYYMMDD-HHMMSS>.<format>``.

    Characters a file name may not hold, and spaces, become ``_``.

    Parameters
    ----------
    source : str
        The Parquet file or folder plotted.
    file_format : str
        ``"csv"`` or ``"parquet"``.
    moment : datetime.datetime
        When the file is saved.

    Returns
    -------
    str
        The file's name.
    """
    stem = Path(source).name.removesuffix(".parquet")
    stem = re.sub(r'[\/:*?"<>|\s\x00-\x1f]+', "_", stem).strip("_.")
    return f"{stem or 'ddviz'}_{moment:%Y%m%d-%H%M%S}.{file_format}"
