"""Plot request passed from the UI server to a worker process."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PlotSpec:
    """What a worker aggregates for one scatter plot.

    Parameters
    ----------
    path : str
        Parquet file to read.
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
    """

    path: str
    x: str
    y: str
    color: str | None
    row: str | None
    col: str | None
    width: int
    height: int
    hover: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)

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
