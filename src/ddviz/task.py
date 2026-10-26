"""Tasks a worker runs; each writes its result files and a manifest into its directory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np
import polars as pl

from ddviz.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.manifest import write_manifest
from ddviz.palette import series_color
from ddviz.png import encode_mask
from ddviz.raster import masks, occupancy
from ddviz.spec import PlotSpec

Emit = Callable[[dict], None]


def _column_array(series: pl.Series) -> tuple[np.ndarray, list | None]:
    """Return a hover column as a numpy array, with labels for codes of a non-numeric column."""
    if series.dtype.is_numeric():
        if series.dtype.is_integer() and series.null_count() == 0:
            return series.cast(pl.Int64).to_numpy(), None
        return series.cast(pl.Float64).fill_null(np.nan).to_numpy(), None
    text = series.cast(pl.String)
    labels = text.drop_nulls().unique().sort()
    codes = text.replace_strict(
        labels, list(range(len(labels))), default=-1, return_dtype=pl.Int32
    )
    return codes.to_numpy(), labels.to_list()


def run_schema(path: str, out: Path, emit: Emit) -> None:
    """Write the column names and types of a Parquet file.

    Parameters
    ----------
    path : str
        Parquet file.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    schema = pl.scan_parquet(path).collect_schema()
    columns = [
        {"name": name, "dtype": str(dtype), "numeric": dtype.is_numeric()}
        for name, dtype in schema.items()
    ]
    write_manifest(out, {"kind": "schema", "columns": columns})


def run_plot(spec: PlotSpec, out: Path, emit: Emit) -> None:
    """Aggregate a scatter plot and write its series images and hover files.

    Parameters
    ----------
    spec : PlotSpec
        What to plot.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    agg = aggregate(spec, lambda stage: emit({"type": "progress", "stage": stage}))
    emit({"type": "progress", "stage": "write"})
    bins = agg.bins
    keys = bins[KEY].to_numpy()
    np.save(out / "keys.npy", keys)
    np.save(out / "count.npy", bins[COUNT].cast(pl.UInt32).to_numpy())
    np.save(out / "index.npy", bins[INDEX].cast(pl.Int64).to_numpy())
    columns = []
    for i, name in enumerate(dict.fromkeys(spec.hover)):
        array, labels = _column_array(bins[name])
        np.save(out / f"col{i}.npy", array)
        columns.append({"name": name, "file": f"col{i}.npy", "labels": labels})

    emit({"type": "progress", "stage": "raster"})
    bin_masks = masks(keys, agg.grid)
    np.save(out / "occupancy.npy", occupancy(bin_masks))
    colors = [series_color(spec.colors, s) for s in range(agg.grid.n_series)]
    images: list[list[str | None]] = []
    for p in range(agg.grid.n_panels):
        row = []
        for s in range(agg.grid.n_series):
            mask = bin_masks[p, s]
            if not mask.any():
                row.append(None)
                continue
            name = f"p{p}s{s}.png"
            # Row 0 is the bottom bin: plotly's image trace puts the image's
            # first row at y0 on an increasing y axis.
            (out / name).write_bytes(encode_mask(mask, colors[s]))
            row.append(name)
        images.append(row)

    write_manifest(
        out,
        {
            "kind": "plot",
            "spec": spec.to_dict(),
            "grid": asdict(agg.grid),
            "layout": asdict(agg.layout),
            "x_range": agg.x_range,
            "y_range": agg.y_range,
            "levels": agg.levels,
            "colors": colors,
            "columns": columns,
            "images": images,
            "rows": int(bins[COUNT].sum()),
        },
    )


def run_task(task: dict, emit: Emit) -> None:
    """Run a task described by the UI server.

    Parameters
    ----------
    task : dict
        ``{"kind": "schema" | "plot", "out": directory, ...}``; ``"path"`` for
        a schema task and ``"spec"`` for a plot task.
    emit : callable
        Receives progress messages.

    Raises
    ------
    ValueError
        For an unknown kind.
    """
    out = Path(task["out"])
    out.mkdir(parents=True, exist_ok=True)
    if task["kind"] == "schema":
        run_schema(task["path"], out, emit)
    elif task["kind"] == "plot":
        run_plot(PlotSpec.from_dict(task["spec"]), out, emit)
    else:
        raise ValueError(f"unknown task kind: {task['kind']}")
