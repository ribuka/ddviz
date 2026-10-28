"""Builds the plotly figure of a plot task: series image layers on a facet grid."""

from __future__ import annotations

from collections.abc import Callable

from ddviz.layout import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    GridLayout,
)

# Distance of the legend from the right edge of the plot area, in pixels,
# leaving room for the row labels.
_LEGEND_OFFSET = 28


def _axis_suffix(panel: int) -> str:
    """Return the plotly axis suffix of a panel: "" for the first, else its number."""
    return "" if panel == 0 else str(panel + 1)


def _label(column: str | None, level: object) -> str:
    """Return a facet label."""
    return f"{column} = {level}"


def _panel_titles(spec: dict, levels: dict, layout: GridLayout) -> list[dict]:
    """Return a facet title above each panel, for a grid that scrolls."""
    titles = []
    for row in range(layout.nrow):
        for col in range(layout.ncol):
            text = " / ".join(
                _label(spec[role], levels[role][i])
                for role, i in (("row", row), ("col", col))
                if spec[role] is not None
            )
            if not text:
                continue
            lo, hi = layout.x_domain(col)
            titles.append(
                {
                    "text": text,
                    "x": (lo + hi) / 2,
                    "y": layout.y_domain(row)[1],
                    "yanchor": "bottom",
                    "xref": "paper",
                    "yref": "paper",
                    "showarrow": False,
                    "font": {"size": 11},
                }
            )
    return titles


def build_figure(manifest: dict, image_source: Callable[[list[int]], str]) -> dict:
    """Return the figure of a plot task and what the page needs for hovering.

    Each series of each panel is an image trace; one empty scatter trace per
    series carries its legend item, in the same legend group, so a legend
    click fades the series' images.

    Parameters
    ----------
    manifest : dict
        Manifest of the plot task.
    image_source : callable
        Returns the ``source`` of an image trace (a data URI) from the offset
        and length of its PNG in the images file (`ddviz.manifest.IMAGES`).

    Returns
    -------
    dict
        ``{"figure": {"data", "layout"}, "meta": {...}}``; the meta holds the
        axes of each panel, the bin grid, the data ranges and whether the
        grid scrolls.
    """
    spec = manifest["spec"]
    grid = manifest["grid"]
    layout = GridLayout(**manifest["layout"])
    (x_lo, x_hi), (y_lo, y_hi) = manifest["x_range"], manifest["y_range"]
    dx = (x_hi - x_lo) / grid["width"]
    dy = (y_hi - y_lo) / grid["height"]
    levels = manifest["levels"]

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
        "showlegend": True,
        "legend": {
            "x": 1 + _LEGEND_OFFSET / (layout.width - MARGIN_LEFT - MARGIN_RIGHT),
            "xanchor": "left",
            "y": 1,
            "title": {"text": spec["color"] or ""},
        },
        "annotations": [],
    }
    panels = []
    for row in range(layout.nrow):
        for col in range(layout.ncol):
            panel = row * layout.ncol + col
            suffix = _axis_suffix(panel)
            fig_layout[f"xaxis{suffix}"] = {
                "domain": layout.x_domain(col),
                "anchor": f"y{suffix}",
                "range": [x_lo, x_hi],
                "showticklabels": layout.scroll or row == layout.nrow - 1,
                "zeroline": False,
                # Image traces otherwise make pixels square by shrinking the
                # domain, so a bin would no longer be a screen pixel.
                "scaleanchor": False,
                **({"matches": "x"} if panel else {}),
            }
            fig_layout[f"yaxis{suffix}"] = {
                "domain": layout.y_domain(row),
                "anchor": f"x{suffix}",
                "range": [y_lo, y_hi],
                "showticklabels": layout.scroll or col == 0,
                "zeroline": False,
                "scaleanchor": False,
                **({"matches": "y"} if panel else {}),
            }
            panels.append({"xaxis": f"x{suffix}", "yaxis": f"y{suffix}"})
    if layout.scroll:
        fig_layout["annotations"] += _panel_titles(spec, levels, layout)
    if spec["col"] is not None and not layout.scroll:
        for col, level in enumerate(levels["col"]):
            lo, hi = layout.x_domain(col)
            fig_layout["annotations"].append(
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
    if spec["row"] is not None and not layout.scroll:
        for row, level in enumerate(levels["row"]):
            lo, hi = layout.y_domain(row)
            fig_layout["annotations"].append(
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
    fig_layout["annotations"] += [
        {
            "text": spec["x"],
            "x": 0.5,
            "y": 0,
            "yshift": -36,
            "xref": "paper",
            "yref": "paper",
            "yanchor": "top",
            "showarrow": False,
        },
        {
            "text": spec["y"],
            "x": 0,
            "y": 0.5,
            "xshift": -46,
            "textangle": -90,
            "xref": "paper",
            "yref": "paper",
            "xanchor": "right",
            "showarrow": False,
        },
    ]

    data = []
    for series, color in enumerate(manifest["colors"]):
        group = f"s{series}"
        name = str(levels["color"][series]) if spec["color"] is not None else spec["y"]
        for panel, images in enumerate(manifest["images"]):
            if images[series] is None:
                continue
            data.append(
                {
                    "type": "image",
                    "source": image_source(images[series]),
                    "x0": x_lo + dx / 2,
                    "dx": dx,
                    "y0": y_lo + dy / 2,
                    "dy": dy,
                    "xaxis": panels[panel]["xaxis"],
                    "yaxis": panels[panel]["yaxis"],
                    "hoverinfo": "skip",
                    "legendgroup": group,
                    "name": name,
                }
            )
        data.append(
            {
                "type": "scatter",
                "mode": "markers",
                "x": [None],
                "y": [None],
                "name": name,
                "legendgroup": group,
                "marker": {"color": color, "size": 10},
                "hoverinfo": "skip",
            }
        )
    # plotly leaves out the axes of a subplot without traces, so a panel with
    # no rows in the view gets an empty trace.
    for panel, images in enumerate(manifest["images"]):
        if all(image is None for image in images):
            data.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": [],
                    "y": [],
                    "xaxis": panels[panel]["xaxis"],
                    "yaxis": panels[panel]["yaxis"],
                    "showlegend": False,
                    "hoverinfo": "skip",
                }
            )
    meta = {
        "panels": panels,
        "grid": grid,
        "x_range": [x_lo, x_hi],
        "y_range": [y_lo, y_hi],
        "series": [str(v) for v in levels["color"]],
        "colors": manifest["colors"],
        "rows": manifest["rows"],
        "scroll": layout.scroll,
    }
    return {"figure": {"data": data, "layout": fig_layout}, "meta": meta}
