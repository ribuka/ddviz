"""Tasks a worker runs; each writes its result files and a manifest into its directory."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np
import polars as pl

from ddviz.aggregate import (
    COUNT,
    INDEX,
    KEY,
    aggregate,
    selection_columns,
    selection_filter,
)
from ddviz.convert import convert_columns
from ddviz.manifest import IMAGES, write_manifest
from ddviz.palette import series_color
from ddviz.png import encode_mask
from ddviz.raster import atlas, masks, occupancy
from ddviz.scan import scan_columns
from ddviz.scatter import ScatterSpec

Emit = Callable[[dict], None]
# Rows of a table page further apart than this are read with separate
# slices; closer ones with one slice over the rows between them.
TABLE_GAP = 10_000


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


def _write_images(
    out: Path, bin_masks: np.ndarray, ncol: int, colors: list[str]
) -> list[list[int] | None]:
    """Write one PNG per series into the images file; return where each lies.

    One PNG per series holds all its panels as tiles: the page decodes 5
    images instead of 500 (about 45ms instead of 120ms for 10 x 10 panels).
    All PNGs go into one file: the first read of each freshly written file
    costs about 0.6ms on Windows (the virus scan, we assume).

    Parameters
    ----------
    out : pathlib.Path
        Directory of the task.
    bin_masks : numpy.ndarray
        Masks of the bins (`ddviz.raster.masks`).
    ncol : int
        Panels to a row of tiles.
    colors : list of str
        Color of each series.

    Returns
    -------
    list
        ``[offset, length]`` of each series' PNG in the file, or None for a
        series without bins.
    """
    images: list[list[int] | None] = []
    offset = 0
    with open(out / IMAGES, "wb") as file:
        for s, color in enumerate(colors):
            series_masks = bin_masks[:, s]
            if not series_masks.any():
                images.append(None)
                continue
            png = encode_mask(atlas(series_masks, ncol), color)
            file.write(png)
            images.append([offset, len(png)])
            offset += len(png)
    return images


def run_plot(spec: ScatterSpec, out: Path, emit: Emit) -> None:
    """Aggregate a scatter plot and write its series images and hover files.

    Parameters
    ----------
    spec : ScatterSpec
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
    images = _write_images(out, bin_masks, agg.layout.ncol, colors)

    write_manifest(
        out,
        {
            "kind": "plot",
            "spec": spec.to_dict(),
            "grid": asdict(agg.grid),
            "layout": asdict(agg.layout),
            "axes": asdict(agg.axes),
            "x_ranges": agg.x_ranges,
            "y_ranges": agg.y_ranges,
            "levels": agg.levels,
            "colors": colors,
            "columns": columns,
            "images": images,
            "rows": int(bins[COUNT].sum()),
        },
    )


def run_selection(spec: ScatterSpec, out: Path, emit: Emit) -> None:
    """Aggregate the selected rows of a drawn result and write their images.

    Parameters
    ----------
    spec : ScatterSpec
        The drawn result's spec with its view (levels and ranges) and a
        selection.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    agg = aggregate(
        spec,
        lambda stage: emit({"type": "progress", "stage": stage}),
        selection_only=True,
    )
    emit({"type": "progress", "stage": "raster"})
    bin_masks = masks(agg.selected[KEY].to_numpy(), agg.grid)
    colors = [series_color(spec.colors, s) for s in range(agg.grid.n_series)]
    images = _write_images(out, bin_masks, agg.layout.ncol, colors)
    write_manifest(
        out,
        {
            "kind": "selection",
            "selection": spec.to_dict()["selection"],
            "grid": asdict(agg.grid),
            "images": images,
            "rows": agg.selected_rows,
        },
    )


def _json_value(value: object) -> object:
    """Return a cell value that JSON can carry: NaN and infinities as text."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _spans(rows: list[int]) -> list[tuple[int, int]]:
    """Return slices (start, length) covering sorted rows, split where they are far apart."""
    spans: list[list[int]] = []
    for r in rows:
        if spans and r - spans[-1][1] <= TABLE_GAP:
            spans[-1][1] = r
        else:
            spans.append([r, r])
    return [(lo, hi - lo + 1) for lo, hi in spans]


def run_table(
    spec: ScatterSpec,
    offset: int,
    limit: int,
    files: dict[str, str],
    out: Path,
    emit: Emit,
) -> None:
    """Write a page of the selected rows: their indices and the values of some columns.

    Parameters
    ----------
    spec : ScatterSpec
        A spec with a selection; its files hold the selection's columns.
    offset, limit : int
        The page: the selected rows from `offset`, at most `limit`, in row
        order.
    files : dict of str to str
        Parquet file to read each column of the page from: a file of the
        column cache, or the source.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    emit({"type": "progress", "stage": "rows"})
    index = (
        scan_columns({c: spec.files[c] for c in selection_columns(spec)}, INDEX)
        .filter(*selection_filter(spec))
        .select(INDEX)
        .slice(offset, limit)
        .collect(engine="streaming")[INDEX]
        .to_list()
    )
    emit({"type": "progress", "stage": "values"})
    # One lazy frame for every slice: a new scan parses the footer again
    # (about 0.5s for a file of 1M column chunks). Slices are read one after
    # another; reading 100 rows spread over 100 row groups at once peaked at
    # 8.7GB on 7 columns of 100M rows.
    frame = scan_columns(files, INDEX) if files else None
    parts = []
    if frame is not None:
        for start, length in _spans(index):
            parts.append(frame.slice(start, length).collect())
    values = (
        pl.concat(parts).filter(pl.col(INDEX).is_in(index))
        if parts
        else pl.DataFrame({INDEX: index}, schema={INDEX: pl.UInt32})
    )
    columns = [
        {
            "name": name,
            "dtype": str(values.schema[name]),
            "values": [_json_value(v) for v in values[name].to_list()],
        }
        for name in files
    ]
    write_manifest(
        out,
        {
            "kind": "table",
            "offset": offset,
            "index": [int(i) for i in index],
            "columns": columns,
        },
    )


def run_task(task: dict, emit: Emit) -> None:
    """Run a task described by the UI server.

    Parameters
    ----------
    task : dict
        ``{"kind": "schema" | "convert" | "plot" | "selection" | "table",
        "out": directory, ...}``; ``"path"`` for a schema task, ``"path"``
        and ``"files"`` (the file to write for each column) for a convert
        task, ``"spec"`` for a plot or selection task, and ``"spec"``,
        ``"offset"``, ``"limit"`` and ``"files"`` (the file to read each
        column from) for a table task.
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
    elif task["kind"] == "convert":
        convert_columns(task["path"], task["files"], emit)
    elif task["kind"] == "plot":
        run_plot(ScatterSpec.from_dict(task["spec"]), out, emit)
    elif task["kind"] == "selection":
        run_selection(ScatterSpec.from_dict(task["spec"]), out, emit)
    elif task["kind"] == "table":
        run_table(
            ScatterSpec.from_dict(task["spec"]),
            task["offset"],
            task["limit"],
            task["files"],
            out,
            emit,
        )
    else:
        raise ValueError(f"unknown task kind: {task['kind']}")
