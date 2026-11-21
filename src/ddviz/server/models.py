"""Bodies of the server's POST requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from ddviz.shared.layout import MARGIN_BOTTOM, MARGIN_LEFT


class ShowNullRows(BaseModel):
    """Whether the Color, the Symbol, the Group Y (``row``), the Group X (``col``) and the Wrap draw their rows with a null or NaN value (`ddviz.shared.missing`); each is true when left out."""

    model_config = ConfigDict(extra="forbid")

    color: StrictBool = True
    symbol: StrictBool = True
    row: StrictBool = True
    col: StrictBool = True
    wrap: StrictBool = True


class PlotRequest(BaseModel):
    """Body of ``POST /api/plot``: the graph (`ddviz.server.encoding.Encoding.to_dict`) and the plot area size.

    ``margin_left`` is the left margin the page asks for, for the y tick
    labels it measured (`ddviz.shared.layout.left_margin`), and
    ``margin_bottom`` the bottom margin, for the x tick labels at an angle
    set (`ddviz.shared.layout.bottom_margin`). ``keep_unfiltered_color_levels``
    keeps the levels of a categorical color column over every row
    (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_color_levels`),
    ``keep_unfiltered_symbol_levels`` those of a categorical symbol column
    (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_symbol_levels`), and
    ``keep_unfiltered_axis_levels`` those of the categorical x and y columns
    it names, kept as sent for `ddviz.server.plotoptions.parse_keep_axis_levels`
    to check
    (`ddviz.shared.scatter.ScatterSpec.keep_unfiltered_axis_levels`).
    ``wrap_cols``, ``shape_size`` and ``line_width`` are kept as sent, for
    `ddviz.server.plotoptions` to take JSON integers only, and
    ``line_aggregation`` for it to give the reason of a wrong one.
    ``color_scale`` is the color scale of a numeric color column the page
    keeps under the lock of the axes (`ddviz.server.plotoptions.parse_color_scale`),
    kept as sent for it to check; null for that of the filter. ``cuts``
    are so the cuts of the numeric symbol, row and col columns, by role
    (`ddviz.server.plotoptions.parse_cuts`). ``ref_stats`` are the
    statistics of the reference lines of each column, kept as sent
    (`ddviz.server.plotoptions.parse_ref_stats`).
    """

    encoding: dict
    width: int
    height: int
    margin_left: int = MARGIN_LEFT
    margin_bottom: int = MARGIN_BOTTOM
    filters: list[dict] = []
    color_bins: dict | None = None
    wrap_cols: object = None
    smooth: dict | None = None
    shape_size: object = None
    line_width: object = None
    line_aggregation: object = None
    shape_sizes: dict[str, object] | None = None
    level_shapes: dict[str, object] | None = None
    show_null_rows: ShowNullRows = ShowNullRows()
    axis_scales: object = None
    keep_unfiltered_color_levels: StrictBool = False
    keep_unfiltered_symbol_levels: StrictBool = False
    keep_unfiltered_axis_levels: object = []
    color_scale: object = None
    cuts: object = None
    ref_stats: object = {}


class PlotDataRequest(BaseModel):
    """Body of ``POST /api/plot-data/{task}``: the file's format, its rows and columns (`ddviz.shared.tasks.PlotDataTask`), and the page's token for the progress."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["csv", "parquet"]
    rows: Literal["drawn", "filtered"]
    columns: Literal["drawn", "all"]
    export: str


class SelectionDataRequest(BaseModel):
    """Body of ``POST /api/plot-data/selection``: the file's format and columns, and the page's token for the progress (`PlotDataRequest`); the rows are the selected ones."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["csv", "parquet"]
    columns: Literal["drawn", "all"]
    export: str


class ExportCancel(BaseModel):
    """Body of ``POST /api/plot-data/cancel``: the page's token of the export to cancel."""

    model_config = ConfigDict(extra="forbid")

    export: str


class SizeRequest(BaseModel):
    """Body of ``POST /api/overview``: the size of the plot area in pixels, the left and bottom margins asked for, the local filter, the color scale and the cuts kept (`PlotRequest`)."""

    width: int
    height: int
    margin_left: int = MARGIN_LEFT
    margin_bottom: int = MARGIN_BOTTOM
    filters: list[dict] = []
    color_scale: object = None
    cuts: object = None


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
    """Body of ``POST /api/view``: the data range of each x and y column of the zoomed view and the plot area size.

    A null range leaves its column at the automatic range of the request's
    filter (`ddviz.compute.aggregate.Aggregation.x_auto`). ``range_levels``
    gives, for a categorical axis column with a range, the levels its range
    is a position among, kept as sent for the server to check
    (`ddviz.server.plotoptions.parse_range_levels`); null for none.
    """

    x_ranges: list[tuple[float, float] | None]
    y_ranges: list[tuple[float, float] | None]
    range_levels: object = None


class DrawFileRequest(BaseModel):
    """Body of ``POST /api/draw-file``: the drawing settings to save and the names of the columns they refer to."""

    model_config = ConfigDict(extra="forbid")

    settings: dict
    columns: list[str]


class ColumnKindsRequest(BaseModel):
    """Body of ``POST /api/column-kinds``: the names of the columns whose kinds the page asks for."""

    model_config = ConfigDict(extra="forbid")

    names: list[str]


class JoinSourceRequest(BaseModel):
    """Body of ``POST /api/join/source``: the joined table's input, as Load takes one."""

    model_config = ConfigDict(extra="forbid")

    paths: list[str]
    recursive: StrictBool = False


class JoinKey(BaseModel):
    """A pair of keys of a join: a column of the input and one of the joined table."""

    model_config = ConfigDict(extra="forbid")

    left: str
    right: str


class JoinRequest(BaseModel):
    """Body of ``POST /api/join``: ``"key"`` with the pairs of keys, or ``"rows"`` without keys, and the columns to add (`ddviz.server.source.Source.join`).

    ``columns`` null adds all the columns of the joined table but its keys,
    with ``same_names`` deciding on those named like the input's
    (``"rename"``, ``"skip_equal"`` or ``"skip"``); a list adds those
    columns alone.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    keys: list[JoinKey] = []
    columns: list[str] | None = None
    same_names: str = "rename"
