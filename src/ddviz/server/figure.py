"""Builds the plotly figure of a plot task: the axes of a facet grid.

The series images are not plotly traces: the page draws them on a canvas
from the figure's axes (``static/js/layers.js``). The legend and the axis
names are not plotly's either: the page shows them outside the scrolled
figure (``static/js/legend.js`` and the drop zones), and so are the tick
labels and facet labels of a grid that scrolls (``static/js/sticky.js``).
"""

from __future__ import annotations

from dataclasses import asdict

from ddviz.server.labeltext import facet_text, fit_text, level_text, plotly_text
from ddviz.shared.layout import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    AxisGrid,
    GridLayout,
    wrap_columns,
)
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.missing import shown_level
from ddviz.shared.scatter import ONE_BAND, ScatterSpec
from ddviz.shared.shapes import SHAPES, kernel
from ddviz.shared.temporal import DATE_KINDS

# Each plot area is white with a frame line around it, on a light gray
# figure, so neighboring panels stand apart. The frame lies just outside the
# plot area, where the series canvas (clipped to it) does not cover it; with
# the one-pixel `GAP`, neighbors share one line.
FRAME_COLOR = "#aaa"
PAPER_COLOR = "#f5f5f5"
PLOT_COLOR = "#fff"
_FRAME = {"showline": True, "mirror": True, "linecolor": FRAME_COLOR, "linewidth": 1}
# Half the width of a band of a categorical axis (`ddviz.compute.bands.BAND`).
BAND = 0.4
# Room between the tick labels of a categorical axis, and from a y tick label
# to the left edge, in pixels.
TICK_PAD = 6
# Numeric ticks write an exponent as "1e+300", not plotly's "1×10³⁰⁰": the
# left margin had room for the exponent only, without the digits before it.
EXPONENT = {"exponentformat": "e"}
# Size in pixels of the shapes drawn in the panel that picks a level's
# shape (`_overlay`).
CHOICE_SIZE = 9


def _axis_suffix(panel: int) -> str:
    """Return the plotly axis suffix of a panel: "" for the first, else its number."""
    return "" if panel == 0 else str(panel + 1)


def _fitted(label: dict, text: str, shown: str) -> dict:
    """Return a facet label showing `shown`; one cut from `text` keeps it whole as its hover text."""
    if shown != text:
        label["hovertext"] = text
    return {"text": shown, **label}


def _for_plotly(label: dict) -> dict:
    """Return a facet label for plotly, which reads its text as markup; the page's strips set it as text."""
    escaped = {k: plotly_text(label[k]) for k in ("text", "hovertext") if k in label}
    return {**label, **escaped}


def _facet_labels(
    spec: ScatterSpec, levels: dict, layout: GridLayout, axes: AxisGrid
) -> list[dict]:
    """Return the facet labels above the grid and right of it, each over its panels.

    A wrapped grid has its labels above each panel instead, the level alone:
    the column's name is on the chip of its drop zone.
    """
    labels = []
    width = layout.width - MARGIN_LEFT - MARGIN_RIGHT
    height = layout.height - MARGIN_TOP - MARGIN_BOTTOM
    if spec.wrap:
        for panel, level in enumerate(levels["col"]):
            prow, pcol = divmod(panel, layout.ncol)
            lo, hi = layout.x_domain(pcol)
            label = {
                "x": (lo + hi) / 2,
                "y": layout.y_domain(prow)[1],
                "xanchor": "center",
                "yanchor": "bottom",
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
            }
            text = level_text(level)
            labels.append(_fitted(label, text, fit_text(text, (hi - lo) * width)))
        return labels
    if spec.col is not None:
        for col, level in enumerate(levels["col"]):
            lo = layout.x_domain(col * axes.nx)[0]
            hi = layout.x_domain(col * axes.nx + axes.nx - 1)[1]
            label = {
                "x": (lo + hi) / 2,
                "y": 1,
                # plotly's "auto" anchors a label left of the middle
                # third by its left end, right of it by its right end.
                "xanchor": "center",
                "yanchor": "bottom",
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
            }
            shown = facet_text(spec.col, level, (hi - lo) * width)
            labels.append(_fitted(label, f"{spec.col} = {level_text(level)}", shown))
    if spec.row is not None:
        for row, level in enumerate(levels["row"]):
            lo = layout.y_domain(row * axes.ny + axes.ny - 1)[0]
            hi = layout.y_domain(row * axes.ny)[1]
            label = {
                "x": 1,
                "y": (lo + hi) / 2,
                "xanchor": "left",
                "yanchor": "middle",
                "xshift": 4,
                "textangle": 90,
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
            }
            shown = facet_text(spec.row, level, (hi - lo) * height)
            labels.append(_fitted(label, f"{spec.row} = {level_text(level)}", shown))
    return labels


