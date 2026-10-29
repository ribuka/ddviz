"""Share of non-null values per column, from the statistics in the Parquet footer.

No data is read: each column chunk's statistics hold its null count. polars
has no API for them (a null count over a column reads all its data), so the
footer is read with pyarrow. A column without a null count in every chunk,
or a nested one, gets no share.
"""

from __future__ import annotations

import pyarrow.parquet as pq


def nonnull_shares(path: str, names: list[str]) -> list[float | None]:
    """Return the share of non-null values of each column.

    Parameters
    ----------
    path : str
        Parquet file.
    names : list of str
        Column names, in the order of the result.

    Returns
    -------
    list of float or None
        Per name, the non-null values over the rows, from 0 to 1; None for a
        column some chunk of which has no null count, a nested column, or a
        file without rows.
    """
    metadata = pq.read_metadata(path)
    schema = metadata.schema
    # A flat column has one leaf whose path is its name; leaves of nested
    # columns have longer paths.
    leaves = {
        schema.column(j).path: j
        for j in range(metadata.num_columns)
        if schema.column(j).path == schema.column(j).name
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
    rows = metadata.num_rows
    shares: list[float | None] = []
    for name in names:
        count = nulls.get(leaves[name]) if name in leaves else None
        shares.append(None if count is None or rows == 0 else 1 - count / rows)
    return shares
