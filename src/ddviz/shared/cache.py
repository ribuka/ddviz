"""Column cache: per source file, one Parquet file per column, made on first use.

The UI server owns the cache and never imports polars: it decides which
columns to convert, hands them to a worker (`ddviz.compute.convert`), and evicts old
files. A column file's modification time is the time it was last used.

An input (one Parquet file, a folder of them or several files,
`ddviz.shared.inputs`) has a directory named by its path (several files: by
their paths). In it, each source file has a directory named by its path
relative to the input (several files: to their common folder), holding a
part of each converted column: the column's values in that file, cast to
the input's type of the column, or nulls when the file lacks it. A column of
the input is its parts in the order of the files, read with one scan
(`ddviz.compute.scan`). A changed file loses only its own parts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

from ddviz.shared.inputs import input_base, relative_name

SOURCE = "source.json"
PARTIAL = ".tmp"
DAY = 86400.0
# Empty Parquet file with the input's type of every column, written by the
# schema task and kept in the input's directory.
SCHEMA = "schema.parquet"
# Files of an input's directory made from all its source files: they go
# whenever a file is added, removed or changed.
DERIVED = ("schema.json", SCHEMA, "nonnull.json")


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


def _key(text: str) -> str:
    """Return a short name made from `text`, safe as a file name."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _identity(file: Path) -> dict:
    """Return what tells a source file apart from a changed one."""
    stat = file.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class ColumnCache:
    """The cached columns of an input.

    Opening the cache discards the parts of source files that changed (size
    or modification time) or are gone since the parts were made, the files
    made from all the source files (`DERIVED`) when any file was added,
    removed or changed, and files a conversion left unfinished.

    Parameters
    ----------
    root : pathlib.Path
        Directory holding the caches of all inputs.
    source : list of pathlib.Path
        The input (`ddviz.shared.inputs.unique`): a Parquet file, a folder,
        or several Parquet files. Several files are one input by the set of
        their paths: another choice of files is another input, even in the
        same folder, so that it keeps the parts of neither.
    files : list of pathlib.Path
        Its Parquet files in reading order (`ddviz.shared.inputs.parquet_files`).
    """

    def __init__(self, root: Path, source: list[Path], files: list[Path]) -> None:
        source = [p.resolve() for p in source]
        files = [f.resolve() for f in files]
        if len(source) == 1:
            path: str | list[str] = str(source[0])
            key = os.path.normcase(path)
        else:
            path = [str(f) for f in files]
            key = "\0".join(os.path.normcase(p) for p in path)
        self.dir = root / _key(key)
        base = input_base(source)
        names = [relative_name(f, base) for f in files]
        self._dirs = [self.dir / f"f{_key(os.path.normcase(n))}" for n in names]
        identity = {
            "path": path,
            "files": {n: _identity(f) for n, f in zip(names, files, strict=True)},
        }
        marker = self.dir / SOURCE
        recorded = (
            json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
        )
        if recorded != identity:
            self._discard(recorded, identity)
            marker.write_text(json.dumps(identity), encoding="utf-8")
        for partial in self.dir.glob("*/*" + PARTIAL):
            partial.unlink(missing_ok=True)

    def _discard(self, recorded: dict | None, identity: dict) -> None:
        """Remove what no longer matches the source files."""
        if recorded is None or recorded.get("path") != identity["path"]:
            shutil.rmtree(self.dir, ignore_errors=True)
        else:
            files = identity["files"]
            for name, before in recorded.get("files", {}).items():
                if files.get(name) != before:
                    shutil.rmtree(
                        self.dir / f"f{_key(os.path.normcase(name))}",
                        ignore_errors=True,
                    )
            for name in DERIVED:
                (self.dir / name).unlink(missing_ok=True)
        self.dir.mkdir(parents=True, exist_ok=True)

    def parts(self, column: str, dtype: str) -> list[Path]:
        """Return the parts of a column, one per source file; they may not exist yet.

        Parameters
        ----------
        column : str
            Column name.
        dtype : str
            The input's type of the column. Parts are named by the name and
            the type, since names may not be valid file names and a file
            added with another type can change the input's type.

        Returns
        -------
        list of pathlib.Path
            The parts in the order of the source files.
        """
        name = f"c{_key(column + chr(0) + dtype)}.parquet"
        return [d / name for d in self._dirs]

    def missing(self, columns: dict[str, str]) -> dict[str, list[int]]:
        """Return the parts not converted yet.

        Parameters
        ----------
        columns : dict of str to str
            The type of each column.

        Returns
        -------
        dict of str to list of int
            Per column with missing parts, the positions of their source
            files.
        """
        missing = {}
        for column, dtype in columns.items():
            gaps = [
                i for i, p in enumerate(self.parts(column, dtype)) if not p.exists()
            ]
            if gaps:
                missing[column] = gaps
        return missing

    def touch(self, columns: dict[str, str]) -> None:
        """Mark columns as used now.

        Parameters
        ----------
        columns : dict of str to str
            The type of each column whose parts exist.
        """
        for column, dtype in columns.items():
            for part in self.parts(column, dtype):
                os.utime(part)


def evict(
    root: Path,
    max_bytes: int,
    max_unused_days: float,
    keep: Iterable[Path] = (),
    now: float | None = None,
) -> list[Path]:
    """Remove column parts unused for too long, then the least recently used past the size limit.

    A column that loses some of its parts has the missing ones converted
    again when used.

    Parameters
    ----------
    root : pathlib.Path
        Directory holding the caches of all inputs.
    max_bytes : int
        Total size the column parts may take.
    max_unused_days : float
        Parts unused for longer are removed.
    keep : iterable of pathlib.Path
        Parts never removed, such as the columns of the current plot.
    now : float, optional
        Current time in seconds since the epoch.

    Returns
    -------
    list of pathlib.Path
        The removed parts. A part another process holds open is skipped.
    """
    now = time.time() if now is None else now
    kept = {Path(p).resolve() for p in keep}
    files = []
    for path in root.glob("*/f*/c*.parquet"):
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