def _band_ticks(manifest: PlotManifest, column: str, room: float | None) -> dict:
    """Return the ticks of an axis column: a categorical one's levels at the middle of their bands, else plotly's.

    The page gives a categorical column's axis the ticks of the range it
    shows, thinned to labels that can be read (``static/js/bandticks.js``),
    from the levels of the meta (``axis_levels``); the figure has none. The
    one band has a tick under each series' box: a name longer than its
    room (``room`` pixels: its band's width on an x axis; None on a y axis,
    whose ticks have the left margin) ends in "…".
    """
    levels = manifest.axis_levels.get(column)
    if levels is None:
        return {}
    if column != ONE_BAND:
        return {"tickmode": "array", "tickvals": [], "ticktext": [], "showgrid": False}
    ticks = _series_ticks(manifest)
    if room is None:
        room = MARGIN_LEFT - TICK_PAD
    else:
        room = room / max(len(ticks), 1) - TICK_PAD
    texts = [fit_text(level_text(v), room) for v in ticks.values()]
    # plotly reads tick text as its own markup; the levels are the data's.
    return {
        "tickmode": "array",
        "tickvals": list(ticks),
        "ticktext": [plotly_text(t) for t in texts],
        "showgrid": False,
    }


def _date_axis(spec: ScatterSpec, column: str) -> dict:
    """Return the type of an axis column of a datetime, date or time: plotly's date axis, over milliseconds.

    A time lies on the first day of the epoch: its ticks show the time
    alone, to the millisecond when zoomed below a second.
    """
    kind = spec.temporal.get(column)
    if kind not in DATE_KINDS:
        return {}
    axis: dict = {"type": "date"}
    if kind == "time":
        axis["tickformatstops"] = [
            {"dtickrange": [None, 1000], "value": "%H:%M:%S.%L"},
            {"dtickrange": [1000, None], "value": "%H:%M:%S"},
        ]
    return axis


def _numeric_axis(manifest: PlotManifest, column: str) -> bool:
    """Return whether an axis column is drawn on a numeric axis: not categorical, temporal or the one band.

    The page sets the range, ticks and reference lines of such an axis
    (``static/js/axisdialog.js``).
    """
    spec = manifest.spec
    return (
        column != ONE_BAND
        and column not in manifest.axis_levels
        and column not in spec.temporal
    )


def _loggable_axis(manifest: PlotManifest, column: str) -> bool:
    """Return whether an axis column may lie on a log axis: a number or a duration (`ddviz.shared.axisscale.loggable`)."""
    spec = manifest.spec
    return (
        column != ONE_BAND
        and column not in manifest.axis_levels
        and spec.temporal.get(column) not in DATE_KINDS
    )


def _log_axis(log: bool) -> dict:
    """Return the type of a log axis: plotly's log axis, whose range is of exponents, as the result's ranges are."""
    return {"type": "log"} if log else {}


def _series_ticks(manifest: PlotManifest) -> dict[float, str]:
    """Return the ticks of the one band (`ddviz.shared.scatter.ONE_BAND`): each series' name under its box.

    Without box plots or series (no color column, a gradient, or a color
    column without values) it has none. A series of a color level and an overlay level is named by both.
    A gradient beside its missing level (`ddviz.shared.missing`) names its
    own level by its column.
    """
    spec, levels = manifest.spec, manifest.levels
    colors, overlays = levels["color"], levels["overlay"]
    if not spec.box or colors == [None]:
        return {}

    def name(c: object) -> str:
        return spec.color if c is None else shown_level(c, colors)

    names = [
        name(c) if spec.overlay is None else f"{name(c)} / {shown_level(o, overlays)}"
        for c in colors
        for o in overlays
    ]
    if not names:
        return {}
    # The boxes split the band into a slot per series (``static/js/boxes.js``).
    slot = 2 * BAND / len(names)
    return {-BAND + slot * (s + 0.5): name for s, name in enumerate(names)}


