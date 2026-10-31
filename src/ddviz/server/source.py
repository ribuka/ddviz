"""The input the server plots, a Parquet file or a folder of them: its schema, column cache and per-column facts.

The schema is read on the first request (Load) and kept in the column cache
until a source file is added, removed or changed. The files of a folder are
read one after another as one table (`ddviz.shared.inputs`). Columns a plot
uses for the first time are converted into the column cache before the plot
task, and the plot reads them from there. The share of non-null values of
each column is measured once after Load and kept in the cache; the filter
pane's summary of a column is computed once per column.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi import HTTPException

from ddviz.server.broker import Pool, TaskBroker
from ddviz.server.errors import ensure_done
from ddviz.server.plan import parse_filters
from ddviz.server.settings import Settings
from ddviz.shared.cache import SCHEMA, ColumnCache, evict
from ddviz.shared.inputs import parquet_files
from ddviz.shared.scatter import Filter
from ddviz.shared.tasks import (
    ConvertTask,
    NonnullTask,
    SchemaTask,
    SourceFiles,
    SummaryTask,
)

# Files in the column cache's directory of an input: its columns, the rows
# of each source file and the columns cast to a common type; and the share
# of non-null values of each column. A later Load needs no task; the cache
# discards them when a source file is added, removed or changed.
SCHEMA_JSON = "schema.json"
NONNULL = "nonnull.json"


class Source:
    """The input of the server and what is known of its columns.

    Parameters
    ----------
    path : str
        Parquet file, or folder of Parquet files, to plot.
    recursive : bool
        For a folder, also read the files in its subfolders.
    cache_root : pathlib.Path
        Directory of the column cache; kept across runs.
    settings : Settings
        Limits of the column cache.
    broker : TaskBroker
        Runs the tasks that read the files.
    """

    def __init__(
        self,
        path: str,
        recursive: bool,
        cache_root: Path,
        settings: Settings,
        broker: TaskBroker,
    ) -> None:
        self.path = path
        self.recursive = recursive
        self._cache_root = cache_root
        self._settings = settings
        self._broker = broker
        self._schema: list[dict] | None = None
        self.files: list[Path] = []
        # Rows of each source file.
        self.rows: list[int] = []
        # Columns whose type differs between the files, with the common type
        # they are read as (`ddviz.compute.tasks.columns.run_schema`).
        self.casts: list[dict] = []
        self._dtypes: dict[str, str] = {}
        self.cache: ColumnCache | None = None
        # Non-null values per column and the rows, ``{"counts", "rows"}``
        # (`ddviz.compute.nonnull`), measured after Load; "pending" until
        # then, "failed" when the task failed.
        self.nonnull: dict | None = None
        self.shares_state = "pending"
        self._shares_task: asyncio.Task | None = None
        # True while a conversion for a plot runs; plots are refused meanwhile.
        self.converting = False
        # One conversion at a time: the filter pane's and a plot's could
        # write the same parts.
        self._convert_lock = asyncio.Lock()
        # The filter pane's summary of each column (`ddviz.compute.summary`).
        self._summaries: dict[str, dict] = {}
        # One summary pool task at a time: a new task kills the running one.
        self._summary_lock = asyncio.Lock()

    async def schema(self) -> list[dict]:
        """Return the columns of the input, reading them on the first call.

        Returns
        -------
        list of dict
            ``{"name", "dtype", "numeric", "temporal"}`` of each column, in
            the order the columns first appear in the files
            (`ddviz.compute.tasks.columns.run_schema`).
        """
        if self._schema is None:
            files = await asyncio.to_thread(
                parquet_files, Path(self.path), self.recursive
            )
            if not files:
                raise HTTPException(400, f"Parquet ファイルがありません：{self.path}")
            self.cache = await asyncio.to_thread(
                ColumnCache, self._cache_root, Path(self.path), files
            )
            self.files = files
            stored = self.cache.dir / SCHEMA_JSON
            found = None
            if stored.exists():
                found = json.loads(stored.read_text(encoding="utf-8"))
            # A schema stored before columns had their temporal kind is read again.
            if found is None or any("temporal" not in c for c in found["columns"]):
                found = await self._read_schema()
            self.rows = found["rows"]
            self.casts = found["casts"]
            self._dtypes = {c["name"]: c["dtype"] for c in found["columns"]}
            await asyncio.to_thread(self.evict, [])
            self._schema = found["columns"]
            stored = self.cache.dir / NONNULL
            if stored.exists():
                self.nonnull = json.loads(stored.read_text(encoding="utf-8"))
                self.shares_state = "done"
            else:
                self._shares_task = asyncio.create_task(self._measure_shares())
        return self._schema

    async def _read_schema(self) -> dict:
        """Run the schema task and keep its result in the column cache."""
        end = await self._broker.run(SchemaTask([str(f) for f in self.files]))
        if end.type != "done":
            end.discard()
            raise HTTPException(500, end.error)
        await asyncio.to_thread(shutil.move, end.out / SCHEMA, self.cache.dir / SCHEMA)
        manifest = end.take()
        found = {k: manifest[k] for k in ("columns", "rows", "casts")}
        _write_json(self.cache.dir / SCHEMA_JSON, found)
        return found

    async def numeric(self) -> dict[str, bool]:
        """Return whether each column is numeric."""
        return {c["name"]: c["numeric"] for c in await self.schema()}

    async def temporal(self) -> dict[str, str]:
        """Return the kind of each temporal column (`ddviz.shared.temporal.KINDS`)."""
        return {c["name"]: c["temporal"] for c in await self.schema() if c["temporal"]}

    def parts(self, column: str) -> list[str]:
        """Return the column's parts in the cache, one per source file."""
        return [str(p) for p in self.cache.parts(column, self._dtypes[column])]

    def source_files(self, columns: list[str]) -> SourceFiles:
        """Return the source files, for reading columns not in the cache.

        Parameters
        ----------
        columns : list of str
            The columns to read.

        Returns
        -------
        SourceFiles
            The files, their rows and the types of the columns.
        """
        return SourceFiles(
            [str(f) for f in self.files],
            self.rows,
            str(self.cache.dir / SCHEMA),
            {c: self._dtypes[c] for c in columns},
        )

    def missing(self, columns: list[str]) -> dict[str, list[int]]:
        """Return the columns with parts not converted yet (`ColumnCache.missing`)."""
        return self.cache.missing({c: self._dtypes[c] for c in dict.fromkeys(columns)})

    def touch(self, columns: list[str]) -> None:
        """Mark columns whose parts exist as used now."""
        self.cache.touch({c: self._dtypes[c] for c in dict.fromkeys(columns)})

    def evict(self, keep: list[Path]) -> None:
        """Remove old column parts, keeping the given ones."""
        limits = self._settings.cache
        evict(self._cache_root, limits.max_bytes, limits.max_unused_days, keep)

    async def _measure_shares(self) -> None:
        """Count the non-null values of each column after Load and keep them in the cache.

        The task runs in the summary pool, under its lock, since a new task
        in a pool kills the running one.
        """
        names = [c["name"] for c in self._schema]
        paths = [str(f) for f in self.files]
        async with self._summary_lock:
            end = await self._broker.run(NonnullTask(paths, names), "summary")
        if end.type != "done":
            self.shares_state = "failed"
            end.discard()
            return
        manifest = end.take()
        nonnull = {k: manifest[k] for k in ("counts", "rows")}
        _write_json(self.cache.dir / NONNULL, nonnull)
        self.nonnull = nonnull
        self.shares_state = "done"

    async def convert(self, columns: list[str], pool: Pool = "plot") -> None:
        """Convert the parts of columns not in the cache yet.

        Parameters
        ----------
        columns : list of str
            Columns a task is about to read; they stay in the cache.
        pool : str
            Pool to run the conversion in. Plots are refused while the plot
            pool converts, since the page shows its progress and takes no
            edits meanwhile.
        """
        plot = pool == "plot"
        if plot:
            self.converting = True
        try:
            async with self._convert_lock:
                missing = await asyncio.to_thread(self.missing, columns)
                if missing:
                    await self._convert(missing, pool)
        finally:
            if plot:
                self.converting = False
        keep = [Path(p) for c in dict.fromkeys(columns) for p in self.parts(c)]
        await asyncio.to_thread(self.evict, keep)

    async def _convert(self, missing: dict[str, list[int]], pool: Pool) -> None:
        """Run the conversion of the missing parts, one source file after another."""
        by_file: dict[int, dict[str, str]] = {}
        for column, positions in missing.items():
            parts = self.parts(column)
            for i in positions:
                by_file.setdefault(i, {})[column] = parts[i]
        order = sorted(by_file)
        task = ConvertTask(
            str(self.cache.dir / SCHEMA),
            {c: self._dtypes[c] for c in missing},
            [str(self.files[i]) for i in order],
            [by_file[i] for i in order],
        )
        end = await self._broker.run(task, pool)
        end.discard()
        if end.type != "done":
            raise HTTPException(500, end.error)

    async def filters(self, raw: list[dict]) -> list[Filter]:
        """Return the checked conditions of the local filter of a request.

        Parameters
        ----------
        raw : list of dict
            The conditions as the page sent them.

        Returns
        -------
        list of Filter
            The conditions (`ddviz.server.plan.parse_filters`).
        """
        try:
            return parse_filters(raw, await self.numeric())
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    async def summary(self, column: str) -> dict:
        """Return what the filter pane shows of a column, over every row.

        A column not converted yet is converted first, in the summary pool:
        reading a folder's source files one after another with a scan each
        went past 5.9GB at 100 files.

        Parameters
        ----------
        column : str
            The column.

        Returns
        -------
        dict
            The summary (`ddviz.compute.summary`).
        """
        if column not in await self.numeric():
            raise HTTPException(400, f"unknown column: {column}")
        async with self._summary_lock:
            if column not in self._summaries:
                await self.convert([column], "summary")
                end = await self._broker.run(
                    SummaryTask(self.parts(column), column), "summary"
                )
                ensure_done(end)
                self._summaries[column] = end.take()
        return self._summaries[column]


def _write_json(path: Path, value: object) -> None:
    """Write JSON under a temporary name, then rename it."""
    partial = path.with_suffix(".json.tmp")
    partial.write_text(json.dumps(value), encoding="utf-8")
    partial.replace(path)
