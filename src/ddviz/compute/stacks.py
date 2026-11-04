"""Points of a categorical axis that share their exact coordinates: stacked in their band, or one counted marker.

A row of a pair of axis columns with a categorical axis lies at the center
of its level's band (`ddviz.compute.bands`). Rows of one facet cell whose
coordinates are exactly equal (the same level, the same numeric value in the
column's own type, or the same pair of levels) form a stack, whatever their
series:

- A row alone stays at the center.
- The rows of a stack whose points fit its band and the panel's plot area
  move apart along the categorical axis, ordered by their row index: in a
  line centered on the center, or, with two categorical axes, in a grid
  (`grid_shape`).
- The rows of a stack that does not fit stay at the center and are drawn as
  one marker of the stack, with its number of rows (a pile): none of them is
  a point of its series.

Positions are in pixels of the panel (bin ``i`` spans ``[i, i + 1)``), so
that the points of a stack lie whole pixels apart. Nothing here holds every
row: the stacks are counted part by part, the rows split by a hash of their
coordinates (`parts`, `part_of`) and only by their coordinates, and only
the rows of the stacks that fit are ranked, a bounded number at once
(`ranked`).

"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import polars as pl

from ddviz.compute.bands import BAND
from ddviz.compute.temporal import as_number, temporal_kind

# Columns of a frame of drawn rows: the coordinates as compared (`KEYS`: the
# facet cell and the levels of the categorical axes packed into one Int64,
# and the value of a numeric axis in its own type, else 0), the center along
# x and y in pixels of the panel, the panel, the series, and the width and
# height in pixels of the row's marker.
KC = "__kc"
KV = "__kv"
KEYS = [KC, KV]
PX = "__px"
PY = "__py"
PANEL = "__panel"
SERIES = "__series"
WX = "__wx"
WY = "__wy"
# Columns of the stacks (`count_stacks`, `describe`): the rows, and whether
# they fit.
N = "__stack_n"
FIT = "__fit"
# Columns of the placed rows (`place`): the offset from the center in pixels.
DX = "__dx"
DY = "__dy"
# Most distinct coordinates counted in one part (`parts`).
PART_KEYS = 10_000_000
# Most rows of the stacks that fit ranked at once (`ranked`).
PART_ROWS = 5_000_000
# Seed of the hash that splits the rows into parts.
_SEED = 86
_RANK = "__rank"
_TEMPORAL = "__temporal"


@dataclass(frozen=True)
class Axis:
    """One axis of a pair's panels, as the stacks see it.

    Parameters
    ----------
    banded : bool
        Whether the axis is categorical: the rows of a stack move apart
        along it.
    lo, hi : float
        The axis' range in the panel (the view's, or the overview's).
    bins : int
        Pixels of a panel along the axis.
    """

    banded: bool
    lo: float
    hi: float
    bins: int

    @property
    def scale(self) -> float:
        """Pixels per unit of the axis."""
        return self.bins / (self.hi - self.lo)

    def pixel(self, value: pl.Expr) -> pl.Expr:
        """Return where positions lie in pixels of the panel, from 0 at `lo`.

        Parameters
        ----------
        value : polars.Expr
            Positions in the axis' units.

        Returns
        -------
        polars.Expr
            The positions in pixels, as Float64.
        """
        return (value.cast(pl.Float64) - self.lo) * self.scale

    def position(self, pixel: pl.Expr) -> pl.Expr:
        """Return positions in the axis' units from pixels of the panel (the inverse of `pixel`).

        Parameters
        ----------
        pixel : polars.Expr
            Positions in pixels.

        Returns
        -------
        polars.Expr
            The positions.
        """
        return self.lo + pixel / self.scale


def key_value(column: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """Return a numeric column's values as stacks compare them: in their own type, -0.0 as 0.0.

    Parameters
    ----------
    column : polars.Expr
        The column.
    dtype : polars.DataType
        Its type as read.

    Returns
    -------
    polars.Expr
        The values. Integers stay integers, so that two of them that one
        float cannot tell apart stay apart.
    """
    return column + 0.0 if dtype.is_float() else column


def _hash() -> pl.Expr:
    """Return the hash of each row's coordinates."""
    return pl.struct(KEYS).hash(_SEED)


def parts(frame: pl.LazyFrame) -> int:
    """Return how many parts the rows of a frame are counted in.

    Parameters
    ----------
    frame : polars.LazyFrame
        Drawn rows with the `KEYS` columns.

    Returns
    -------
    int
        Enough parts for about `PART_KEYS` distinct coordinates each, by an
        estimate of the distinct coordinates (HyperLogLog, in one streaming
        pass).
    """
    distinct = (
        frame.select(_hash().approx_n_unique()).collect(engine="streaming").item()
    )
    return max(1, math.ceil((distinct or 0) / PART_KEYS))


