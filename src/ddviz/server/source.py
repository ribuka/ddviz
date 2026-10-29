"""The Parquet file the server plots: its schema, column cache and per-column facts.

The schema is read on the first request (Load). Columns a plot uses for the
first time are converted into the column cache before the plot task, and
the plot reads them from there. The share of non-null values of each column
is measured once after Load and kept in the cache; the filter pane's
summary of a column is computed once per column.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import HTTPException

from ddviz.server.broker import TaskBroker
from ddviz.server.errors import ensure_done
from ddviz.server.plan import parse_filters
from ddviz.server.settings import Settings
from ddviz.shared.cache import ColumnCache, evict
from ddviz.shared.scatter import Filter
from ddviz.shared.tasks import ConvertTask, NonnullTask, SchemaTask, SummaryTask

# File in the column cache's directory of a source holding the share of
# non-null values of each column, so that a later Load needs no task; the
# cache discards it with the columns when the source changes.
NONNULL = "nonnull.json"


class Source:
    """The Parquet file of the server and what is known of its columns.

    Parameters
    ----------
    path : str
        Parquet file to plot.
    cache_root : pathlib.Path
        Directory of the column cache; kept across runs.
    settings : Settings
        Limits of the column cache.
    broker : TaskBroker
        Runs the tasks that read the file.
    """

    def __init__(
        self, path: str, cache_root: Path, settings: Settings, broker: TaskBroker
    ) -> None:
        self.path = path
        self._cache_root = cache_root
        self._settings = settings
        self._broker = broker
        self._schema: list[dict] | None = None
        self.cache: ColumnCache | None = None
        # Share of non-null values per column (`ddviz.compute.nonnull`),
        # measured after Load; "pending" until then, "failed" when the task
        # failed.
        self.shares: list | None = None
        self.shares_state = "pending"
        self._shares_task: asyncio.Task | None = None
        # True while a conversion runs; plots are refused meanwhile.
        self.converting = False
        # The filter pane's summary of each column (`ddviz.compute.summary`).
        self._summaries: dict[str, dict] = {}
        # One summary pool task at a time: a new task kills the running one.
        self._summary_lock = asyncio.Lock()

    async def schema(self) -> list[dict]:
        """Return the columns of the file, reading them on the first call.

        Returns
        -------
        list of dict
            ``{"name", "dtype", "numeric"}`` of each column in file order.
        """
        if self._schema is None:
            end = await self._broker.run(SchemaTask(self.path))
            if end.type != "done":
                raise HTTPException(500, end.error)
            columns = end.take()["columns"]
            self.cache = await asyncio.to_thread(
                ColumnCache,
                self._cache_root,
                Path(self.path),
                [c["name"] for c in columns],
            )
            await asyncio.to_thread(self.evict, [])
            self._schema = columns
            stored = self.cache.dir / NONNULL
            if stored.exists():
                self.shares = json.loads(stored.read_text(encoding="utf-8"))
                self.shares_state = "done"
            else:
                self._shares_task = asyncio.create_task(self._measure_shares())
        return self._schema

    async def numeric(self) -> dict[str, bool]:
        """Return whether each column is numeric."""
        return {c["name"]: c["numeric"] for c in await self.schema()}

    def file(self, column: str) -> str:
        """Return the column's file in the cache."""
        return str(self.cache.file(column))

    def evict(self, keep: list[Path]) -> None:
        """Remove old column files, keeping the given ones."""
        limits = self._settings.cache
        evict(self._cache_root, limits.max_bytes, limits.max_unused_days, keep)

    async def _measure_shares(self) -> None:
        """Measure the share of non-null values of each column after Load and keep it in the cache.

        The task runs in the summary pool, under its lock, since a new task
        in a pool kills the running one.
        """
        names = [c["name"] for c in self._schema]
        async with self._summary_lock:
            end = await self._broker.run(NonnullTask(self.path, names), "summary")
        if end.type != "done":
            self.shares_state = "failed"
            end.discard()
            return
        shares = end.take()["shares"]
        stored = self.cache.dir / NONNULL
        partial = stored.with_suffix(".json.tmp")
        partial.write_text(json.dumps(shares), encoding="utf-8")
        partial.replace(stored)
        self.shares = shares
        self.shares_state = "done"

    async def convert(self, columns: list[str]) -> None:
        """Convert the columns not in the cache yet; plots are refused meanwhile.

        Parameters
        ----------
        columns : list of str
            Columns a task is about to read; they stay in the cache.
        """
        missing = self.cache.missing(columns)
        if not missing:
            return
        self.converting = True
        try:
            end = await self._broker.run(
                ConvertTask(self.path, {c: self.file(c) for c in missing})
            )
        finally:
            self.converting = False
        end.discard()
        if end.type != "done":
            raise HTTPException(500, end.error)
        await asyncio.to_thread(self.evict, [self.cache.file(c) for c in columns])

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
                # A column not converted yet is read from the source:
                # converting it here could race the plot's conversion of the
                # same column.
                missing = await asyncio.to_thread(self.cache.missing, [column])
                file = self.path if missing else self.file(column)
                end = await self._broker.run(SummaryTask(file, column), "summary")
                ensure_done(end)
                self._summaries[column] = end.take()
        return self._summaries[column]
