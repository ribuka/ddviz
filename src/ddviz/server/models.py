"""Bodies of the server's POST requests."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictBool

from ddviz.shared.layout import MARGIN_LEFT


class ShowNullRows(BaseModel):
    """Whether the Color and the Overlay draw their rows with a null or NaN value (`ddviz.shared.missing`); each is true when left out."""

    model_config = ConfigDict(extra="forbid")

    color: StrictBool = True
    overlay: StrictBool = True


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``: the graph (`ddviz.server.encoding.Encoding.to_dict`) and the plot area size.

    ``margin_left`` is the left margin the page asks for, for the y tick
    labels it measured (`ddviz.shared.layout.left_margin`).
    """

    encoding: dict
    width: int
    height: int
    margin_left: int = MARGIN_LEFT
    filters: list[dict] = []
    color_bins: dict | None = None
    wrap_cols: int | None = None
    smooth: dict | None = None
    shape_size: int | None = None
    shape_sizes: dict[str, object] | None = None
    level_shapes: dict[str, object] | None = None
    show_null_rows: ShowNullRows = ShowNullRows()
    axis_scales: object = None


class SizeRequest(BaseModel):
    """Body of ``POST /api/overview``: the size of the plot area in pixels, the left margin asked for (`PlotRequest`) and the local filter."""

    width: int
    height: int
    margin_left: int = MARGIN_LEFT
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
