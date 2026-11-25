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
from ddviz.server.plan import (
    FACET_BINS,
    categorical_axes,
    color_kind,
    cut_roles,
    drawable,
    drawn_columns,
    scatter_spec,
    undrawn,
)
from ddviz.server.plotoptions import (
    parse_color_scale,
    parse_cuts,
    parse_keep_axis_levels,
    parse_plot_options,
    parse_range_levels,
    spec_color_kind,
)
from ddviz.server.results import Results, drop
from ddviz.server.settings import Settings
from ddviz.server.source import Source
from ddviz.shared.axisscale import NoPositiveValuesError, axis_positions
from ddviz.shared.manifest import IMAGES
from ddviz.shared.palette import DEFAULT_COLORS
from ddviz.shared.scatter import ONE_BAND, FilteredLevelsError, ScatterSpec
from ddviz.shared.tasks import PlotTask


class _LevelsRefused(Exception):
    """A plot task refused for too many levels among the rows of the filter (`ddviz.shared.scatter.FilteredLevelsError`)."""

    def response(self) -> JSONResponse:
        """Return the 400 that tells the page so, by its ``error``."""
        return JSONResponse(
            {"detail": str(self), "error": "filtered_levels"}, status_code=400
        )


def plot_router(  # noqa: C901, PLR0915
    source: Source,
    results: Results,
    broker: TaskBroker,
    settings: Callable[[], Settings],
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
    settings : callable
        Returns the settings in effect (`ddviz.server.settings_store`). A
        plot reads them once when it starts: ``plot.max_levels`` (the most
        levels of a categorical Color, Symbol, Group X, Group Y or Wrap
        column, and the most intervals of a numeric color column),
        ``plot.max_axis_levels`` (the most levels of a categorical x or y)
        and ``hover.max_temp_bytes`` (the most bytes the hover files of the
        overview and the view take together); a view or an overview
        aggregated again reads them too, when it is asked for, so that a new
        filter counts its color levels against the limit in effect then.

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

    async def run_plot(
        spec: ScatterSpec, max_hover_bytes: int
    ) -> tuple[HoverIndex | None, dict]:
        """Run a plot task beside the open results, whose hover files take at most `max_hover_bytes` with theirs; return its result, or None when a newer task killed it."""
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
        too_many = f"{FilteredLevelsError.__name__}: "
        if end.type == "error" and (end.error or "").startswith(too_many):
            # Too many levels among the rows of the filter: the page keeps
            # its plot and goes back to the filter it was drawn with.
            raise _LevelsRefused(end.error.removeprefix(too_many))
        ensure_done(end)
        timing = {"task_seconds": time.perf_counter() - started}
        await asyncio.to_thread(source.touch, spec.hover)
        index = await asyncio.to_thread(HoverIndex, end.out)
        return index, timing

    async def run_again(
        spec: ScatterSpec, max_hover_bytes: int
    ) -> tuple[HoverIndex | None, dict]:
        """Run a plot task of the current plot (`run_plot`); None when it was cancelled or the plot changed."""
        plot_id = results.plot_id
        index, timing = await run_plot(spec, max_hover_bytes)
        if index is None or results.plot_id != plot_id:
            drop(index)
            return None, {}
        return index, timing

    def figure(index: HoverIndex, timing: dict, max_hover_bytes: int) -> JSONResponse:
        """Return the figure of a result; the page fetches its images on their own.

        To the meta of `build_figure` (`ddviz.server.figure.FigureMeta`) it
        adds the task (``task``), the piles the page draws (``piles``), the local
        filters drawn (``filters``), what the hover holds (``hover``:
        ``files``, ``dropped``, ``bytes``, ``kept``, and ``limit_gb``, the
        limit `max_hover_bytes` in GB), and
        ``timing``: the seconds of the task (``task_seconds``) and, for
        ``/api/plot``, of the conversion (``convert_seconds``), the encoding
        (``encoding``) and the roles placed but not drawn (``undrawn``).
        """
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
        request: SizeRequest,
        x_ranges: list | None = None,
        y_ranges: list | None = None,
        range_levels: object = None,
    ) -> ScatterSpec:
        """Return the overview's spec for a request's size, filter and ranges (by default the automatic ranges of the filter).

        `range_levels` are the levels the ranges of the categorical axes are
        positions among, as the page sends them
        (`ddviz.server.plotoptions.parse_range_levels`).
        """
        if results.overview is None:
            raise HTTPException(409, "no plot")
        if source.converting:
            raise HTTPException(409, "converting")
        manifest = results.overview.manifest
        # One snapshot of the settings for the whole request: the limits of
        # levels in effect now, not those of the plot's creation.
        current = settings()
        # Checked before any task, the conversion's included.
        try:
            color_scale = parse_color_scale(
                request.color_scale,
                spec_color_kind(manifest.spec),
                current.plot.max_levels,
            )
            cuts = parse_cuts(
                request.cuts,
                [r for r in manifest.spec.binned if r != "color"],
                FACET_BINS,
            )
            range_levels = parse_range_levels(
                range_levels,
                [c for c in manifest.spec.categorical if c != ONE_BAND],
                current.plot.max_axis_levels,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        filters = await source.filters(request.filters)
        await source.convert([f.column for f in filters])
        manifest = results.overview.manifest
        # The color levels and the automatic ranges of the filter, from the
        # view drawn with it while zoomed (`resized_spec`).
        known = results.view.manifest if results.view is not None else None
        try:
            spec = resized_spec(
                manifest,
                request.width,
                request.height,
                filters,
                {f.column: source.parts(f.column) for f in filters},
                [None] * len(manifest.spec.x) if x_ranges is None else x_ranges,
                [None] * len(manifest.spec.y) if y_ranges is None else y_ranges,
                margin_left=request.margin_left,
                margin_bottom=request.margin_bottom,
                known=known,
                color_scale=color_scale,
                cuts=cuts,
                range_levels=range_levels,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return replace(
            spec,
            max_levels=current.plot.max_levels,
            max_axis_levels=current.plot.max_axis_levels,
        )

    async def aggregate_again(
        spec: ScatterSpec,
        shown: HoverIndex | None,
        keep: Callable[[HoverIndex], None],
    ) -> JSONResponse:
        """Return the figure of `spec` aggregated again, or of `shown` when it already is (`unchanged`); `keep` takes a new result."""
        max_hover_bytes = settings().hover.max_temp_bytes
        if unchanged(shown.manifest if shown is not None else None, spec):
            # A task for another size must not replace the result drawn now.
            await broker.cancel()
            return figure(shown, {"task_seconds": 0.0}, max_hover_bytes)
        try:
            index, timing = await run_again(spec, max_hover_bytes)
        except _LevelsRefused as error:
            return error.response()
        if index is None:
            return JSONResponse({"cancelled": True}, status_code=409)
        keep(index)
        return figure(index, timing, max_hover_bytes)

    @router.post("/api/plot")
    async def plot(request: PlotRequest) -> JSONResponse:  # noqa: C901
        nonlocal latest
        latest += 1
        mine = latest
        # One snapshot of the settings for the whole plot.
        current = settings()
        max_levels = current.plot.max_levels
        try:
            encoding = Encoding.from_dict(request.encoding)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        filters = await source.filters(request.filters)
        try:
            options = parse_plot_options(request, max_levels)
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
        # Checked before the conversion: the scale kept of a color neither a
        # gradient nor cut is none, and the axes that keep their levels are
        # categorical axis columns of the graph.
        try:
            options = replace(
                options,
                color_scale=parse_color_scale(
                    request.color_scale,
                    color_kind(encoding.color, numeric, options.color_bins),
                    max_levels,
                ),
                cuts=parse_cuts(
                    request.cuts, cut_roles(encoding, numeric), FACET_BINS
                ),
                keep_unfiltered_axis_levels=parse_keep_axis_levels(
                    request.keep_unfiltered_axis_levels,
                    categorical_axes(encoding, numeric),
                ),
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
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
                max_levels=max_levels,
                max_axis_levels=current.plot.max_axis_levels,
                temporal=await source.temporal(),
                axis_scales=request.axis_scales,
                margin_left=request.margin_left,
                margin_bottom=request.margin_bottom,
                options=options,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        try:
            index, timing = await run_plot(spec, current.hover.max_temp_bytes)
        except _LevelsRefused as error:
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
            current.hover.max_temp_bytes,
        )

    @router.post("/api/view")
    async def view(request: ViewRequest) -> JSONResponse:
        """Aggregate the zoomed view of the overview.

        The ranges are of the values themselves: those of a log axis become
        its positions here (`ddviz.shared.axisscale.axis_positions`). A
        null range is the column's automatic range of the request's filter.
        """
        if results.overview is None:
            raise HTTPException(409, "no plot")
        drawn = results.overview.manifest.spec
        try:
            x_ranges = axis_positions(request.x_ranges, drawn.x, drawn.log_x)
            y_ranges = axis_positions(request.y_ranges, drawn.y, drawn.log_y)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        spec = await respec(request, x_ranges, y_ranges, request.range_levels)
        return await aggregate_again(spec, results.view, results.set_view)

    @router.post("/api/overview")
    async def overview(request: SizeRequest) -> JSONResponse:
        """Aggregate the overview again at another size of the plot area, or for another filter.

        It spans the automatic ranges of the request's filter: those of a
        result of that filter, or else found by the worker.
        """
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
