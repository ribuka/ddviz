"""Scatter plot request passed from the UI server to a worker process."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
        Levels of the overview (`ddviz.aggregate.Aggregation.levels`), so that
        the panels and series stay those of the overview and the levels need
        no pass over the data.
    """

    x_ranges: list[list[float]]
    y_ranges: list[list[float]]
    levels: dict[str, list]


@dataclass(frozen=True)
class Selection:
    """Rows chosen by a box drawn on one panel of a scatter plot.

    The rows are those of the panel's facet cell whose x and y columns fall
    in the box; every panel highlights them (`ddviz.aggregate.aggregate`
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
class ScatterSpec:
    """What a worker aggregates for one scatter plot.

    Made from the graph's `ddviz.encoding.Encoding` by `ddviz.plan`; it
    holds only the roles that are drawn.

    Parameters
    ----------
    files : dict of str to str
        Parquet file to read each column of the plot from: a file of the
        column cache, or the source itself (`ddviz.scan.scan_columns`).
    x, y : list of str
        Columns on the x and y axes, at least one each. Every pair of an x and
        a y column is a panel of each facet cell: the x columns side by side,
        the y columns stacked from the top (`ddviz.layout.AxisGrid`).
    color : str or None
        Column whose levels make the series, or None for a single series.
    row, col : str or None
        Columns whose levels make the facet rows and columns.
    width, height : int
        Figure size in pixels. The worker splits it into panels by
        `ddviz.layout.grid_layout` once it knows the facet levels; one bin is
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
    """

    files: dict[str, str]
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
            }
        )
