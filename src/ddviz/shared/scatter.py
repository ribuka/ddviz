"""Scatter plot request passed from the UI server to a worker process."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Default of the most levels a color, row or col column may have
# (`ScatterSpec.max_levels`).
MAX_LEVELS = 50


@dataclass(frozen=True)
class Binning:
    """How a numeric column on the color, row or col role becomes levels of intervals (`ddviz.compute.cuts`).

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
class View:
    """Zoomed view of a scatter plot.

    Parameters
    ----------
    x_ranges, y_ranges : list of list of float
        Data range of each x and each y column to aggregate: the bins of a
        panel cover exactly the ranges of its columns and rows outside them
        are left out of it.
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
    """

    x_ranges: list[list[float]]
    y_ranges: list[list[float]]
    levels: dict[str, list]
    facets: dict[str, list] | None = None
    cuts: dict[str, dict] = field(default_factory=dict)
    color_range: list[float] | None = None


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
        The box along them.
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
    column) or among the levels (a categorical column, compared as text);
    a row with a null value never passes.

    Parameters
    ----------
    column : str
        The column.
    range : list of float or None
        Bounds, both included, for a numeric column.
    levels : list of str or None
        Levels kept, for a categorical column.
    """

    column: str
    range: list[float] | None = None
    levels: list[str] | None = None


@dataclass(frozen=True)
class ScatterSpec:
    """What a worker aggregates for one scatter plot.

    Made from the graph's `ddviz.server.encoding.Encoding` by `ddviz.server.plan`; it
    holds only the roles that are drawn.

    Parameters
    ----------
    files : dict of str to list of str
        Parquet files holding each column of the plot, read one after another:
        its parts in the column cache (`ddviz.compute.scan.scan_columns`).
    x, y : list of str
        Columns on the x and y axes, at least one each. Every pair of an x and
        a y column is a panel of each facet cell: the x columns side by side,
        the y columns stacked from the top (`ddviz.shared.layout.AxisGrid`).
    color : str or None
        Column whose levels make the series, or None for a single series.
    row, col : str or None
        Columns whose levels make the facet rows and columns.
    width, height : int
        Figure size in pixels. The worker splits it into panels by
        `ddviz.shared.layout.grid_layout` once it knows the facet levels; one bin is
        one pixel of a panel.
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
        Roles (``"color"``, ``"row"``, ``"col"``) whose numeric column is cut
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
        Most levels a color, row or col column may have; more are refused
        before binning. A numeric column on these roles has about one level
        per row: its masks would not fit in memory.
    hover_bytes : int or None
        Most bytes the result's hover files may take
        (`ddviz.compute.hoverfit`); None for no limit.
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
    hover_bytes: int | None = None

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
        return cls(
            **{
                **data,
                "view": View(**view) if view is not None else None,
                "selection": Selection(**selection) if selection is not None else None,
                "filters": [Filter(**f) for f in data.get("filters", [])],
                "binned": {
                    role: Binning(**b) for role, b in data.get("binned", {}).items()
                },
            }
        )
