"""Routes that draw: a plot, its zoomed view, its overview at another size, and hovers.

The hover files of the open results (the overview and the view), and of
replaced ones a worker still reads (`Results.hold`), keep within
``max_hover_bytes`` together: a new result gets what the results
open while it is written leave, those it replaces included, as they go only
once it is open (`ddviz.compute.hoverfit`); its figure tells the page which
hover columns were left out.

Every plot, view and overview request carries the conditions of the local
filter (`ddviz.server.plan.parse_filters`); the result's spec keeps them, so
the selection and the table of a result follow its filter.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import asdict, replace

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ddviz.server.broker import TaskBroker
from ddviz.server.derive import resized_spec, unchanged
from ddviz.server.encoding import Encoding
from ddviz.server.errors import ensure_done
from ddviz.server.figure import build_figure
from ddviz.server.hover import HoverIndex
from ddviz.server.models import PlotRequest, SizeRequest, ViewRequest
from ddviz.server.plan import drawable, drawn_columns, scatter_spec, undrawn
from ddviz.server.plotoptions import (
    parse_color_bins,
    parse_level_shapes,
    parse_line_width,
    parse_shape_size,
    parse_shape_sizes,
    parse_smoothing,
    parse_wrap_cols,
)
from ddviz.server.results import Results, drop
from ddviz.server.source import Source
from ddviz.shared.axisscale import NoPositiveValuesError, axis_positions
from ddviz.shared.manifest import IMAGES
from ddviz.shared.palette import DEFAULT_COLORS
from ddviz.shared.scatter import FilteredColorLevelsError, ScatterSpec
from ddviz.shared.tasks import PlotTask


class _ColorLevelsRefused(Exception):
    """A plot task refused for too many color levels among the rows of the filter (`ddviz.compute.aggregate.FilteredColorLevelsError`)."""

    def response(self) -> JSONResponse:
        """Return the 400 that tells the page so, by its ``error``."""
        return JSONResponse(
            {"detail": str(self), "error": "filtered_color_levels"}, status_code=400
        )


def plot_router(
    source: Source,
    results: Results,
    broker: TaskBroker,
    max_levels: int,
    max_axis_levels: int,
    max_hover_bytes: int,
) -> APIRouter:
    """Return the routes that draw.

    Parameters
    ----------
    source : Source
        The file plotted.
    results : Results
        The drawn results, which the routes replace.
    broker : TaskBroker
        Runs the plot tasks.
    max_levels : int
        Most levels a categorical color, Symbol, Group X, Group Y or Wrap
        column may have.
    max_axis_levels : int
        Most levels a categorical x or y column may have.
    max_hover_bytes : int
        Most bytes the hover files of the overview and the view take together.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()
    # Number of the latest plot request: a plot that a newer one superseded
    # does not replace the results, so that a newer plot that fails leaves
    # those the page draws.
    latest = 0

    async def run_plot(spec: ScatterSpec) -> tuple[HoverIndex | None, dict]:
        """Run a plot task beside the open results; return its result, or None when a newer task killed it."""
        opened = (results.overview, results.view)
        used = sum(i.manifest.hover_bytes for i in opened if i is not None)
        # Replaced results that a worker still reads are on disk too.
        used += results.held_bytes
        spec = replace(spec, hover_bytes=max(max_hover_bytes - used, 0))
        started = time.perf_counter()
        end = await broker.run(PlotTask(spec))
        if end.type == "cancelled":
            return None, {}
        refused = f"{NoPositiveValuesError.__name__}: "
        if end.type == "error" and (end.error or "").startswith(refused):
            # A log axis without a positive value: the page keeps its plot.
            raise HTTPException(400, end.error.removeprefix(refused))
        too_many = f"{FilteredColorLevelsError.__name__}: "
        if end.type == "error" and (end.error or "").startswith(too_many):
            # Too many color levels among the rows of the filter: the page
            # keeps its plot and goes back to the filter it was drawn with.
            raise _ColorLevelsRefused(end.error.removeprefix(too_many))
        ensure_done(end)
        timing = {"task_seconds": time.perf_counter() - started}
        await asyncio.to_thread(source.touch, spec.hover)
        index = await asyncio.to_thread(HoverIndex, end.out)
        return index, timing

    async def run_again(spec: ScatterSpec) -> tuple[HoverIndex | None, dict]:
        """Run a plot task of the current plot; None when it was cancelled or the plot changed."""
        plot_id = results.plot_id
        index, timing = await run_plot(spec)
        if index is None or results.plot_id != plot_id:
            drop(index)
            return None, {}
        return index, timing

    def figure(index: HoverIndex, timing: dict) -> JSONResponse:
        """Return the figure of a result; the page fetches its images on their own."""
        result = build_figure(index.manifest)
        result["meta"]["task"] = int(index.out.name)
        result["meta"]["piles"] = index.piles()
        result["meta"]["filters"] = [asdict(f) for f in index.manifest.spec.filters]
        result["meta"]["hover"] = {
            "files": index.manifest.hover_files,
            "dropped": index.manifest.hover_dropped,
            "bytes": index.manifest.hover_bytes,
            "kept": [c.name for c in index.manifest.columns],
            "limit_gb": max_hover_bytes / 2**30,
        }
        result["meta"].update(timing)
        return JSONResponse(result)

    async def respec(
        request: SizeRequest, x_ranges: list | None = None, y_ranges: list | None = None
    ) -> ScatterSpec:
        """Return the overview's spec for a request's size, filter and ranges (by default its own)."""
        if results.overview is None:
            raise HTTPException(409, "no plot")
        if source.converting:
            raise HTTPException(409, "converting")
        filters = await source.filters(request.filters)
        await source.convert([f.column for f in filters])
        manifest = results.overview.manifest
        # The color levels of the filter, from the view drawn with it while
        # zoomed (`resized_spec`).
        known = results.view.manifest if results.view is not None else None
        try:
            return resized_spec(
                manifest,
                request.width,
                request.height,
                filters,
                {f.column: source.parts(f.column) for f in filters},
                manifest.x_ranges if x_ranges is None else x_ranges,
                manifest.y_ranges if y_ranges is None else y_ranges,
                margin_left=request.margin_left,
                margin_bottom=request.margin_bottom,
                known=known,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    async def aggregate_again(
        spec: ScatterSpec,
        shown: HoverIndex | None,
        keep: Callable[[HoverIndex], None],
    ) -> JSONResponse:
        """Return the figure of `spec` aggregated again, or of `shown` when it already is (`unchanged`); `keep` takes a new result."""
        if unchanged(shown.manifest if shown is not None else None, spec):
            # A task for another size must not replace the result drawn now.
            await broker.cancel()
            return figure(shown, {"task_seconds": 0.0})
        try:
            index, timing = await run_again(spec)
        except _ColorLevelsRefused as error:
            return error.response()
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        keep(index)
        return figure(index, timing)

    @router.post("/api/plot")
    async def plot(request: PlotRequest) -> JSONResponse:
        nonlocal latest
        latest += 1
        mine = latest
        try:
            encoding = Encoding.from_dict(request.encoding)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        filters = await source.filters(request.filters)
        try:
            color_bins = parse_color_bins(request.color_bins)
            wrap_cols = parse_wrap_cols(request.wrap_cols)
            smoothing = parse_smoothing(request.smooth)
            shape_size = parse_shape_size(request.shape_size)
            line_width = parse_line_width(request.line_width)
            shape_sizes = parse_shape_sizes(request.shape_sizes)
            level_shapes = parse_level_shapes(request.level_shapes)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        numeric = await source.numeric()
        missing = [c for c in encoding.columns() if c not in numeric]
        if missing:
            raise HTTPException(400, f"unknown columns: {missing}")
        if not drawable(encoding, numeric):
            raise HTTPException(
                400, "x and y need a column, or y numeric columns alone"
            )
        # The page refuses edits while converting; a plot now would kill the conversion.
        if source.converting:
            raise HTTPException(409, "converting")
        started = time.perf_counter()
        columns = drawn_columns(encoding)
        columns += [f.column for f in filters if f.column not in columns]
        await source.convert(columns)
        convert_seconds = time.perf_counter() - started
        try:
            spec = scatter_spec(
                encoding,
                {c: source.parts(c) for c in columns},
                request.width,
                request.height,
                DEFAULT_COLORS,
                filters=filters,
                numeric=numeric,
                color_bins=color_bins,
                max_levels=max_levels,
                max_axis_levels=max_axis_levels,
                wrap_cols=wrap_cols,
                smoothing=smoothing,
                shape_size=shape_size,
                temporal=await source.temporal(),
                shape_sizes=shape_sizes,
                level_shapes=level_shapes,
                show_null_rows=request.show_null_rows.model_dump(),
                axis_scales=request.axis_scales,
                margin_left=request.margin_left,
                margin_bottom=request.margin_bottom,
                line_width=line_width,
                keep_unfiltered_color_levels=request.keep_unfiltered_color_levels,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        try:
            index, timing = await run_plot(spec)
        except _ColorLevelsRefused as error:
            return error.response()
        if index is not None and mine != latest:
            drop(index)
            index = None
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        results.set_plot(index)
        return figure(
            index,
            {
                **timing,
                "convert_seconds": convert_seconds,
                "encoding": encoding.to_dict(),
                "undrawn": undrawn(encoding, numeric),
            },
        )

    @router.post("/api/view")
    async def view(request: ViewRequest) -> JSONResponse:
        """Aggregate the zoomed view of the overview.

        The ranges are of the values themselves: those of a log axis become
        its positions here (`ddviz.shared.axisscale.axis_positions`).
        """
        if results.overview is None:
            raise HTTPException(409, "no plot")
        drawn = results.overview.manifest.spec
        try:
            x_ranges = axis_positions(request.x_ranges, drawn.x, drawn.log_x)
            y_ranges = axis_positions(request.y_ranges, drawn.y, drawn.log_y)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        spec = await respec(request, x_ranges, y_ranges)
        return await aggregate_again(spec, results.view, results.set_view)

    @router.post("/api/overview")
    async def overview(request: SizeRequest) -> JSONResponse:
        """Aggregate the overview again at another size of the plot area."""
        # The padded data ranges hold every row, so this is the overview.
        spec = await respec(request)
        return await aggregate_again(spec, results.overview, results.set_overview)

    @router.get("/api/images/{task}")
    async def images(task: int) -> FileResponse:
        """Return the PNGs of a result or a selection layer one after another (its ``images`` slices it)."""
        index = results.opened(task)
        if index is not None:
            out = index.out
        elif results.layer is not None and results.layer.out.name == str(task):
            out = results.layer.out
        else:
            raise HTTPException(404, "stale")
        return FileResponse(out / IMAGES, media_type="application/octet-stream")

    @router.get("/api/hover")
    async def hover(
        task: int,
        panel: int,
        fx: float,
        fy: float,
        sx: float,
        sy: float,
        order: str = "",
        hidden: str = "",
    ) -> dict:
        """Return the row under the cursor in a result, or that the result is gone.

        `order` lists the series from the top drawn layer down; `hidden`
        the series drawn invisible (inactive at opacity 0), which never answer.
        """
        index = results.opened(task)
        if index is None:
            return {"stale": True}
        series = [int(s) for s in order.split(",") if s]
        skip = frozenset(int(s) for s in hidden.split(",") if s)
        return {"hit": index.lookup(panel, fx, fy, sx, sy, series, skip)}

    @router.get("/api/pile")
    async def pile(task: int, i: int) -> dict:
        """Return what the hover shows of a pile of a result (`HoverIndex.pile`), or that the result is gone."""
        index = results.opened(task)
        if index is None:
            return {"stale": True}
        return {"pile": index.pile(i)}

    return router