@dataclass(frozen=True)
class Part:
    """Some of the parts the rows are split into by the hash of their coordinates.

    Parameters
    ----------
    n : int
        Number of parts.
    members : tuple of int
        The parts.
    """

    n: int
    members: tuple[int, ...]


def part_of(
    frame: pl.LazyFrame | pl.DataFrame, part: Part, sub: int = 1, j: int = 0
) -> pl.LazyFrame | pl.DataFrame:
    """Return the rows of some parts, and of their sub-part `j` of `sub`: whole stacks each.

    Parameters
    ----------
    frame : polars.LazyFrame or polars.DataFrame
        Rows (or stacks) with the `KEYS` columns.
    part : Part
        The parts.
    sub, j : int
        Number of sub-parts of each part, and the sub-part.

    Returns
    -------
    polars.LazyFrame or polars.DataFrame
        The rows of the parts.
    """
    n = part.n
    if sub == 1 and len(part.members) == n:
        return frame
    # h % (n * sub) is (h % n) + n * ((h // n) % sub).
    hashed = _hash() % (n * sub)
    targets = [i + n * j for i in part.members]
    if len(targets) == 1:
        return frame.filter(hashed == targets[0])
    return frame.filter(hashed.is_in(pl.Series(targets, dtype=pl.UInt64).implode()))


