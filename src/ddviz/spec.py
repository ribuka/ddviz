"""Plot request passed from the UI server to a worker process."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PlotSpec:
    """What a worker aggregates for one scatter plot.

    Parameters
    ----------
    files : dict of str to str
        Parquet file to read each column of the plot from: a file of the
        column cache, or the source itself (`ddviz.scan.scan_columns`).
    x, y : str
        Columns on the x and y axes.
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
    x_range, y_range : list of float or None
        Zoomed view to aggregate: the bins cover exactly these data ranges
        and rows outside them are left out. None for the overview, whose
        bins cover the padded data ranges.
    levels : dict or None
        Levels of the overview (`ddviz.aggregate.Aggregation.levels`), given
        with a view so that its panels and series stay those of the overview
        and the levels need no pass over the data.

    Raises
    ------
    ValueError
        When only some of `x_range`, `y_range` and `levels` are given.
    """

    files: dict[str, str]
    x: str
    y: str
    color: str | None
    row: str | None
    col: str | None
    width: int
    height: int
    hover: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    x_range: list[float] | None = None
    y_range: list[float] | None = None
    levels: dict[str, list] | None = None

    def __post_init__(self) -> None:
        """Check that the view fields are all given or all None."""
        view = (self.x_range, self.y_range, self.levels)
        if any(v is None for v in view) and any(v is not None for v in view):
            raise ValueError("x_range, y_range and levels go together")

    @property
    def is_view(self) -> bool:
        """Whether the spec aggregates a zoomed view rather than the overview."""
        return self.levels is not None

    def to_dict(self) -> dict:
        """Return the spec as a JSON-ready dict.

        Returns
        -------
        dict
            The fields of the spec.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PlotSpec:
        """Build a spec from the dict made by `to_dict`.

        Parameters
        ----------
        data : dict
            The fields of the spec.

        Returns
        -------
        PlotSpec
            The spec.
        """
        return cls(**data)
