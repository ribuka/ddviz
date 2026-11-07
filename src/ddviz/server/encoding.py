"""The graph as the user builds it by drag and drop: which columns take which roles."""

from __future__ import annotations

from dataclasses import dataclass

# Roles that hold a list of columns: the first is drawn on the axis, the
# others are the n-th axes.
AXES = ("x", "y")
# Roles that hold one column or none.
SINGLES = ("color", "overlay", "row", "col", "wrap")
ROLES = AXES + SINGLES
# Elements of a graph, which the icons above the figure toggle: points,
# box plots and smoothing lines.
ELEMENTS = ("points", "box", "smooth")


@dataclass(frozen=True)
class Encoding:
    """Columns placed on each role of a graph.

    A column may take several roles (for example color and col). The plan
    of a graph (`ddviz.server.plan`) turns them into what a worker draws.

    Parameters
    ----------
    x, y : tuple of str
        Columns on the x and y axes; those after the first are the n-th axes.
    color : str or None
        Column whose levels color the series.
    overlay : str or None
        Column whose levels draw the points in marker shapes, with or without
        a color column.
    row, col : str or None
        Columns whose levels make the facet rows and columns (Group Y and
        Group X).
    wrap : str or None
        Column whose levels make panels side by side that wrap into rows
        (``facet_col_wrap`` of plotly express); the plan refuses it beside
        row, col or the n-th axes (`ddviz.server.plan.scatter_spec`).
    elements : tuple of str
        Elements drawn, one or more of `ELEMENTS` in that order; several
        are drawn one over another.
    """

    x: tuple[str, ...] = ()
    y: tuple[str, ...] = ()
    color: str | None = None
    overlay: str | None = None
    row: str | None = None
    col: str | None = None
    wrap: str | None = None
    elements: tuple[str, ...] = ("points",)

    def columns(self) -> list[str]:
        """Return every placed column once, in role order.

        Returns
        -------
        list of str
            The columns.
        """
        placed = [*self.x, *self.y]
        placed += [getattr(self, r) for r in SINGLES if getattr(self, r) is not None]
        return list(dict.fromkeys(placed))

    def to_dict(self) -> dict:
        """Return the encoding as a JSON-ready dict.

        Returns
        -------
        dict
            Each role, and the elements; the axes and the elements as lists.
        """
        return {
            **{r: list(getattr(self, r)) for r in AXES},
            **{r: getattr(self, r) for r in SINGLES},
            "elements": list(self.elements),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Encoding:
        """Build an encoding from a dict like `to_dict`'s; missing roles are empty, missing elements are points.

        Parameters
        ----------
        data : dict
            Columns of each role.

        Returns
        -------
        Encoding
            The encoding.

        Raises
        ------
        ValueError
            For an unknown role, a role whose value has the wrong type, or
            elements that are not a non-empty list of `ELEMENTS`.
        """
        unknown = sorted(set(data) - {*ROLES, "elements"})
        if unknown:
            raise ValueError(f"unknown roles: {unknown}")
        values: dict = {}
        for role in AXES:
            columns = data.get(role, [])
            if not isinstance(columns, list) or not all(
                isinstance(c, str) for c in columns
            ):
                raise ValueError(f"{role} must be a list of column names")
            values[role] = tuple(columns)
        for role in SINGLES:
            column = data.get(role)
            if column is not None and not isinstance(column, str):
                raise ValueError(f"{role} must be a column name or null")
            values[role] = column
        elements = data.get("elements", ["points"])
        if (
            not isinstance(elements, list)
            or not elements
            or not all(e in ELEMENTS for e in elements)
        ):
            raise ValueError(f"elements must be a non-empty list of {ELEMENTS}")
        values["elements"] = tuple(e for e in ELEMENTS if e in elements)
        return cls(**values)
