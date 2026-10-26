"""Column cache: one Parquet file per source column, made on first use.

The UI server owns the cache and never imports polars: it decides which
columns to convert, hands them to a worker (`ddviz.convert`), and evicts old
files. A column file's modification time is the time it was last used.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

SOURCE = "source.json"
PARTIAL = ".tmp"
DAY = 86400.0


def default_cache_root() -> Path:
    r"""Return the per-user cache directory, ``%LOCALAPPDATA%\ddviz\cache\columns``.

    Returns
    -------
    pathlib.Path
        The directory, which may not exist.
    """
    base = os.environ.get("LOCALAPPDATA")
    local = Path(base) if base else Path.home() / ".cache"
    return local / "ddviz" / "cache" / "columns"


def _identity(source: Path) -> dict:
    """Return what tells a source file apart from a changed one."""
    stat = source.stat()
    return {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class ColumnCache:
    """The cached columns of one source file.

    Opening the cache discards it when the source changed (size or
    modification time) since the files were made, and removes files a
    conversion left unfinished.

    Parameters
    ----------
    root : pathlib.Path
        Directory holding the caches of all sources.
    source : pathlib.Path
        Parquet file the columns come from.
    columns : list of str
        Column names of the source in schema order; a column's file is named
        by its position, since names may not be valid file names.
    """

    def __init__(self, root: Path, source: Path, columns: list[str]) -> None:
        source = source.resolve()
        key = hashlib.sha256(os.path.normcase(str(source)).encode()).hexdigest()
        self.dir = root / key[:16]
        identity = _identity(source)
        marker = self.dir / SOURCE
        recorded = (
            json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
        )
        if recorded != identity:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(identity), encoding="utf-8")
        for partial in self.dir.glob("*" + PARTIAL):
            partial.unlink(missing_ok=True)
        self._position = {name: i for i, name in enumerate(columns)}

    def file(self, column: str) -> Path:
        """Return the file of a column, which may not exist yet.

        Parameters
        ----------
        column : str
            Column name.

        Returns
        -------
        pathlib.Path
            The file.
        """
        return self.dir / f"c{self._position[column]:06d}.parquet"

    def missing(self, columns: Iterable[str]) -> list[str]:
        """Return the columns not converted yet.

        Parameters
        ----------
        columns : iterable of str
            Column names.

        Returns
        -------
        list of str
            The columns without a file, without duplicates.
        """
        return [c for c in dict.fromkeys(columns) if not self.file(c).exists()]

    def touch(self, columns: Iterable[str]) -> None:
        """Mark columns as used now.

        Parameters
        ----------
        columns : iterable of str
            Column names whose files exist.
        """
        for column in dict.fromkeys(columns):
            os.utime(self.file(column))


def evict(
    root: Path,
    max_bytes: int,
    max_unused_days: float,
    keep: Iterable[Path] = (),
    now: float | None = None,
) -> list[Path]:
    """Remove column files unused for too long, then the least recently used past the size limit.

    Parameters
    ----------
    root : pathlib.Path
        Directory holding the caches of all sources.
    max_bytes : int
        Total size the column files may take.
    max_unused_days : float
        Files unused for longer are removed.
    keep : iterable of pathlib.Path
        Files never removed, such as the columns of the current plot.
    now : float, optional
        Current time in seconds since the epoch.

    Returns
    -------
    list of pathlib.Path
        The removed files. A file another process holds open is skipped.
    """
    now = time.time() if now is None else now
    kept = {Path(p).resolve() for p in keep}
    files = []
    for path in root.glob("*/c*.parquet"):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        files.append((stat.st_mtime, stat.st_size, path))
    files.sort()
    total = sum(size for _, size, _ in files)
    removed = []
    for mtime, size, path in files:
        if path.resolve() in kept:
            continue
        if now - mtime <= max_unused_days * DAY and total <= max_bytes:
            continue
        try:
            path.unlink()
        except (FileNotFoundError, PermissionError):
            continue
        total -= size
        removed.append(path)
    return removed
