"""Task that writes the data of a drawn plot as a file to save: one row per bin of its result.

A result holds no points, only the pixel bins they fall in (`ddviz.shared.keys`)
with how many rows each holds; the table is those bins with what they are in
the figure's terms: the panel's axis columns, the facet, color and overlay
levels, the bin's range along each axis and its rows. A categorical axis
gives the bin's level too; its range is in the axis' positions, where level
``i`` is centered at ``i``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.progress import Emit
from ddviz.shared.manifest import PlotManifest, write_manifest
from ddviz.shared.missing import MISSING
from ddviz.shared.scatter import ONE_BAND

# The facet and series roles of a figure, as the table's columns name them
# after the drop zones; only the roles in use get a column.
_ROLES = (
    ("row", "group_y"),
    ("col", "group_x"),
    ("color", "color"),
    ("overlay", "overlay"),
)


def _values(at: np.ndarray, log: np.ndarray) -> np.ndarray:
    """Return the values at positions: the powers of 10 of those on a log axis (`log`)."""
    return np.where(log, np.power(10.0, at), at)


def _levels(levels: list, index: np.ndarray) -> pl.Series:
    """Return the text of each bin's level; null for the missing level (`ddviz.shared.missing.MISSING`)."""
    texts = [None if v == MISSING else str(v) for v in levels]
    return pl.Series(texts, dtype=pl.String).gather(index)


def _axis(
    name: str,
    columns: list[str],
    ranges: list[list[float]],
    axis_levels: dict[str, list[str]],
    which: np.ndarray,
    bins: np.ndarray,
    n: int,
    logs: list[str],
) -> dict[str, pl.Series]:
    """Return the columns of one axis: its data column, the bin's range and, with a categorical column, its level.

    The range of a bin of a column on a log axis (`logs`) is of the
    values: the powers of 10 of its positions.
    """
    log = np.array([c in logs for c in columns])[which]
    lo = np.array([r[0] for r in ranges])[which]
    step = (np.array([r[1] for r in ranges])[which] - lo) / n
    out = {
        f"{name}_column": pl.Series(
            [None if c == ONE_BAND else c for c in columns], dtype=pl.String
        ).gather(which),
        f"{name}_lo": pl.Series(_values(lo + bins * step, log)),
        f"{name}_hi": pl.Series(_values(lo + (bins + 1) * step, log)),
    }
    if any(c in axis_levels for c in columns):
        # The band of a level is centered at its index; null for a numeric column.
        texts = []
        center = np.rint(lo + (bins + 0.5) * step).astype(np.int64)
        for column, i in zip(
            np.array(columns, dtype=object)[which], center, strict=True
        ):
            levels = axis_levels.get(column)
            texts.append(
                None if levels is None else levels[min(max(i, 0), len(levels) - 1)]
            )
        out[f"{name}_level"] = pl.Series(texts, dtype=pl.String)
    return out


def bins_table(out: Path) -> pl.DataFrame:
    """Return the bins of a plot task's result as a table.

    The result must have its hover files (`PlotManifest.hover_files`), which
    hold the bins: those of the points, and those of the rows of the piles
    at their centers, counted in their series' bins as any row.


    Parameters
    ----------
    out : pathlib.Path
        The task's output directory.

    Returns
    -------
    polars.DataFrame
        One row per bin with rows: ``x_column``, ``x_lo``, ``x_hi`` (and
        ``x_level`` with a categorical x), the same for y, then ``group_y``,
        ``group_x`` (``wrap`` in a wrapped grid), ``color`` and ``overlay``
        for the roles in use, and ``count``, the rows in the bin. A gradient's
        color has no levels, so no column.
    """
    manifest = PlotManifest.read(out)
    spec, grid, axes, levels = (
        manifest.spec,
        manifest.grid,
        manifest.axes,
        manifest.levels,
    )
    keys = np.load(out / "keys.npy")
    count = np.load(out / "count.npy").astype(np.int64)
    # The rows of the piles are rows of their series' bins at their centers,
    # drawn as piles instead of points (`ddviz.compute.stacks`).
    pile_keys = np.load(out / "pile_keys.npy")
    if len(pile_keys):
        keys, at = np.unique(np.concatenate([keys, pile_keys]), return_inverse=True)
        pile_count = np.load(out / "pile_count.npy").astype(np.int64)
        count = np.bincount(at, np.concatenate([count, pile_count])).astype(np.int64)
    panel, series, by, bx = grid.unpack(keys)
    # Panels count row by row (`ddviz.shared.layout.AxisGrid`).
    prow, pcol = np.divmod(panel, axes.cols)
    xi, yj = pcol % axes.nx, prow % axes.ny
    row, col = prow // axes.ny, pcol // axes.nx
    if axes.wrap:
        row, col = np.zeros_like(row), row * axes.ncol + col
    columns = {
        **_axis(
            "x",
            spec.x,
            manifest.x_ranges,
            manifest.axis_levels,
            xi,
            bx,
            grid.width,
            spec.log_x,
        ),
        **_axis(
            "y",
            spec.y,
            manifest.y_ranges,
            manifest.axis_levels,
            yj,
            by,
            grid.height,
            spec.log_y,
        ),
    }
    shapes = len(levels["overlay"])
    index = {
        "row": row,
        "col": col,
        "color": series // shapes,
        "overlay": series % shapes,
    }
    for role, name in _ROLES:
        if getattr(spec, role) is None or (role == "color" and spec.gradient):
            continue
        if role == "col" and spec.wrap:
            name = "wrap"
        columns[name] = _levels(levels[role], index[role])
    columns["count"] = pl.Series(count.astype(np.int64))
    return pl.DataFrame(columns)


def run_plot_data(result: Path, file_format: str, out: Path, emit: Emit) -> None:
    """Write the bins of a plot task's result (`bins_table`) as a file.

    Parameters
    ----------
    result : pathlib.Path
        The plot task's output directory.
    file_format : str
        ``"csv"`` (UTF-8 with a byte order mark, so that Excel reads it as
        UTF-8) or ``"parquet"``.
    out : pathlib.Path
        Directory to write the file into; the manifest names it.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "plot data"})
    table = bins_table(result)
    file = f"data.{file_format}"
    if file_format == "csv":
        table.write_csv(out / file, include_bom=True)
    else:
        table.write_parquet(out / file)
    write_manifest(out, {"kind": "plot_data", "file": file})