def _color_scale(manifest: PlotManifest) -> dict:
    """Return how the page colors the series: by level, by intervals of a numeric column, or by a gradient."""
    spec = manifest.spec
    bins = spec.binned.get("color")
    if spec.gradient:
        kind = "gradient"
    elif bins is not None:
        kind = "bins"
    else:
        kind = "levels"
    return {
        "column": spec.color,
        "kind": kind,
        "bins": None if bins is None else asdict(bins),
        "range": manifest.color_range,
        # The kind of a temporal column, whose gradient's ticks are dates.
        "temporal": spec.temporal.get(spec.color),
        # Series per color level: one per overlay level.
        "shapes": len(manifest.levels["overlay"]),
    }


def _overlay(manifest: PlotManifest) -> dict | None:
    """Return the overlay levels and their marker shapes (`ddviz.shared.shapes.kernel`, rows from the top), or None without an overlay."""
    spec = manifest.spec
    if spec.overlay is None:
        return None
    levels = manifest.levels["overlay"]
    sizes = spec.marker_sizes(levels)
    shapes = spec.marker_shapes(levels)
    return {
        "column": spec.overlay,
        "levels": [str(v) for v in levels],
        # Size in pixels of each level's shapes (`ScatterSpec.marker_sizes`).
        "sizes": sizes if levels else [],
        # Shape of each level (`ScatterSpec.marker_shapes`).
        "shapes": shapes if levels else [],
        "kernels": [
            kernel(shapes[i], sizes[i]).astype(int).tolist() for i in range(len(levels))
        ],
        # Every shape a level can take, drawn in the panel that picks one.
        "choices": [
            {"name": name, "kernel": kernel(name, CHOICE_SIZE).astype(int).tolist()}
            for name in SHAPES
        ],
    }


def _panel_boxes(manifest: PlotManifest) -> dict[tuple, list[list[float]]]:
    """Return the box plots of each pair of axis columns and facet cell, as the page draws them."""
    boxes: dict[tuple, list[list[float]]] = {}
    for pair in manifest.boxes:
        for row, col, *box in pair.stats:
            boxes.setdefault((pair.x, pair.y, int(row), int(col)), []).append(
                [int(box[0]), int(box[1]), *box[2:]]
            )
    return boxes


def _panel_smooths(manifest: PlotManifest) -> dict[tuple, list[list]]:
    """Return the smoothing lines of each pair of axis columns and facet cell, as the page draws them."""
    smooths: dict[tuple, list[list]] = {}
    for pair in manifest.smooths:
        for row, col, series, xs, ys in pair.lines:
            smooths.setdefault((pair.x, pair.y, int(row), int(col)), []).append(
                [int(series), xs, ys]
            )
    return smooths


