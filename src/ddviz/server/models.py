"""Bodies of the server's POST requests."""

from __future__ import annotations

from pydantic import BaseModel


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``: the graph (`ddviz.server.encoding.Encoding.to_dict`) and the plot area size."""

    encoding: dict
    width: int
    height: int
    filters: list[dict] = []
    color_bins: dict | None = None
    wrap_cols: int | None = None
    smooth: dict | None = None
    shape_size: int | None = None
    shape_sizes: dict[str, object] | None = None
    level_shapes: dict[str, object] | None = None


class SizeRequest(BaseModel):
    """Body of ``POST /api/overview``: the size of the plot area in pixels and the local filter."""

    width: int
    height: int
    filters: list[dict] = []


class SelectionRequest(BaseModel):
    """Body of ``POST /api/selection``.

    The box drawn on a panel of the drawn result `task`; without a panel,
    the current selection again, for a new result of the same plot.
    """

    task: int
    panel: int | None = None
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None


class ViewRequest(SizeRequest):
    """Body of ``POST /api/view``: the data range of each x and y column of the zoomed view and the plot area size."""

    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
