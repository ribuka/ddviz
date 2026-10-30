"""Non-null values per column, from the statistics in the Parquet footer.

No data is read: each column chunk's statistics hold its null count. polars
has no API for them (a null count over a column reads all its data), so the
footer is read with pyarrow. A column without a null count in every chunk,
or a nested one, gets no count.
"""

from __future__ import annotations

import gc

import pyarrow.parquet as pq


def nonnull_counts(paths: list[str], names: list[str]) -> tuple[list[int | None], int]:
    """Return the non-null values of each column over files read as one table.

    The footers are read one after another, so that only one is in memory.

    Parameters
    ----------
    paths : list of str
        Parquet files. A file without a column counts as nulls in it.
    names : list of str
        Column names, in the order of the result.

    Returns
    -------
    counts : list of int or None
        Per name, the rows with a value; None for a column some chunk of
        which has no null count, a nested column, or files without rows.
    rows : int
        The rows of all files.
    """
    values: dict[str, int | None] = dict.fromkeys(names, 0)
    rows = 0
    for path in paths:
        metadata = pq.read_metadata(path)
        schema = metadata.schema
        # A flat column has one leaf whose path is its name; leaves of nested
        # columns have longer paths.
        leaves = {
            schema.column(j).path: j
            for j in range(metadata.num_columns)
            if schema.column(j).path == schema.column(j).name
        }
        # The top names of all leaves: a column of the file with no flat
        # leaf is nested.
        tops = {
            schema.column(j).path.split(".")[0] for j in range(metadata.num_columns)
        }
        nulls: dict[int, int | None] = dict.fromkeys(leaves.values(), 0)
        for i in range(metadata.num_row_groups):
            group = metadata.row_group(i)
            for j, count in nulls.items():
                if count is None:
                    continue
                statistics = group.column(j).statistics
                if statistics is None or not statistics.has_null_count:
                    nulls[j] = None
                else:
                    nulls[j] = count + statistics.null_count
        for name, value in values.items():
            if value is None:
                continue
            if name in leaves:
                count = nulls[leaves[name]]
                values[name] = (
                    None if count is None else value + metadata.num_rows - count
                )
            elif name in tops:
                values[name] = None
        rows += metadata.num_rows
        # The schema refers back to the footer in a cycle, which keeps each
        # footer until the cyclic collector runs: without this, 10 files of
        # 100k column chunks peaked at 939MiB, against 180MiB for one.
        del metadata, schema
        gc.collect()
    return [None if rows == 0 else value for value in values.values()], rows
