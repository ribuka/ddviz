"""Scatter plot request passed from the UI server to a worker process."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ddviz.shared.layout import MARGIN_LEFT
from ddviz.shared.missing import MISSING, MISSING_SHAPE
from ddviz.shared.shapes import default_shape

# Default of the most levels a color, overlay, row or col column may have
# (`ScatterSpec.max_levels`).
MAX_LEVELS = 100
# Default of the most levels a categorical x or y column may have
# (`ScatterSpec.max_axis_levels`). A million levels drew in about 8s at a
# peak of 1GB in the worker; more were not measured (`docs/spec.md`,
# "カテゴリの軸の水準の上限").
MAX_AXIS_LEVELS = 1_000_000
# Default size in pixels of the markers (`ScatterSpec.shape_size`): the
# shapes of the overlay levels, and the filled circles of the points without
# an overlay.
SHAPE_SIZE = 7
POINT_SIZE = 5
# The x column of a graph whose X is empty: a categorical column of one
# level, so that every row lies in one band. It is no column of the data;
# the scan makes it (`ddviz.compute.scan.scan_columns`).
ONE_BAND = "\x00one band"


@dataclass(frozen=True)
class Binning:
    """How a numeric column on the color, overlay, row or col role becomes levels of intervals (`ddviz.compute.cuts`).

    Parameters
    ----------
    n : int
        Number of intervals.
    by : str
        ``"rows"`` for intervals of about the same number of rows (cut at
        the quantiles), ``"values"`` for intervals of the same width.
    values_up_to : int
        A column with at most this many values gets one level per value
        instead; 0 never does.
    """

    n: int
    by: str = "rows"
    values_up_to: int = 0


@dataclass(frozen=True)
class Boxes:
    """Box plots of a pair of axis columns: a categorical x and a numeric y (`ddviz.compute.boxes`).

    Parameters
    ----------
    x, y : str
        The pair's x and y columns.
    stats : list of list of float
        One box per facet cell, x level and series with rows:
        ``[row, col, level, series, n, low, q1, median, q3, high]``, where
        ``row`` and ``col`` index the drawn facet levels
        (`ddviz.compute.aggregate.Aggregation.levels`), ``level`` the x
        level, ``n`` counts the rows, and ``low`` and ``high`` are the ends
        of the whiskers.
    """

    x: str
    y: str
    stats: list[list[float]]


@dataclass(frozen=True)
class Smoothing:
    """How the smoothing lines are fitted (`ddviz.compute.smooth`).

    Parameters
    ----------
    method : str
        ``"gcv"`` (a smoothing spline whose penalty generalized
        cross-validation picks), ``"csaps"`` (a smoothing spline of the
        parameter ``p``) or ``"lowess"``.
    p : float or None
        For csaps, the smoothing parameter from 0 (a straight line) to 1
        (through the points), with x scaled to [0, 1]; None picks it from
        the data, as the ``csaps`` package does.
    frac : float
        For lowess, the part of the rows each local fit uses, above 0 and
        at most 1.
    """

    method: str = "gcv"
    p: float | None = None
    frac: float = 2 / 3


@dataclass(frozen=True)
class Smooths:
    """Smoothing lines of a pair of numeric axis columns (`ddviz.compute.smooth`).

    Parameters
    ----------
    x, y : str
        The pair's x and y columns.
    lines : list of list
        One line per facet cell and series with rows:
        ``[row, col, series, xs, ys]``, where ``row`` and ``col`` index the
        drawn facet levels, and ``xs`` and ``ys`` are the points of the
        line, increasing in x.
    """

    x: str
    y: str
    lines: list[list]


@dataclass(frozen=True)
class View:
    """Zoomed view of a scatter plot.

    Parameters
    ----------
    x_ranges, y_ranges : list of list of float
        Data range of each x and each y column to aggregate: the bins of a
        panel cover exactly the ranges of its columns and rows outside them
        are left out of it. A column on a log axis has the positions of
        its range: the log10 of the values (`ddviz.shared.axisscale`).
    levels : dict
        Levels of the overview over every row
        (`ddviz.compute.aggregate.Aggregation.all_levels`), so that the series stay
        those of the overview and the levels need no pass over the data.
    facets : dict or None
        Levels of the ``"row"`` and ``"col"`` roles drawn as panels
        (`ddviz.compute.aggregate.Aggregation.levels`), known from a result with the
        same local filter; None to find them again from the filter.
    cuts : dict
        Cuts of each role in ``binned`` of the spec (`ddviz.compute.cuts`), from the
        overview.
    color_range : list of float or None
        Finite minimum and maximum of a gradient's color column, from the
        overview.
    axis_levels : dict of str to list of str
        Levels of each categorical axis column, from the overview.
    boxes : list of Boxes
        Box plots of each pair, from a result with the same local filter; a
        pair without them has them found again.
    smooths : list of Smooths
        Smoothing lines of each pair, from a result with the same local
        filter; a pair without them has them fitted again.
    """

    x_ranges: list[list[float]]
    y_ranges: list[list[float]]
    levels: dict[str, list]
    facets: dict[str, list] | None = None
    cuts: dict[str, dict] = field(default_factory=dict)
    color_range: list[float] | None = None
    axis_levels: dict[str, list[str]] = field(default_factory=dict)
    boxes: list[Boxes] = field(default_factory=list)
    smooths: list[Smooths] = field(default_factory=list)


@dataclass(frozen=True)
class Selection:
    """Rows chosen by a box drawn on one panel of a scatter plot.

    The rows are those of the panel's facet cell whose x and y columns fall
    in the box; every panel highlights them (`ddviz.compute.aggregate.aggregate`
    with ``selection_only``), and the table lists them.

    Parameters
    ----------
    x, y : str
        The panel's x and y columns.
    x_range, y_range : list of float
        The box along them, as positions (on a log axis, the log10 of the
        values: `ddviz.shared.axisscale`).
    row, col : str or None
        The panel's facet levels (as text), or None without a row or col
        column.
    """

    x: str
    y: str
    x_range: list[float]
    y_range: list[float]
    row: str | None = None
    col: str | None = None


@dataclass(frozen=True)
class Filter:
    """Condition of the local filter on one column (`ddviz.compute.rowfilter`).

    A row passes when its value of the column is in the range (a numeric
    column), or, for a categorical column compared as text, is among the
    levels or contains the text; a row with a null value never passes.

    Parameters
    ----------
    column : str
        The column.
    range : list of float or None
        Bounds, both included, for a numeric column.
    levels : list of str or None
        Levels kept, for a categorical column.
    contains : str or None
        Text the kept values contain, matched literally and case-sensitively,
        for a categorical column with too many levels to tick
        (`ddviz.compute.summary.MAX_FILTER_LEVELS`).
    """

    column: str
    range: list[float] | None = None
    levels: list[str] | None = None
    contains: str | None = None


@dataclass(frozen=True)
class ScatterSpec:
    """What a worker aggregates for one scatter plot.

    Made from the graph's `ddviz.server.encoding.Encoding` by `ddviz.server.plan`; it
    holds only the roles that are drawn.

    Parameters
    ----------
    files : dict of str to list of str
        Parquet files holding each column of the plot, read one after another:
        its parts in the column cache (`ddviz.compute.scan.scan_columns`);
        none for `ONE_BAND`.
    x, y : list of str
        Columns on the x and y axes, at least one each. Every pair of an x and
        a y column is a panel of each facet cell: the x columns side by side,
        the y columns stacked from the top (`ddviz.shared.layout.AxisGrid`).
        A column in ``categorical`` is drawn by its levels, in bands
        (`ddviz.compute.bands`); the x column `ONE_BAND` puts every row in
        one band.
    color : str or None
        Column whose levels make the series' colors, or None for a single
        color.
    row, col : str or None
        Columns whose levels make the facet rows and columns.
    width, height : int
        Figure size in pixels. The worker splits it into panels by
        `ddviz.shared.layout.grid_layout` once it knows the facet levels; one bin is
        one pixel of a panel.
    wrap : bool
        Whether the col levels wrap into rows of panels (``facet_col_wrap``
        of plotly express; `ddviz.shared.layout.AxisGrid`); row is then None
        and x and y have one column each.
    wrap_cols : int or None
        Wrapped panels to a row; None to make the panels closest to square
        (`ddviz.shared.layout.wrap_columns`).
    hover : list of str
        Columns whose values the hover shows for the representative rows.
    colors : list of str
        Series colors as ``#rrggbb``, cycled over the series.
    view : View or None
        Zoomed view to aggregate, or None for the overview, whose bins cover
        the padded data range of each column.
    selection : Selection or None
        Rows chosen by a box, aggregated as a layer of their own.
    binned : dict of str to Binning
        Roles (``"color"``, ``"overlay"``, ``"row"``, ``"col"``) whose numeric column is cut
        into intervals, each a level (`ddviz.compute.cuts`).
    gradient : bool
        Whether the color column is numeric and colors each pixel by the
        value of its representative row, in a single series.
    filters : list of Filter
        Conditions of the local filter, all of which a row must meet to be
        drawn, hovered, selected or listed. They leave the series and the
        overview's ranges as they are without them, and drop the facet
        panels left without rows (`ddviz.compute.aggregate.aggregate`).
    max_levels : int
        Most levels a color, overlay, row or col column may have; more are refused
        before binning. A numeric column on these roles has about one level
        per row: its masks would not fit in memory.
    max_axis_levels : int
        Most levels a categorical x or y column may have; more are refused
        before binning. A column also on a role of `max_levels` has to meet
        both.
    hover_bytes : int or None
        Most bytes the result's hover files may take
        (`ddviz.compute.hoverfit`); None for no limit.
    categorical : list of str
        Columns of x and y that are not numeric: each of their levels is a
        band of the axis, up to ``max_axis_levels`` levels.
    points : bool
        Whether the points of every row are drawn. A panel that cannot have
        box plots draws them anyway.
    box : bool
        Whether the panels of a categorical x and a numeric y have box plots
        (`box_pairs`); without points, such a panel draws only the outliers
        as points (`ddviz.compute.boxes`).
    smooth : Smoothing or None
        How the panels of a numeric x and a numeric y fit smoothing lines
        (`smooth_pairs`), or None for none; without points, such a panel
        draws only the lines.
    overlay : str or None
        Column whose levels draw the points in marker shapes
        (`ddviz.shared.shapes`), or None for filled circles. The series are
        then the pairs of a color level and an overlay level: series ``s``
        has color level ``s // n`` and overlay level ``s % n``, where ``n``
        counts the overlay levels.
    shape_size : int
        Width and height in pixels of the markers, odd: the overlay's
        shapes, or the circles without an overlay
        (`ddviz.shared.shapes.marker`).
    shape_sizes : dict of str to int
        Size of the shapes of single overlay levels, by the level's name
        (`marker_sizes`), in place of `shape_size`.
    level_shapes : dict of str to str
        Shape of single overlay levels, by the level's name
        (`marker_shapes`), one of `ddviz.shared.shapes.SHAPES`, in place of
        the shape the level's place takes.
    temporal : dict of str to str
        The kind of each temporal column read (`ddviz.shared.temporal.KINDS`).
        Such a column is numeric: it is read as numbers
        (`ddviz.compute.temporal`), and its intervals are named and its axis
        drawn as dates, times or seconds.
    null_roles : list of str
        Roles (``"color"``, ``"overlay"``) whose rows with a null or NaN
        value are drawn as the role's missing level
        (`ddviz.shared.missing.MISSING`), the last of its levels, when the
        column has such rows; the other roles' rows, and those of a role not
        listed, are left out. An infinite value is always left out.
    log_x, log_y : list of str
        The x and the y columns on log10 axes (`ddviz.shared.axisscale`):
        the ranges of their columns in the view, and the bins along them,
        are of the log10 of their values, and a panel of such a column
        draws only its rows with a positive finite value there. Box plots
        and smoothing lines are found from those rows' values themselves.
    margin_left : int
        Left margin of the figure in pixels, for the y tick labels the page
        measured (`ddviz.shared.layout.left_margin`): the panels have the
        width left of `width`.
    """

    files: dict[str, list[str]]
    x: list[str]
    y: list[str]
    color: str | None
    row: str | None
    col: str | None
    width: int
    height: int
    hover: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    view: View | None = None
    selection: Selection | None = None
    binned: dict[str, Binning] = field(default_factory=dict)
    gradient: bool = False
    filters: list[Filter] = field(default_factory=list)
    max_levels: int = MAX_LEVELS
    max_axis_levels: int = MAX_AXIS_LEVELS
    hover_bytes: int | None = None
    wrap: bool = False
    wrap_cols: int | None = None
    categorical: list[str] = field(default_factory=list)
    points: bool = True
    box: bool = False
    smooth: Smoothing | None = None
    overlay: str | None = None
    shape_size: int = POINT_SIZE
    shape_sizes: dict[str, int] = field(default_factory=dict)
    level_shapes: dict[str, str] = field(default_factory=dict)
    temporal: dict[str, str] = field(default_factory=dict)
    null_roles: list[str] = field(default_factory=list)
    log_x: list[str] = field(default_factory=list)
    log_y: list[str] = field(default_factory=list)
    margin_left: int = MARGIN_LEFT

    def box_pairs(self) -> set[tuple[str, str]]:
        """Return the pairs of axis columns whose panels have box plots.

        Returns
        -------
        set of tuple of str
            Each ``(x, y)`` with a categorical x and a numeric y, when the
            spec draws box plots; none otherwise.
        """
        if not self.box:
            return set()
        categorical = set(self.categorical)
        return {
            (x, y)
            for x in self.x
            for y in self.y
            if x in categorical and y not in categorical
        }

    def smooth_pairs(self) -> set[tuple[str, str]]:
        """Return the pairs of axis columns whose panels have smoothing lines.

        Returns
        -------
        set of tuple of str
            Each ``(x, y)`` with a numeric x and a numeric y, when the spec
            draws smoothing lines; none otherwise.
        """
        if self.smooth is None:
            return set()
        categorical = set(self.categorical)
        return {
            (x, y)
            for x in self.x
            for y in self.y
            if x not in categorical and y not in categorical
        }

    def draws_points(self, x: str, y: str) -> bool:
        """Return whether the panels of a pair draw the points of every row, not only the outliers or none.

        Parameters
        ----------
        x, y : str
            The pair's columns.

        Returns
        -------
        bool
            True with the points element, or for a pair with neither box
            plots nor smoothing lines.
        """
        return self.points or (x, y) not in self.box_pairs() | self.smooth_pairs()

    def marker_sizes(self, overlay_levels: list) -> list[int]:
        """Return the size of the markers of each overlay level.

        Parameters
        ----------
        overlay_levels : list
            The overlay's levels drawn.

        Returns
        -------
        list of int
            The size of each level's shapes, from `shape_sizes` by the
            level's name or else `shape_size`; series ``s`` takes item
            ``s % len``. Without an overlay (or levels), the one size of the
            circles.
        """
        if self.overlay is None or not overlay_levels:
            return [self.shape_size]
        return [self.shape_sizes.get(str(v), self.shape_size) for v in overlay_levels]

    def marker_shapes(self, overlay_levels: list) -> list[str | None]:
        """Return the shape of the markers of each overlay level.

        Parameters
        ----------
        overlay_levels : list
            The overlay's levels drawn.

        Returns
        -------
        list of str or None
            The shape of each level (`ddviz.shared.shapes.SHAPES`), from
            `level_shapes` by the level's name or else the one of its place
            (`ddviz.shared.shapes.default_shape`), or the x for the missing
            level (`ddviz.shared.missing.MISSING_SHAPE`); series ``s`` takes
            item ``s % len``. Without an overlay (or levels), ``[None]``: the
            filled circles.
        """
        if self.overlay is None or not overlay_levels:
            return [None]
        return [
            self.level_shapes.get(
                str(v), MISSING_SHAPE if v == MISSING else default_shape(i)
            )
            for i, v in enumerate(overlay_levels)
        ]

    def to_dict(self) -> dict:
        """Return the spec as a JSON-ready dict.

        Returns
        -------
        dict
            The fields of the spec; the view as a dict or None.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ScatterSpec:
        """Build a spec from the dict made by `to_dict`.

        Parameters
        ----------
        data : dict
            The fields of the spec.

        Returns
        -------
        ScatterSpec
            The spec.
        """
        view = data.get("view")
        selection = data.get("selection")
        smooth = data.get("smooth")
        return cls(
            **{
                **data,
                "view": _view(view) if view is not None else None,
                "selection": Selection(**selection) if selection is not None else None,
                "smooth": Smoothing(**smooth) if smooth is not None else None,
                "filters": [Filter(**f) for f in data.get("filters", [])],
                "binned": {
                    role: Binning(**b) for role, b in data.get("binned", {}).items()
                },
            }
        )


def _view(data: dict) -> View:
    """Build a view from its dict, as `ScatterSpec.to_dict` makes it."""
    return View(
        **{
            **data,
            "boxes": [Boxes(**b) for b in data.get("boxes", [])],
            "smooths": [Smooths(**s) for s in data.get("smooths", [])],
        }
    )
