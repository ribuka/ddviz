"""Routes that draw: a plot, its zoomed view, its overview at another size, and hovers.

The hover files of the open results (the overview and the view) keep
within ``max_hover_bytes`` together: a new result gets what the results
open while it is written leave, those it replaces included, as they go only
once it is open (`ddviz.compute.hoverfit`); its figure tells the page which
hover columns were left out.

Every plot, view and overview request carries the conditions of the local
filter (`ddviz.server.plan.parse_filters`); the result's spec keeps them, so
the selection and the table of a result follow its filter.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, replace

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ddviz.server.broker import TaskBroker
from ddviz.server.derive import resized_spec, unchanged
from ddviz.server.encoding import Encoding
from ddviz.server.errors import ensure_done
from ddviz.server.figure import build_figure
from ddviz.server.hover import HoverIndex
from ddviz.server.models import PlotRequest, SizeRequest, ViewRequest
from ddviz.server.plan import (
    drawable,
    drawn_columns,
    parse_color_bins,
    parse_shape_size,
    parse_smoothing,
    parse_wrap_cols,
    scatter_spec,
    undrawn,
)
from ddviz.server.results import Results, drop
from ddviz.server.source import Source
from ddviz.shared.manifest import IMAGES
from ddviz.shared.palette import DEFAULT_COLORS
from ddviz.shared.scatter import ScatterSpec
from ddviz.shared.tasks import PlotTask


def plot_router(
    source: Source,
    results: Results,
    broker: TaskBroker,
    max_levels: int,
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
        Most levels a categorical x, y, color, Group X, Group Y or Wrap
        column may have.
    max_hover_bytes : int
        Most bytes the hover files of the overview and the view take together.

    Returns
    -------
    fastapi.APIRouter
        The routes.
    """
    router = APIRouter()

    async def run_plot(spec: ScatterSpec) -> tuple[HoverIndex | None, dict]:
        """Run a plot task beside the open results; return its result, or None when a newer task killed it."""
        opened = (results.overview, results.view)
        used = sum(i.manifest.hover_bytes for i in opened if i is not None)
        spec = replace(spec, hover_bytes=max(max_hover_bytes - used, 0))
        started = time.perf_counter()
        end = await broker.run(PlotTask(spec))
        if end.type == "cancelled":
            return None, {}
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
        try:
            return resized_spec(
                manifest,
                request.width,
                request.height,
                filters,
                {f.column: source.parts(f.column) for f in filters},
                manifest.x_ranges if x_ranges is None else x_ranges,
                manifest.y_ranges if y_ranges is None else y_ranges,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/api/plot")
    async def plot(request: PlotRequest) -> JSONResponse:
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
                filters,
                numeric,
                color_bins,
                max_levels,
                wrap_cols,
                smoothing,
                shape_size,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        results.plot_id += 1
        index, timing = await run_plot(spec)
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
        """Aggregate the zoomed view of the overview."""
        spec = await respec(request, request.x_ranges, request.y_ranges)
        if unchanged(results.view.manifest if results.view else None, spec):
            # A task for another size must not replace the result drawn now.
            await broker.cancel()
            return figure(results.view, {"task_seconds": 0.0})
        index, timing = await run_again(spec)
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        results.set_view(index)
        return figure(index, timing)

    @router.post("/api/overview")
    async def overview(request: SizeRequest) -> JSONResponse:
        """Aggregate the overview again at another size of the plot area."""
        # The padded data ranges hold every row, so this is the overview.
        spec = await respec(request)
        if unchanged(results.overview.manifest, spec):
            await broker.cancel()
            return figure(results.overview, {"task_seconds": 0.0})
        index, timing = await run_again(spec)
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        results.set_overview(index)
        return figure(index, timing)

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
    ) -> dict:
        """Return the row under the cursor in a result, or that the result is gone."""
        index = results.opened(task)
        if index is None:
            return {"stale": True}
        series = [int(s) for s in order.split(",") if s]
        return {"hit": index.lookup(panel, fx, fy, sx, sy, series)}

    @router.get("/api/events")
    async def events() -> StreamingResponse:
        """Stream the progress messages of the plot pool's tasks."""
        queue = broker.listen()

        async def stream() -> AsyncIterator[str]:
            try:
                while True:
                    message = await queue.get()
                    yield f"data: {json.dumps(message)}\n\n"
            finally:
                broker.unlisten(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