def grid_shape(n: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """Return the columns and rows of the grid of a stack of `n` points on two categorical axes.

    Parameters
    ----------
    n : polars.Expr
        Rows of each stack.

    Returns
    -------
    tuple of polars.Expr
        ``ceil(sqrt(n))`` columns and ``ceil(n / columns)`` rows, as Int64.
    """
    cols = n.cast(pl.Float64).sqrt().ceil().cast(pl.Int64)
    return cols, (n + cols - 1) // cols


def _fits_line(axis: Axis, center: str, width: str, n: pl.Expr) -> pl.Expr:
    """Return whether `n` points of each stack, in a line along an axis, fit their band and the panel.

    The points lie their largest marker plus a pixel apart; the pixels of
    the first and last points' markers must lie in the band (the center
    plus or minus `ddviz.compute.bands.BAND`) and in the panel.
    """
    c, w = pl.col(center), pl.col(width)
    half = (n - 1) / 2 * (w + 1)
    first = (c - half).floor() - (w - 1) // 2
    last = (c + half).floor() + (w - 1) // 2
    band = BAND * axis.scale
    return (first >= pl.max_horizontal(c - band, pl.lit(0.0))) & (
        last + 1 <= pl.min_horizontal(c + band, pl.lit(float(axis.bins)))
    )


@dataclass(frozen=True)
class Coordinates:
    """How the `KEYS` of a pair's rows hold their coordinates, so that a stack's center and panel come from its keys alone.

    Parameters
    ----------
    x_levels, y_levels : int or None
        Levels of a categorical x and y axis; None for a numeric one.
        `KC` is ``cell * x_levels + x level``, times ``y_levels`` plus the
        y level, of the axes that are categorical.
    value : polars.DataType or None
        The type, as read, of the numeric axis' column, whose value is `KV`;
        None with two categorical axes.
    panels : list of int
        The panel of each facet cell.
    widths, heights : list of int
        Width and height in pixels of the marker of each overlay level
        (`ddviz.compute.stacked.marker_boxes`).
    """

    x_levels: int | None
    y_levels: int | None
    value: pl.DataType | None
    panels: list[int]
    widths: list[int]
    heights: list[int]

    @property
    def varied(self) -> bool:
        """Whether the markers differ by overlay level, so that a stack's largest comes from its rows."""
        return len(set(self.widths)) > 1 or len(set(self.heights)) > 1


def count_stacks(frame: pl.LazyFrame, coordinates: Coordinates) -> pl.DataFrame:
    """Return the coordinates of more than one row of a frame, and their rows.

    Only the keys and a count (and the largest marker, when the markers
    differ): a streaming group_by of 25M distinct keys of an Int64 and a
    Float64 took about 3.2GB, and about 9GB with each one's center, panel
    and largest marker besides (`docs/spec.md`, "カテゴリの軸の点の重なり").

    Parameters
    ----------
    frame : polars.LazyFrame
        Drawn rows (of a part, `part_of`) with the `KEYS`, `WX` and `WY`
        columns.
    coordinates : Coordinates
        How the keys hold the coordinates.

    Returns
    -------
    polars.DataFrame
        The `KEYS` and the rows (`N`) of each stack of two rows or more,
        with `WX` and `WY` when the markers differ.
    """
    markers = [pl.col(WX).max(), pl.col(WY).max()] if coordinates.varied else []
    return (
        frame.group_by(KEYS)
        .agg(pl.len().cast(pl.Int64).alias(N), *markers)
        .filter(pl.col(N) >= 2)
        .collect(engine="streaming")
    )


def describe(
    counted: pl.DataFrame, x: Axis, y: Axis, coordinates: Coordinates
) -> pl.DataFrame:
    """Return stacks with their center, panel and largest marker, and whether they fit.

    The center and the panel come from the keys (`Coordinates`): no pass
    over the rows.

    Parameters
    ----------
    counted : polars.DataFrame
        The stacks (`count_stacks`).
    x, y : Axis
        The pair's axes; one of them at least is banded.
    coordinates : Coordinates
        How the keys hold the coordinates.

    Returns
    -------
    polars.DataFrame
        `counted` with the center (`PX`, `PY`), `PANEL`, the largest marker
        of the rows (`WX`, `WY`) and whether the points fit (`FIT`).
    """
    nx, ny = coordinates.x_levels, coordinates.y_levels
    packed = pl.col(KC)
    if nx and ny:
        kx, ky, cell = packed // ny % nx, packed % ny, packed // (nx * ny)
    elif nx:
        kx, ky, cell = packed % nx, None, packed // nx
    else:
        kx, ky, cell = None, packed % ny, packed // ny
    stacks = counted
    value = pl.col(KV)
    dtype = coordinates.value
    if dtype is not None and temporal_kind(dtype) is not None:
        # The number of the temporal value, as the rows' centers have it.
        stacks = stacks.with_columns(pl.col(KV).cast(dtype).alias(_TEMPORAL))
        value = as_number(_TEMPORAL, dtype)
    markers = []
    if not coordinates.varied:
        markers = [
            pl.lit(coordinates.widths[0], pl.Int64).alias(WX),
            pl.lit(coordinates.heights[0], pl.Int64).alias(WY),
        ]
    stacks = stacks.with_columns(
        x.pixel(value if kx is None else kx).alias(PX),
        y.pixel(value if ky is None else ky).alias(PY),
        pl.lit(pl.Series(coordinates.panels, dtype=pl.Int64)).gather(cell).alias(PANEL),
        *markers,
    ).drop(_TEMPORAL, strict=False)
    n = pl.col(N)
    if x.banded and y.banded:
        cols, n_rows = grid_shape(n)
        fit = _fits_line(x, PX, WX, cols) & _fits_line(y, PY, WY, n_rows)
    elif x.banded:
        fit = _fits_line(x, PX, WX, n)
    else:
        fit = _fits_line(y, PY, WY, n)
    return stacks.with_columns(fit.alias(FIT))


def stack_groups(
    frame: pl.LazyFrame, x: Axis, y: Axis, coordinates: Coordinates
) -> Iterator[tuple[pl.LazyFrame, pl.DataFrame, Part]]:
    """Yield the rows of a frame in groups of whole stacks, with their stacks.

    The stacks are counted part by part (`parts`). Consecutive parts form a
    group while their stacks number at most `PART_KEYS` together, so that
    the rows of parts with few stacks are read once more for all of them.
    A group is yielded before the next parts are counted: one group's
    stacks are held at a time.

    Parameters
    ----------
    frame : polars.LazyFrame
        Drawn rows with the columns of `ddviz.compute.stacked.stack_frame`.
    x, y : Axis
        The pair's axes.
    coordinates : Coordinates
        How the keys hold the coordinates.

    Yields
    ------
    tuple
        The rows of a group, its stacks (`describe`), and its parts.
    """
    n = parts(frame)
    members: list[int] = []
    pending: list[pl.DataFrame] = []
    for i in range(n):
        found = count_stacks(part_of(frame, Part(n, (i,))), coordinates)
        if members and sum(p.height for p in pending) + found.height > PART_KEYS:
            part = Part(n, tuple(members))
            stacks = describe(pl.concat(pending), x, y, coordinates)
            pending.clear()
            yield part_of(frame, part), stacks, part
            members = []
        members.append(i)
        pending.append(found)
    part = Part(n, tuple(members))
    yield part_of(frame, part), describe(pl.concat(pending), x, y, coordinates), part


def ranked(
    rows: pl.LazyFrame,
    stacks: pl.DataFrame,
    part: Part,
    index: str,
    x: Axis,
    y: Axis,
    columns: list[str],
) -> Iterator[pl.DataFrame]:
    """Yield the rows of the stacks that fit, placed (`place`), a bounded number at once.

    Parameters
    ----------
    rows : polars.LazyFrame
        The rows of a group (`stack_groups`).
    stacks : polars.DataFrame
        Its stacks.
    part : Part
        The parts of the group.
    index : str
        Column of the row index.
    x, y : Axis
        The pair's axes.
    columns : list of str
        Columns of the rows to keep besides the `KEYS` and `index`.

    Yields
    ------
    polars.DataFrame
        Placed rows, with their stack's `N`, `PX`, `PY`, `PANEL`, `WX` and
        `WY`, and `DX` and `DY`; about `PART_ROWS` at most each.

    """
    fit = stacks.filter(pl.col(FIT)).select(*KEYS, N, PX, PY, PANEL, WX, WY)
    if fit.height == 0:
        return
    sub = max(1, math.ceil(fit[N].sum() / PART_ROWS))
    keep = list(dict.fromkeys([*KEYS, index, *columns]))
    for j in range(sub):
        stacks_j = part_of(fit, part, sub, j)
        # Only the keys, the index and `columns` of the rows: their stack has
        # the rest, the same for all of them.
        found = (
            part_of(rows, part, sub, j)
            .join(stacks_j.select(KEYS).lazy(), on=KEYS, how="semi")
            .select(keep)
            .collect(engine="streaming")
            .join(stacks_j, on=KEYS)
        )
        yield place(found, index, x, y)


def place(rows: pl.DataFrame, index: str, x: Axis, y: Axis) -> pl.DataFrame:
    """Return the rows of stacks that fit with their offsets from the center of their stack.

    Parameters
    ----------
    rows : polars.DataFrame
        All the rows of some stacks that fit, with the `KEYS`, the row
        index `index`, and their stack's `N`, `WX` and `WY`.
    index : str
        Column of the row index, which orders the points of a stack.
    x, y : Axis
        The pair's axes.

    Returns
    -------
    polars.DataFrame
        `rows` with `DX` and `DY`, the offsets in pixels. Rank ``r`` (from
        0) of ``n`` lies ``(r - (n - 1) / 2) * spacing`` from the center
        along the banded axis, where the spacing is the stack's largest
        marker plus a pixel. With two banded axes, the ranks fill the rows
        of a grid (`grid_shape`) from the top, each row centered, and the
        grid is centered.
    """
    ranked = rows.with_columns(
        (pl.col(index).rank("ordinal").over(KEYS).cast(pl.Int64) - 1).alias(_RANK)
    )
    n, rank = pl.col(N), pl.col(_RANK)
    sx, sy = pl.col(WX) + 1, pl.col(WY) + 1
    if x.banded and y.banded:
        cols, n_rows = grid_shape(n)
        row, col = rank // cols, rank % cols
        in_row = pl.when(row < n_rows - 1).then(cols).otherwise(n - cols * (n_rows - 1))
        dx = (col - (in_row - 1) / 2) * sx
        dy = ((n_rows - 1) / 2 - row) * sy
    elif x.banded:
        dx, dy = (rank - (n - 1) / 2) * sx, pl.lit(0.0)
    else:
        dx, dy = pl.lit(0.0), (rank - (n - 1) / 2) * sy
    return ranked.with_columns(
        dx.cast(pl.Float64).alias(DX), dy.cast(pl.Float64).alias(DY)
    ).drop(_RANK)


def bins_of(x: Axis, y: Axis, dx: pl.Expr, dy: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """Return the pixel of each row along x and y, from its center and its offset.

    Parameters
    ----------
    x, y : Axis
        The pair's axes.
    dx, dy : polars.Expr
        Offsets in pixels.

    Returns
    -------
    tuple of polars.Expr
        The bins as Int64, kept in the panel.
    """
    bx = (pl.col(PX) + dx).floor().clip(0, x.bins - 1).cast(pl.Int64)
    by = (pl.col(PY) + dy).floor().clip(0, y.bins - 1).cast(pl.Int64)
    return bx, by


def tops(piles: pl.DataFrame, x: Axis, y: Axis) -> pl.DataFrame:
    """Return the pile drawn at each pixel: of the piles there, the one of the most rows.

    The piles of other coordinates in the same pixel lie under it; zooming
    in parts them.

    Parameters
    ----------
    piles : polars.DataFrame
        Stacks that do not fit (`count_stacks`).
    x, y : Axis
        The pair's axes.

    Returns
    -------
    polars.DataFrame
        One row per pixel, ordered by panel, ``by`` and ``bx``: the `KEYS`,
        `N`, `PX`, `PY`, `PANEL` and the pixel's bins ``bx`` and ``by``.
    """
    bx, by = bins_of(x, y, pl.lit(0.0), pl.lit(0.0))
    order = [PANEL, "by", "bx", N, *KEYS]
    return (
        piles.with_columns(bx.alias("bx"), by.alias("by"))
        .sort(order, descending=[o == N for o in order])
        .unique([PANEL, "by", "bx"], keep="first", maintain_order=True)
        .select(*KEYS, N, PX, PY, PANEL, "bx", "by")
    )
