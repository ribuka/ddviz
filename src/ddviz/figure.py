"""Builds the plotly figure of a plot task: the axes of a facet grid.

The series images are not plotly traces: the page draws them on a canvas
from the figure's axes (``static/js/layers.js``). The legend and the axis
names are not plotly's either: the page shows them outside the scrolled
figure (``static/js/legend.js`` and the drop zones).
"""

from __future__ import annotations

from ddviz.layout import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    AxisGrid,
    GridLayout,
)

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


def _panel_titles(
    spec: dict, levels: dict, layout: GridLayout, axes: AxisGrid
) -> list[dict]:
    """Return a title above each panel, for a grid that scrolls.

    The title names the facet cell and, with several axis columns, the
    panel's y and x columns.
    """
    titles = []
    several = axes.nx > 1 or axes.ny > 1
    for panel in range(layout.nrow * layout.ncol):
        prow, pcol = divmod(panel, layout.ncol)
        row, col = prow // axes.ny, pcol // axes.nx
        xi, yj = axes.axes(panel)
        parts = [
            _label(spec[role], levels[role][i])
            for role, i in (("row", row), ("col", col))
            if spec[role] is not None
        ]
        if several:
            parts.append(f"{spec['y'][yj]} × {spec['x'][xi]}")
        if not parts:
            continue
        lo, hi = layout.x_domain(pcol)
        titles.append(
            {
                "text": " / ".join(parts),
                "x": (lo + hi) / 2,
                "y": layout.y_domain(prow)[1],
                "yanchor": "bottom",
                "xref": "paper",
                "yref": "paper",
                "showarrow": False,
                "font": {"size": 11},
            }
        )
    return titles


def _facet_labels(
    spec: dict, levels: dict, layout: GridLayout, axes: AxisGrid
) -> list[dict]:
    """Return the facet labels above the grid and right of it, each over its panels."""
    labels = []
    if spec["col"] is not None:
        for col, level in enumerate(levels["col"]):
            lo = layout.x_domain(col * axes.nx)[0]
            hi = layout.x_domain(col * axes.nx + axes.nx - 1)[1]
            labels.append(
                {
                    "text": _label(spec["col"], level),
                    "x": (lo + hi) / 2,
                    "y": 1,
                    "yanchor": "bottom",
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                }
            )
    if spec["row"] is not None:
        for row, level in enumerate(levels["row"]):
            lo = layout.y_domain(row * axes.ny + axes.ny - 1)[0]
            hi = layout.y_domain(row * axes.ny)[1]
            labels.append(
                {
                    "text": _label(spec["row"], level),
                    "x": 1,
                    "y": (lo + hi) / 2,
                    "xanchor": "left",
                    "xshift": 4,
                    "textangle": 90,
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                }
            )
    return labels


def build_figure(manifest: dict) -> dict:
    """Return the figure of a plot task and what the page needs to draw its images.

    The figure holds the axes of every panel, each kept by an empty scatter
    trace (plotly leaves out the axes of a subplot without traces). The axes
    of the panels of one x column match, and so do those of one y column.

    Parameters
    ----------
    manifest : dict
        Manifest of the plot task.

    Returns
    -------
    dict
        ``{"figure": {"data", "layout"}, "meta": {...}}``; the meta holds the
        axes and the axis columns (``x``, ``y``: their indices) of each panel,
        the axes that hold the range of each x and y column (``x_axes``,
        ``y_axes``), the bin grid, the data range of each column, where each
        series' PNG lies in the images file (`ddviz.manifest.IMAGES`; its
        panels are tiles, ``ncol`` to a row, as `ddviz.raster.atlas`) and
        whether the grid scrolls.
    """
    spec = manifest["spec"]
    grid = manifest["grid"]
    layout = GridLayout(**manifest["layout"])
    axes = AxisGrid(**manifest["axes"])
    x_ranges, y_ranges = manifest["x_ranges"], manifest["y_ranges"]
    levels = manifest["levels"]
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
    for panel in range(layout.nrow * layout.ncol):
        prow, pcol = divmod(panel, layout.ncol)
        xi, yj = axes.axes(panel)
        suffix = _axis_suffix(panel)
        x_axis, y_axis = f"x{suffix}", f"y{suffix}"
        fig_layout[f"xaxis{suffix}"] = {
            "domain": layout.x_domain(pcol),
            "anchor": y_axis,
            "range": list(x_ranges[xi]),
            "showticklabels": layout.scroll or prow == layout.nrow - 1,
            "zeroline": False,
            **_FRAME,
            **({"matches": x_axes[xi]} if x_axis != x_axes[xi] else {}),
        }
        fig_layout[f"yaxis{suffix}"] = {
            "domain": layout.y_domain(prow),
            "anchor": x_axis,
            "range": list(y_ranges[yj]),
            "showticklabels": layout.scroll or pcol == 0,
            "zeroline": False,
            **_FRAME,
            **({"matches": y_axes[yj]} if y_axis != y_axes[yj] else {}),
        }
        panels.append({"xaxis": x_axis, "yaxis": y_axis, "x": xi, "y": yj})
    if layout.scroll:
        fig_layout["annotations"] += _panel_titles(spec, levels, layout, axes)
    else:
        fig_layout["annotations"] += _facet_labels(spec, levels, layout, axes)
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
        "x_columns": spec["x"],
        "y_columns": spec["y"],
        "x_axes": x_axes,
        "y_axes": y_axes,
        "grid": grid,
        "x_ranges": [list(r) for r in x_ranges],
        "y_ranges": [list(r) for r in y_ranges],
        "series": [str(v) for v in levels["color"]],
        "colors": manifest["colors"],
        "images": manifest["images"],
        "ncol": layout.ncol,
        "rows": manifest["rows"],
        "scroll": layout.scroll,
    }
    return {"figure": {"data": data, "layout": fig_layout}, "meta": meta}
