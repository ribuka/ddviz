"""Bodies of the server's POST requests."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictBool

from ddviz.shared.layout import MARGIN_BOTTOM, MARGIN_LEFT


class ShowNullRows(BaseModel):
    """Whether the Color and the Symbol draw their rows with a null or NaN value (`ddviz.shared.missing`); each is true when left out."""

    model_config = ConfigDict(extra="forbid")

    color: StrictBool = True
    symbol: StrictBool = True


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``: the graph (`ddviz.server.encoding.Encoding.to_dict`) and the plot area size.

    ``margin_left`` is the left margin the page asks for, for the y tick
    labels it measured (`ddviz.shared.layout.left_margin`), and
    ``margin_bottom`` the bottom margin, for the x tick labels at an angle
    set (`ddviz.shared.layout.bottom_margin`). ``keep_unfiltered_color_levels``
    keeps the levels of a categorical color column over every row
    (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_color_levels`).
    """

    encoding: dict
    width: int
    height: int
    margin_left: int = MARGIN_LEFT
    margin_bottom: int = MARGIN_BOTTOM
    filters: list[dict] = []
    color_bins: dict | None = None
    wrap_cols: int | None = None
    smooth: dict | None = None
    shape_size: int | None = None
    line_width: object = None
    shape_sizes: dict[str, object] | None = None
    level_shapes: dict[str, object] | None = None
    show_null_rows: ShowNullRows = ShowNullRows()
    axis_scales: object = None
    keep_unfiltered_color_levels: StrictBool = False


class SizeRequest(BaseModel):
    """Body of ``POST /api/overview``: the size of the plot area in pixels, the left and bottom margins asked for (`PlotRequest`) and the local filter."""

    width: int
    height: int
    margin_left: int = MARGIN_LEFT
    margin_bottom: int = MARGIN_BOTTOM
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