def build_figure(manifest: PlotManifest) -> dict:
    """Return the figure of a plot task and what the page needs to draw its images.

    The figure holds the axes of every panel, each kept by an empty scatter
    trace (plotly leaves out the axes of a subplot without traces). A
    categorical axis has a tick at the middle of each level's band. The axes
    of the panels of one x column match, and so do those of one y column.

    Parameters
    ----------
    manifest : PlotManifest
        Manifest of the plot task.

    Returns
    -------
    dict
        ``{"figure": {"data", "layout"}, "meta": {...}}``; the meta holds the
        axes, the axis columns (``x``, ``y``: their indices), the facet
        levels (``facet``: row and col as text, or None), whether the
        points of every row are drawn (``points``) and the box plots
        (``boxes``: ``[level, series, n, low, q1, median, q3, high]`` each,
        `ddviz.shared.scatter.Boxes`) and smoothing lines (``smooths``:
        ``[series, xs, ys]`` each, `ddviz.shared.scatter.Smooths`) of each
        panel, the levels of each
        categorical axis column (``axis_levels``), whether the x axis is
        the one band (``one_band``, `ddviz.shared.scatter.ONE_BAND`),
        the kind of each temporal column (``temporal``,
        `ddviz.shared.temporal.KINDS`: a datetime, date or time axis is
        plotly's date axis over milliseconds),
        the axes that hold the range of each x and y column (``x_axes``,
        ``y_axes``), whether each x and y column is on a numeric axis
        (``x_numeric``, ``y_numeric``: linear, and not categorical, temporal
        or the one band), whether each may lie on a log axis and does
        (``x_loggable``, ``x_log`` and those of y: a number or a duration;
        the ranges of a log axis are exponents), the log axis columns
        with rows left out for a value not positive (``nonpositive``,
        ``[role, column]`` each), the bin grid, the data range of each column, where each
        series' PNG lies in the images file (`ddviz.shared.manifest.IMAGES`; its
        panels are tiles, ``ncol`` to a row, as `ddviz.compute.raster.atlas`),
        the panels a wrapped grid would put to a row with no number set
        (``wrap_auto_cols``, `ddviz.shared.layout.wrap_columns`; None
        without wrapping),
        whether the grid scrolls, its facet labels (plotly annotations in
        paper coordinates; the figure has them only when the grid fits, and
        a wrapped grid has them in the figure only), and
        how the series are colored
        (``color``: ``kind`` is ``"levels"``, ``"bins"`` for the intervals of
        a numeric column, or ``"gradient"``, whose images hold grays
        from 1 to 255 over ``range``; ``shapes`` series per color level),
        and the overlay levels with their marker shapes (``overlay``, or
        None): series ``s`` is color level ``s // shapes`` (of ``series``)
        and overlay level ``s % shapes``.
    """
    spec, layout, axes = manifest.spec, manifest.layout, manifest.axes
    x_ranges, y_ranges = manifest.x_ranges, manifest.y_ranges
    levels = manifest.levels
    # The first panel of each x column (the top row) and of each y column
    # (the left column) holds its range; the other panels match it.
    x_axes = [f"x{_axis_suffix(axes.panel(0, 0, xi, 0))}" for xi in range(axes.nx)]
    y_axes = [f"y{_axis_suffix(axes.panel(0, 0, 0, yj))}" for yj in range(axes.ny)]

    fig_layout: dict = {
        "width": layout.width,
        "height": layout.height,
        "margin": {
            "l": MARGIN_LEFT,
            "r": MARGIN_RIGHT,
            "t": MARGIN_TOP,
            "b": MARGIN_BOTTOM,
            "autoexpand": False,
        },
        "hovermode": False,
        "dragmode": "pan",
        "showlegend": False,
        "paper_bgcolor": PAPER_COLOR,
        "plot_bgcolor": PLOT_COLOR,
        "annotations": [],
    }
    panels = []
    boxes = _panel_boxes(manifest)
    smooths = _panel_smooths(manifest)
    for panel in range(axes.panels):
        prow, pcol = divmod(panel, layout.ncol)
        xi, yj = axes.axes(panel)
        suffix = _axis_suffix(panel)
        x_axis, y_axis = f"x{suffix}", f"y{suffix}"
        # The bottom panel of each panel column, above the empty cells of a
        # wrapped grid, shows the x ticks.
        bottom = panel + layout.ncol >= axes.panels
        fig_layout[f"xaxis{suffix}"] = {
            "domain": layout.x_domain(pcol),
            "anchor": y_axis,
            "range": list(x_ranges[xi]),
            "showticklabels": not layout.scroll and bottom,
            "zeroline": False,
            **EXPONENT,
            **_band_ticks(manifest, spec.x[xi], layout.panel_width),
            **_date_axis(spec, spec.x[xi]),
            **_log_axis(spec.x[xi] in spec.log_x),
            **_FRAME,
            **({"matches": x_axes[xi]} if x_axis != x_axes[xi] else {}),
        }
        fig_layout[f"yaxis{suffix}"] = {
            "domain": layout.y_domain(prow),
            "anchor": x_axis,
            "range": list(y_ranges[yj]),
            "showticklabels": not layout.scroll and pcol == 0,
            "zeroline": False,
            **EXPONENT,
            **_band_ticks(manifest, spec.y[yj], None),
            **_date_axis(spec, spec.y[yj]),
            **_log_axis(spec.y[yj] in spec.log_y),
            **_FRAME,
            **({"matches": y_axes[yj]} if y_axis != y_axes[yj] else {}),
        }
        facet = [
            None if getattr(spec, role) is None else str(levels[role][i])
            for role, i in zip(("row", "col"), axes.facet(panel), strict=True)
        ]
        row, col = axes.facet(panel)
        panels.append(
            {
                "xaxis": x_axis,
                "yaxis": y_axis,
                "x": xi,
                "y": yj,
                "facet": facet,
                "points": spec.draws_points(spec.x[xi], spec.y[yj]),
                "boxes": boxes.get((spec.x[xi], spec.y[yj], row, col), []),
                "smooths": smooths.get((spec.x[xi], spec.y[yj], row, col), []),
            }
        )
    # A grid that scrolls has its tick labels and facet labels in strips
    # along the edges of the area (``static/js/sticky.js``), so that they
    # stay in sight: plotly draws neither.
    labels = _facet_labels(spec, levels, layout, axes)
    if spec.wrap:
        # A wrapped grid's labels lie between its panels: plotly draws them,
        # and they scroll with their panels.
        fig_layout["annotations"] += [_for_plotly(a) for a in labels]
        labels = []
    elif not layout.scroll:
        fig_layout["annotations"] += [_for_plotly(a) for a in labels]
    # plotly leaves out the axes of a subplot without traces.
    data = [
        {
            "type": "scatter",
            "mode": "markers",
            "x": [],
            "y": [],
            "xaxis": panel["xaxis"],
            "yaxis": panel["yaxis"],
            "showlegend": False,
            "hoverinfo": "skip",
        }
        for panel in panels
    ]
    meta = {
        "panels": panels,
        "x_columns": spec.x,
        "y_columns": spec.y,
        "x_axes": x_axes,
        "y_axes": y_axes,
        # The axis dialog (`static/js/axisdialog.js`) is of linear axes.
        "x_numeric": [
            _numeric_axis(manifest, c) and c not in spec.log_x for c in spec.x
        ],
        "y_numeric": [
            _numeric_axis(manifest, c) and c not in spec.log_y for c in spec.y
        ],
        # Whether each axis column may lie on a log axis, and whether it does.
        "x_loggable": [_loggable_axis(manifest, c) for c in spec.x],
        "y_loggable": [_loggable_axis(manifest, c) for c in spec.y],
        "x_log": [c in spec.log_x for c in spec.x],
        "y_log": [c in spec.log_y for c in spec.y],
        # The log axis columns with rows left out for a value not positive.
        "nonpositive": manifest.nonpositive,
        "grid": asdict(manifest.grid),
        "x_ranges": [list(r) for r in x_ranges],
        "y_ranges": [list(r) for r in y_ranges],
        "series": [str(v) for v in levels["color"]],
        "color": _color_scale(manifest),
        "overlay": _overlay(manifest),
        # Size in pixels of the markers of every series
        # (`ddviz.shared.shapes.marker`); an overlay level may have its own
        # (`overlay.sizes`).
        "marker_size": spec.shape_size,
        "colors": manifest.colors,
        "images": manifest.images,
        "ncol": layout.ncol,
        # Wrapped panels to a row with no number set (`wrap_columns` for the
        # levels and the size requested), whatever number the user set; None
        # without a wrap column.
        "wrap_auto_cols": (
            wrap_columns(axes.wrap, spec.width, spec.height) if axes.wrap else None
        ),
        "rows": manifest.rows,
        "scroll": layout.scroll,
        "facet_labels": labels,
        "axis_levels": manifest.axis_levels,
        "one_band": spec.x == [ONE_BAND],
        "temporal": spec.temporal,
    }
    return {"figure": {"data": data, "layout": fig_layout}, "meta": meta}
