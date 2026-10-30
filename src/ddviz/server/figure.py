"""Builds the plotly figure of a plot task: the axes of a facet grid.

The series images are not plotly traces: the page draws them on a canvas
from the figure's axes (``static/js/layers.js``). The legend and the axis
names are not plotly's either: the page shows them outside the scrolled
figure (``static/js/legend.js`` and the drop zones), and so are the tick
labels and facet labels of a grid that scrolls (``static/js/sticky.js``).
"""

from __future__ import annotations

import html
from dataclasses import asdict

from ddviz.shared.layout import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    AxisGrid,
    GridLayout,
)
from ddviz.shared.manifest import PlotManifest
from ddviz.shared.scatter import ScatterSpec

# Each plot area is white with a frame line around it, on a light gray
# figure, so neighboring panels stand apart. The frame lies just outside the
# plot area, where the series canvas (clipped to it) does not cover it; with
# the one-pixel `GAP`, neighbors share one line.
FRAME_COLOR = "#aaa"
PAPER_COLOR = "#f5f5f5"
PLOT_COLOR = "#fff"
_FRAME = {"showline": True, "mirror": True, "linecolor": FRAME_COLOR, "linewidth": 1}


def _axis_suffix(panel: int) -> str:
    """Return the plotly axis suffix of a panel: "" for the first, else its number."""
    return "" if panel == 0 else str(panel + 1)


def _label(column: str | None, level: object) -> str:
    """Return a facet label."""
    return f"{column} = {level}"


def _facet_labels(
    spec: ScatterSpec, levels: dict, layout: GridLayout, axes: AxisGrid
) -> list[dict]:
    """Return the facet labels above the grid and right of it, each over its panels.

    A wrapped grid has its labels above each panel instead, the level alone:
    the column's name is on the chip of its drop zone.
    """
    labels = []
    if spec.wrap:
        for panel, level in enumerate(levels["col"]):
            prow, pcol = divmod(panel, layout.ncol)
            lo, hi = layout.x_domain(pcol)
            labels.append(
                {
                    "text": str(level),
                    "x": (lo + hi) / 2,
                    "y": layout.y_domain(prow)[1],
                    "xanchor": "center",
                    "yanchor": "bottom",
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                }
            )
        return labels
    if spec.col is not None:
        for col, level in enumerate(levels["col"]):
            lo = layout.x_domain(col * axes.nx)[0]
            hi = layout.x_domain(col * axes.nx + axes.nx - 1)[1]
            labels.append(
                {
                    "text": _label(spec.col, level),
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
            )
    if spec.row is not None:
        for row, level in enumerate(levels["row"]):
            lo = layout.y_domain(row * axes.ny + axes.ny - 1)[0]
            hi = layout.y_domain(row * axes.ny)[1]
            labels.append(
                {
                    "text": _label(spec.row, level),
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
            )
    return labels


def _band_ticks(manifest: PlotManifest, column: str) -> dict:
    """Return the ticks of an axis column: a categorical one's levels at the middle of their bands, else plotly's."""
    levels = manifest.axis_levels.get(column)
    if levels is None:
        return {}
    # plotly reads tick text as its own markup; the levels are the data's.
    return {
        "tickmode": "array",
        "tickvals": list(range(len(levels))),
        "ticktext": [html.escape(str(v), quote=False) for v in levels],
        "showgrid": False,
    }


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
    }


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
        axes, the axis columns (``x``, ``y``: their indices) and the facet
        levels (``facet``: row and col as text, or None) of each panel,
        the axes that hold the range of each x and y column (``x_axes``,
        ``y_axes``), the bin grid, the data range of each column, where each
        series' PNG lies in the images file (`ddviz.shared.manifest.IMAGES`; its
        panels are tiles, ``ncol`` to a row, as `ddviz.compute.raster.atlas`),
        whether the grid scrolls, its facet labels (plotly annotations in
        paper coordinates; the figure has them only when the grid fits, and
        a wrapped grid has them in the figure only), and
        how the series are colored
        (``color``: ``kind`` is ``"levels"``, ``"bins"`` for the intervals of
        a numeric column, or ``"gradient"``, whose single image holds grays
        from 1 to 255 over ``range``).
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
            **_band_ticks(manifest, spec.x[xi]),
            **_FRAME,
            **({"matches": x_axes[xi]} if x_axis != x_axes[xi] else {}),
        }
        fig_layout[f"yaxis{suffix}"] = {
            "domain": layout.y_domain(prow),
            "anchor": x_axis,
            "range": list(y_ranges[yj]),
            "showticklabels": not layout.scroll and pcol == 0,
            "zeroline": False,
            **_band_ticks(manifest, spec.y[yj]),
            **_FRAME,
            **({"matches": y_axes[yj]} if y_axis != y_axes[yj] else {}),
        }
        facet = [
            None if getattr(spec, role) is None else str(levels[role][i])
            for role, i in zip(("row", "col"), axes.facet(panel), strict=True)
        ]
        panels.append(
            {"xaxis": x_axis, "yaxis": y_axis, "x": xi, "y": yj, "facet": facet}
        )
    # A grid that scrolls has its tick labels and facet labels in strips
    # along the edges of the area (``static/js/sticky.js``), so that they
    # stay in sight: plotly draws neither.
    labels = _facet_labels(spec, levels, layout, axes)
    if spec.wrap:
        # A wrapped grid's labels lie between its panels: plotly draws them,
        # and they scroll with their panels.
        fig_layout["annotations"] += labels
        labels = []
    elif not layout.scroll:
        fig_layout["annotations"] += labels
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
        "grid": asdict(manifest.grid),
        "x_ranges": [list(r) for r in x_ranges],
        "y_ranges": [list(r) for r in y_ranges],
        "series": [str(v) for v in levels["color"]],
        "color": _color_scale(manifest),
        "colors": manifest.colors,
        "images": manifest.images,
        "ncol": layout.ncol,
        "rows": manifest.rows,
        "scroll": layout.scroll,
        "facet_labels": labels,
    }
    return {"figure": {"data": data, "layout": fig_layout}, "meta": meta}
