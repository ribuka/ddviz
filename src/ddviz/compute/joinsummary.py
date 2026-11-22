"""The summary of a join by keys before it is made (the dry run): the rows of both tables it matches, and the sets of keys that match none.

The join task's map (`ddviz.compute.join.run_join`) tells which rows of the
input match (a null map matches none) and, through the rows it holds, which
rows of the joined table some row of the input matches
(`ddviz.compute.join.write_matched`). The rows of either side that match
none are counted by their set of key values, each side in its own types: a
set with a null matches no row, as in the join. The counts are made in
memory (`polars.LazyFrame.group_by`) when both tables have up to
`ONE_BUCKET_ROWS` rows, and otherwise in `BUCKETS` pieces split on disk by
the hash of the keys (`ddviz.compute.join.hash_pieces`), as the check of
duplicate keys does: a set lies in one piece only, so the first sets of all
are among the first of each piece.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ddviz.compute.join import (
    BUCKETS,
    MATCHED,
    ONE_BUCKET_ROWS,
    hash_pieces,
    write_matched,
)
from ddviz.compute.progress import Emit
from ddviz.compute.scan import scan_columns
from ddviz.shared.joined import MAP_COLUMN
from ddviz.shared.manifest import write_manifest
from ddviz.shared.tasks import JoinSummaryTask

# The most sets of keys matching no row the summary lists, per side.
UNMATCHED_EXAMPLES = 20
# The rows of a set, the map and whether a row matched, named apart from the
# keys, which take the names ``k0``, ``k1``, ...
_COUNT = "__ddviz_count"
_MAP = "__ddviz_map"
_MATCHED = "__ddviz_matched"


def _key(i: int) -> str:
    """Return the name of the `i`-th key while the sets are counted."""
    return f"k{i}"


def _first(found: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """Return the first `UNMATCHED_EXAMPLES` sets of `found`: the most rows first, then the values in ascending order, nulls last."""
    return found.sort(
        [_COUNT, *keys], descending=[True] + [False] * len(keys), nulls_last=True
    ).head(UNMATCHED_EXAMPLES)


def _counted(frame: pl.LazyFrame, keys: list[str]) -> pl.DataFrame:
    """Return the sets of `keys` of the rows of `frame`, with their rows (`_COUNT`)."""
    return frame.group_by(keys).agg(pl.len().alias(_COUNT)).collect()


def unmatched_keys(frame: pl.LazyFrame, keys: list[str], buckets: int, work: Path) -> dict:
    """Return how many sets of key values the rows of `frame` hold, and the first of them.

    Parameters
    ----------
    frame : polars.LazyFrame
        The rows that match none, with their keys.
    keys : list of str
        The keys, in the order of the pairs.
    buckets : int
        The pieces the sets are counted in (`ddviz.compute.join.hash_pieces`).
    work : pathlib.Path
        Directory for the pieces, removed before returning; unused with one
        bucket.

    Returns
    -------
    dict
        ``{"sets", "top"}``: the sets, and the first `UNMATCHED_EXAMPLES`
        of them (`_first`), each ``{"values", "rows"}``, its values as
        texts in the order of the keys (null as None) and its rows.
    """
    frame = frame.select(keys)
    if buckets == 1:
        found = _counted(frame, keys)
        sets, top = found.height, _first(found, keys)
    else:
        sets, firsts = 0, []
        with hash_pieces(frame, keys, buckets, work) as pieces:
            for files in pieces:
                found = _counted(pl.scan_parquet(files), keys)
                sets += found.height
                firsts.append(_first(found, keys))
        top = _first(pl.concat(firsts), keys) if firsts else _counted(frame.head(0), keys)
    texts = top.select(*(pl.col(k).cast(pl.String, strict=False) for k in keys), _COUNT)
    return {
        "sets": sets,
        "top": [{"values": list(row[:-1]), "rows": row[-1]} for row in texts.rows()],
    }


def run_join_summary(task: JoinSummaryTask, out: Path, emit: Emit) -> None:
    """Count the rows of both tables the join matches, and the sets of keys of those that match none.

    Parameters
    ----------
    task : JoinSummaryTask
        The keys, their parts and the parts of the map.
    out : pathlib.Path
        Directory to write the result into: the manifest, with
        ``right_matched``, the rows of the joined table some row of the
        input matches, and ``left_unmatched`` and ``right_unmatched``, the
        sets of keys of the rows of each table that match none
        (`unmatched_keys`).
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "join_summary"})
    buckets = 1 if max(task.left_rows, task.right_rows) <= ONE_BUCKET_ROWS else BUCKETS
    names = [_key(i) for i in range(len(task.keys))]
    left = pl.concat(
        [
            scan_columns({k["left"]: task.left[k["left"]] for k in task.keys}, None, False).select(
                pl.col(k["left"]).alias(n) for k, n in zip(task.keys, names, strict=True)
            ),
            scan_columns({MAP_COLUMN: task.maps}, None, False).select(pl.col(MAP_COLUMN).alias(_MAP)),
        ],
        how="horizontal",
    ).filter(pl.col(_MAP).is_null())
    left_unmatched = unmatched_keys(left, names, buckets, out / "left")
    matched = out / "matched.parquet"
    right_matched = write_matched(task.maps, task.right_rows, matched)
    right = pl.concat(
        [
            scan_columns({k["right"]: task.right[k["right"]] for k in task.keys}, None, False).select(
                pl.col(k["right"]).alias(n) for k, n in zip(task.keys, names, strict=True)
            ),
            pl.scan_parquet(matched).select(pl.col(MATCHED).alias(_MATCHED)),
        ],
        how="horizontal",
    ).filter(~pl.col(_MATCHED))
    right_unmatched = unmatched_keys(right, names, buckets, out / "right")
    matched.unlink()
    write_manifest(
        out,
        {
            "kind": "join_summary",
            "right_matched": right_matched,
            "left_unmatched": left_unmatched,
            "right_unmatched": right_unmatched,
        },
    )
