"""The input the server plots, a Parquet file, a folder of them or several files: its schema, column cache and per-column facts.

The schema is read on the first request (Load) and kept in the column cache
until a source file is added, removed or changed. The files of a folder are
read one after another as one table, and so are several files
(`ddviz.shared.inputs`). Columns a plot
uses for the first time are converted into the column cache before the plot
task, and the plot reads them from there. The share of non-null values of
each column is measured once after Load and kept in the cache; the filter
pane's summary of a column is computed once per column, and so is the index
of a column's levels that a filter card searches. Another table can be
joined to the input once (`join`); its columns then come after the input's
and are used as any column (`ddviz.server.join`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from ddviz.server.broker import Pool, TaskBroker
from ddviz.server.errors import ensure_done
from ddviz.server.join import Join, check_keys, check_rows
from ddviz.server.plan import parse_filters
from ddviz.server.settings import CacheSettings
from ddviz.shared.cache import SCHEMA, ColumnCache, evict
from ddviz.shared.generated import part_key
from ddviz.shared.inputs import parquet_files, unique
from ddviz.shared.joined import (
    MAP_COLUMN,
    join_id,
    joined_names,
    joined_part_key,
    map_part_key,
)
from ddviz.shared.scatter import Filter
from ddviz.shared.tasks import (
    ConvertTask,
    JoinConvertTask,
    JoinedFiles,
    JoinTask,
    LevelIndexTask,
    LevelSearchTask,
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
# The non-null values of each part a join wrote (`Source.join`), in a file
# per join (`ddviz.shared.joined.join_id`).
JOINED_NONNULL = "joined-{}.json"
# Orders of a filter card's levels (`ddviz.compute.levelindex.ORDERS`).
LEVEL_ORDERS = ("name", "count")


class Source:
    """The input of the server and what is known of its columns.

    Parameters
    ----------
    paths : list of str
        Absolute paths of the input: a Parquet file, a folder of Parquet
        files, or several Parquet files read one after another as one table.
    recursive : bool
        For a folder, also read the files in its subfolders.
    cache_root : pathlib.Path
        Directory of the column cache; kept across runs.
    index_dir : pathlib.Path
        Directory of the indexes of the levels a filter card searches, under
        the run's directory, which the server removes when it stops.
    cache_limits : callable
        Returns the limits of the column cache in effect, which each cleaning
        of the cache reads when it starts.
    broker : TaskBroker
        Runs the tasks that read the files.
    """

    def __init__(
        self,
        paths: list[str],
        recursive: bool,
        cache_root: Path,
        index_dir: Path,
        cache_limits: Callable[[], CacheSettings],
        broker: TaskBroker,
    ) -> None:
        self.paths = [str(p) for p in unique([Path(p) for p in paths])]
        self.recursive = recursive
        self._cache_root = cache_root
        self._index_dir = index_dir
        self._cache_limits = cache_limits
        self._broker = broker
        self._schema: list[dict] | None = None
        self.files: list[Path] = []
        # Rows of each source file.
        self.rows: list[int] = []
        # Columns whose type differs between the files, with the common type
        # they are read as (`ddviz.compute.tasks.columns.run_schema`).
        self.casts: list[dict] = []
        self._dtypes: dict[str, str] = {}
        # The columns added to an input of several files, with their kinds
        # (`ddviz.shared.generated`).
        self._generated: dict[str, str] = {}
        self.cache: ColumnCache | None = None
        # Non-null values per column and the rows, ``{"counts", "rows"}``
        # (`ddviz.compute.nonnull`), measured after Load; "pending" until
        # then, "failed" when the task failed.
        self.nonnull: dict | None = None
        self.shares_state = "pending"
        self._shares_task: asyncio.Task | None = None
        # True while the plot pool converts missing parts; plots are refused meanwhile.
        self.converting = False
        # One conversion at a time: the filter pane's and a plot's could
        # write the same parts.
        self._convert_lock = asyncio.Lock()
        # The filter pane's summary of each column (`ddviz.compute.summary`).
        self._summaries: dict[str, dict] = {}
        # One summary pool task at a time: a new task kills the running one.
        self._summary_lock = asyncio.Lock()
        # The index of each column's levels a filter card searched: its path,
        # or None for a column with too many levels, with its levels
        # (`ddviz.compute.levelindex.build_index`).
        self._indexes: dict[str, dict] = {}
        # One levels pool task at a time, as for the summary pool.
        self._levels_lock = asyncio.Lock()
        # The table to join, once read (`load_join_source`), and the join
        # once made (`join`).
        self.join_source: Source | None = None
        self.joined: Join | None = None

    async def schema(self) -> list[dict]:
        """Return the columns of the input, reading them on the first call.

        Returns
        -------
        list of dict
            ``{"name", "dtype", "numeric", "temporal", "joined"}`` of each
            column, in the order the columns first appear in the files
            (`ddviz.compute.tasks.columns.run_schema`), then the columns a
            join added (``"joined"`` true).
        """
        if self._schema is None:
            paths = [Path(p) for p in self.paths]
            try:
                files = await asyncio.to_thread(parquet_files, paths, self.recursive)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            if not files:
                raise HTTPException(
                    400, f"Parquet ファイルがありません：{self.paths[0]}"
                )
            self.cache = await asyncio.to_thread(
                ColumnCache, self._cache_root, paths, files
            )
            self.files = files
            stored = self.cache.dir / SCHEMA_JSON
            found = None
            if stored.exists():
                found = json.loads(stored.read_text(encoding="utf-8"))
            # A schema stored before columns had their temporal kind, or
            # before several files had added columns, is read again, and the
            # non-null counts made with it are measured again.
            if (
                found is None
                or "generated" not in found
                or any("temporal" not in c for c in found["columns"])
            ):
                (self.cache.dir / NONNULL).unlink(missing_ok=True)
                found = await self._read_schema()
            self.rows = found["rows"]
            self.casts = found["casts"]
            self._generated = found["generated"]
            self._dtypes = {c["name"]: c["dtype"] for c in found["columns"]}
            await asyncio.to_thread(self.evict, [])
            self._schema = [{**c, "joined": False} for c in found["columns"]]
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
        found = {k: manifest[k] for k in ("columns", "rows", "casts", "generated")}
        _write_json(self.cache.dir / SCHEMA_JSON, found)
        return found

    async def numeric(self) -> dict[str, bool]:
        """Return whether each column is numeric."""
        return {c["name"]: c["numeric"] for c in await self.schema()}

    async def temporal(self) -> dict[str, str]:
        """Return the kind of each temporal column (`ddviz.shared.temporal.KINDS`)."""
        return {c["name"]: c["temporal"] for c in await self.schema() if c["temporal"]}

    def _key(self, column: str) -> str:
        """Return what names the column's parts besides its name (`ddviz.shared.generated.part_key`, `ddviz.shared.joined.joined_part_key`)."""
        if self.joined is not None and column in self.joined.names:
            held = self.joined.names[column]
            return joined_part_key(self._dtypes[column], self.joined.id, held)
        return part_key(self._dtypes[column], self._generated.get(column), self.paths)

    def parts(self, column: str) -> list[str]:
        """Return the column's parts in the cache, one per source file."""
        return [str(p) for p in self.cache.parts(column, self._key(column))]

    def source_files(self, columns: list[str]) -> SourceFiles:
        """Return the source files, for reading columns not in the cache.

        Parameters
        ----------
        columns : list of str
            The columns to read.

        Returns
        -------
        SourceFiles
            The files, their rows and the types of the columns; for columns
            a join added, where the joined table's values are.
        """
        added = self.joined.names if self.joined is not None else {}
        plain = [c for c in columns if c not in added]
        joined = None
        held = {c: added[c] for c in columns if c in added}
        if held:
            right = self.joined.right
            read = [h for h in held.values() if h is not None]
            missing = right.missing(read)
            joined = JoinedFiles(
                held,
                self.joined.maps,
                {h: right.parts(h) for h in read if h not in missing},
                right.source_files([h for h in read if h in missing]),
            )
        return SourceFiles(
            [str(f) for f in self.files],
            self.rows,
            str(self.cache.dir / SCHEMA),
            {c: self._dtypes[c] for c in plain},
            {c: self._generated[c] for c in plain if c in self._generated},
            joined,
        )

    def missing(self, columns: list[str]) -> dict[str, list[int]]:
        """Return the columns with parts not converted yet (`ColumnCache.missing`)."""
        return self.cache.missing({c: self._key(c) for c in dict.fromkeys(columns)})

    def touch(self, columns: list[str]) -> None:
        """Mark columns whose parts exist as used now."""
        self.cache.touch({c: self._key(c) for c in dict.fromkeys(columns)})

    def evict(self, keep: list[Path]) -> None:
        """Remove old column parts, keeping the given ones and the map and ``_joined`` of the join."""
        if self.joined is not None:
            keep = [*keep, *self._join_parts()]
        limits = self._cache_limits()
        evict(self._cache_root, limits.max_bytes, limits.max_unused_days, keep)

    def _join_parts(self) -> list[Path]:
        """Return the parts the join task writes: the map and ``_joined``."""
        found = [Path(p) for p in self.joined.maps]
        for column, held in self.joined.names.items():
            if held is None:
                found += [Path(p) for p in self.parts(column)]
        return found

    async def _measure_shares(self) -> None:
        """Count the non-null values of each column after Load and keep them in the cache.

        The task runs in the summary pool, under its lock, since a new task
        in a pool kills the running one.
        """
        names = [c["name"] for c in self._schema if not c["joined"]]
        paths = [str(f) for f in self.files]
        async with self._summary_lock:
            task = NonnullTask(paths, names, list(self._generated))
            end = await self._broker.run(task, "summary")
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
            Pool to run the conversion in. While the plot pool converts
            parts that were missing, plots are refused, since the page shows
            its progress and takes no edits meanwhile. Checking for missing
            parts refuses nothing: a request let through meanwhile waits for
            the same lock before it sends a task to the plot pool, so it
            kills no conversion.
        """
        async with self._convert_lock:
            missing = await asyncio.to_thread(self.missing, columns)
            if missing:
                plot = pool == "plot"
                if plot:
                    self.converting = True
                try:
                    await self._convert(missing, pool)
                finally:
                    if plot:
                        self.converting = False
        keep = [Path(p) for c in dict.fromkeys(columns) for p in self.parts(c)]
        await asyncio.to_thread(self.evict, keep)

    async def _convert(self, missing: dict[str, list[int]], pool: Pool) -> None:
        """Run the conversion of the missing parts, one source file after another.

        Columns a join added are converted apart (`_convert_joined`).
        """
        added = self.joined.names if self.joined is not None else {}
        joined = {c: p for c, p in missing.items() if c in added}
        missing = {c: p for c, p in missing.items() if c not in added}
        if missing:
            await self._convert_files(missing, pool)
        if joined:
            await self._convert_joined(joined, pool)

    async def _convert_files(self, missing: dict[str, list[int]], pool: Pool) -> None:
        """Convert the missing parts of columns of the source files."""
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
            {c: self._generated[c] for c in missing if c in self._generated},
        )
        end = await self._broker.run(task, pool)
        end.discard()
        if end.type != "done":
            raise HTTPException(500, end.error)

    async def _convert_joined(self, missing: dict[str, list[int]], pool: Pool) -> None:
        """Convert the missing parts of columns a join added.

        ``_joined`` and the map are written by the join task, run again
        when a part of them is gone. The joined table's columns are
        converted into its column cache first; the parts are made from
        them, and their non-null values are kept (`_keep_nonnull`).
        """
        join = self.joined
        if join.task is not None and (
            any(join.names[c] is None for c in missing)
            or not all(Path(p).exists() for p in join.maps)
        ):
            end = await self._broker.run(join.task, pool)
            ensure_done(end)
            end.discard()
        columns = {c: h for c in missing if (h := join.names[c]) is not None}
        if not columns:
            return
        right = join.right
        held = list(dict.fromkeys(columns.values()))
        gaps = await asyncio.to_thread(right.missing, held)
        if gaps:
            await right._convert(gaps, pool)
        by_file: dict[int, dict[str, str]] = {}
        for column in columns:
            parts = self.parts(column)
            for i in missing[column]:
                by_file.setdefault(i, {})[column] = parts[i]
        order = sorted(by_file)
        task = JoinConvertTask(
            columns,
            {h: right.parts(h) for h in held},
            self.rows,
            order,
            [join.maps[i] for i in order] if join.maps else [],
            [by_file[i] for i in order],
        )
        end = await self._broker.run(task, pool)
        ensure_done(end)
        found = end.take()["nonnull"]
        await asyncio.to_thread(self._keep_nonnull, found)

    def _keep_nonnull(self, found: dict[str, int]) -> None:
        """Keep the non-null values of parts a join wrote, and those of the columns all of whose parts are counted."""
        path = self.cache.dir / JOINED_NONNULL.format(self.joined.id)
        counts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        counts.update(found)
        _write_json(path, counts)
        self._count_joined(counts)

    def _count_joined(self, counts: dict[str, int]) -> None:
        """Set the exact non-null values of the added columns whose parts all exist and are counted."""
        for column, held in self.joined.names.items():
            if held is None or column in self.joined.exact:
                continue
            parts = self.parts(column)
            if all(p in counts and Path(p).exists() for p in parts):
                self.joined.exact[column] = sum(counts[p] for p in parts)

    def nonnull_counts(self) -> dict | None:
        """Return the non-null values per column and the rows (`ddviz.server.columns.search_columns`).

        Without a join, those counted after Load (`nonnull`). A column a
        join added has its exact count once converted; before, ``_joined``
        has a value in every row, a column joined by rows the count of the
        joined table, and a column joined by keys an estimate: the joined
        table's share times the rows matched. A count not known yet is None.
        """
        join = self.joined
        if join is None:
            return self.nonnull
        rows = sum(self.rows)
        left = len(self._schema) - len(join.names)
        counts = list(self.nonnull["counts"]) if self.nonnull else [None] * left
        right = join.right.nonnull
        position = {c["name"]: i for i, c in enumerate(join.right._schema)}
        for column, held in join.names.items():
            if column in join.exact:
                count = join.exact[column]
            elif held is None:
                count = rows
            elif right is None or right["counts"][position[held]] is None:
                count = None
            elif join.kind == "rows":
                count = right["counts"][position[held]]
            elif right["rows"] == 0:
                count = 0
            else:
                count = round(right["counts"][position[held]] / right["rows"] * join.matched)
            counts.append(count)
        return {"counts": counts, "rows": rows}

    async def load_join_source(self, paths: list[str], recursive: bool) -> dict:
        """Read the table to join, in place of one read before.

        Its columns are read as the input's are (`schema`), into the
        column cache of its own input, and their non-null values counted.

        Parameters
        ----------
        paths : list of str
            The table to join: a Parquet file, a folder or several files.
        recursive : bool
            For a folder, also read the files in its subfolders.

        Returns
        -------
        dict
            ``{"paths", "files", "rows", "columns", "casts"}``: its input,
            its files, its rows, the number of its columns and the columns
            cast to a common type.

        Raises
        ------
        fastapi.HTTPException
            409 ``already joined`` after a join; 400 as Load refuses an input.
        """
        await self.schema()
        if self.joined is not None:
            raise HTTPException(409, "already joined")
        right = Source(
            paths,
            recursive,
            self._cache_root,
            self._index_dir,
            self._cache_limits,
            self._broker,
        )
        # Its non-null count runs in the summary pool, where a new task
        # kills the running one.
        right._summary_lock = self._summary_lock
        columns = await right.schema()
        if self.joined is not None:
            raise HTTPException(409, "already joined")
        self.join_source = right
        return {
            "paths": right.paths,
            "files": len(right.files),
            "rows": sum(right.rows),
            "columns": len(columns),
            "casts": right.casts,
        }

    async def join(self, kind: str, keys: list[dict[str, str]]) -> dict:
        """Join the table read (`load_join_source`) to the input, once.

        A join by keys runs the join task in the plot pool (plots are
        refused meanwhile, as while converting), after converting the keys
        of both tables. Its columns then follow the input's
        (`ddviz.shared.joined.joined_names`). A refused join adds nothing,
        and the table read stays for another try.

        Parameters
        ----------
        kind : str
            ``"key"`` or ``"rows"``.
        keys : list of dict of str to str
            The pairs of keys, ``{"left", "right"}``; empty for ``"rows"``.

        Returns
        -------
        dict
            ``{"added", "rows", "matched"}``: the columns added, the rows of
            the input and those a row of the joined table matched.

        Raises
        ------
        fastapi.HTTPException
            409 ``no join source`` before a table is read, ``already joined``
            after a join; 400 for keys given wrong, tables of different rows,
            keys of no common type or duplicated in the joined table; 500
            when the task fails.
        """
        await self.schema()
        async with self._convert_lock:
            right = self.join_source
            if self.joined is not None:
                raise HTTPException(409, "already joined")
            if right is None:
                raise HTTPException(409, "no join source")
            check_keys(kind, keys, self._dtypes, right._dtypes)
            if kind == "rows":
                check_rows(sum(self.rows), sum(right.rows))
            taken = [k["right"] for k in keys]
            names = joined_names(
                self._dtypes,
                [
                    c["name"]
                    for c in right._schema
                    if c["name"] not in right._generated and c["name"] not in taken
                ],
                {c: k for c, k in right._generated.items() if c not in taken},
                kind == "key",
            )
            typed = [
                {**k, "left_dtype": self._dtypes[k["left"]], "right_dtype": right._dtypes[k["right"]]}
                for k in keys
            ]
            files = right.cache.identity["files"]
            rows = self.rows if kind == "rows" else []
            id_ = join_id(kind, right.cache.key, files, typed, rows)
            maps: list[str] = []
            task = None
            matched = sum(self.rows)
            if kind == "key":
                maps = [str(p) for p in self.cache.parts(MAP_COLUMN, map_part_key(id_))]
                indicator = next(iter(names))
                task = JoinTask(
                    keys,
                    {k["left"]: self.parts(k["left"]) for k in keys},
                    {k["right"]: right.parts(k["right"]) for k in keys},
                    self.rows,
                    sum(right.rows),
                    maps,
                    indicator,
                    [str(p) for p in self.cache.parts(indicator, joined_part_key("String", id_, None))],
                )
                self.converting = True
                try:
                    matched = await self._run_join(task, keys, right)
                finally:
                    self.converting = False
            join = Join(right, kind, keys, names, id_, matched, maps, task)
            self._add_join(join)
        return {"added": list(names), "rows": sum(self.rows), "matched": matched}

    async def _run_join(
        self, task: JoinTask, keys: list[dict[str, str]], right: Source
    ) -> int:
        """Convert the keys of both tables, run the join task and return the rows matched."""
        gaps = await asyncio.to_thread(self.missing, [k["left"] for k in keys])
        if gaps:
            await self._convert_files(gaps, "plot")
        gaps = await asyncio.to_thread(right.missing, [k["right"] for k in keys])
        if gaps:
            await right._convert(gaps, "plot")
        end = await self._broker.run(task, "plot")
        ensure_done(end)
        found = end.take()
        if "refused" in found:
            raise HTTPException(400, found["refused"])
        return found["matched"]

    def _add_join(self, join: Join) -> None:
        """Add the columns of a join after the input's, with the types they have in the joined table."""
        right = {c["name"]: c for c in join.right._schema}
        added = []
        for column, held in join.names.items():
            if held is None:
                found = {"dtype": "String", "numeric": False, "temporal": None}
            else:
                found = {k: right[held][k] for k in ("dtype", "numeric", "temporal")}
            added.append({"name": column, **found, "joined": True})
            self._dtypes[column] = found["dtype"]
        self.joined = join
        # A new list: the column search keeps the ranks of the last one
        # (`ddviz.server.columns`).
        self._schema = [*self._schema, *added]
        path = self.cache.dir / JOINED_NONNULL.format(join.id)
        if path.exists():
            self._count_joined(json.loads(path.read_text(encoding="utf-8")))

    def join_info(self) -> dict | None:
        """Return the join for ``GET /api/source``, or None without one."""
        join = self.joined
        if join is None:
            return None
        return {
            "paths": join.right.paths,
            "recursive": join.right.recursive,
            "kind": join.kind,
            "keys": join.keys,
            "rows": sum(self.rows),
            "matched": join.matched,
            "added": list(join.names),
        }

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

    async def filter_levels(self, column: str, query: str, order: str) -> dict:
        """Return the levels of a categorical column that match a search, for a filter card.

        The first search of a column converts it if needed and writes the
        index of its levels (`ddviz.compute.levelindex`); later searches read
        only the index. A column with too many levels is known as such
        from then on. A failed index is written again on the next search.

        Parameters
        ----------
        column : str
            A categorical column.
        query : str
            The search input; blank keeps every level.
        order : {"name", "count"}
            The order of the levels.

        Returns
        -------
        dict
            ``levels`` (``[value, count]`` pairs, at most 100; None for a
            column with too many levels), ``truncated`` and ``n_levels``.
        """
        numeric = await self.numeric()
        if column not in numeric:
            raise HTTPException(400, f"unknown column: {column}")
        if numeric[column]:
            raise HTTPException(400, f"not a categorical column: {column}")
        if order not in LEVEL_ORDERS:
            raise HTTPException(400, f"unknown order: {order}")
        async with self._levels_lock:
            index = self._indexes.get(column)
            if index is None:
                index = await self._build_index(column)
                self._indexes[column] = index
            if index["index"] is None:
                return {
                    "levels": None,
                    "truncated": False,
                    "n_levels": index["n_levels"],
                }
            end = await self._broker.run(
                LevelSearchTask(index["index"], query, order), "levels"
            )
            ensure_done(end)
            found = end.take()
        return {k: found[k] for k in ("levels", "truncated", "n_levels")}

    async def _build_index(self, column: str) -> dict:
        """Convert a column if needed and write the index of its levels, in the levels pool.

        The index is named by a hash of the column's parts, which tell its
        type, an added column's kind and the input's paths besides its name.
        """
        await self.convert([column], "levels")
        parts = self.parts(column)
        name = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]
        path = self._index_dir / f"{name}.parquet"
        await asyncio.to_thread(self._index_dir.mkdir, parents=True, exist_ok=True)
        end = await self._broker.run(LevelIndexTask(parts, column, str(path)), "levels")
        if end.type != "done":
            # A killed task may leave its file half written.
            path.with_name(path.name + ".partial").unlink(missing_ok=True)
        ensure_done(end)
        found = end.take()
        return {"index": found["index"], "n_levels": found["n_levels"]}


def _write_json(path: Path, value: object) -> None:
    """Write JSON under a temporary name, then rename it."""
    partial = path.with_suffix(".json.tmp")
    partial.write_text(json.dumps(value), encoding="utf-8")
    partial.replace(path)
