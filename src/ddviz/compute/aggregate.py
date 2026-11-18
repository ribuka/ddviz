"""Pixel-bin aggregation of a scatter plot with one representative row per bin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

import polars as pl

from ddviz.compute.axisposition import on_axis, position, within
from ddviz.compute.bands import JITTER_X, band_range, jitter, level_index
from ddviz.compute.boxes import (
    GROUP,
    VALUE,
    BoxGroups,
    box_stats,
    fences,
    is_outlier,
    outlier_position,
)
from ddviz.compute.cuts import cut_index, cut_labels, find_cuts
from ddviz.compute.lines import VALUE as LINE_VALUE
from ddviz.compute.lines import LinePixels, line_frame, line_pixels
from ddviz.compute.missing import (
    drawn_conditions,
    is_missing,
    numeric_columns,
    numeric_roles,
    role_index,
)
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.compute.smooth import bin_query, fit_lines
from ddviz.compute.stacked import ROWS, TOP, marker_boxes, stack_frame, stacked_bins
from ddviz.compute.stacks import Axis
from ddviz.shared.axisscale import (
    RANGE_PADDING,
    NoPositiveValuesError,
    no_positive_message,
    padded_log_range,
    values,
)
from ddviz.shared.keys import BinGrid
from ddviz.shared.layout import (
    GAP,
    WRAP_GAP,
    AxisGrid,
    GridLayout,
    facet_grid,
    grid_layout,
)
from ddviz.shared.missing import MISSING
from ddviz.shared.natural import natural_key
from ddviz.shared.scatter import (
    ONE_BAND,
    Binning,
    Boxes,
    FilteredLevelsError,
    ScatterSpec,
    Smooths,
    filtered_levels_message,
)

KEY = "__key"
COUNT = "__n"
INDEX = "__idx"
# Whether a row is an outlier of its box plot, or any row of a pair whose
# panels draw points.
_OUTLIER = "__outlier"

# Most piles a plot draws (`ddviz.compute.stacks`): the page draws each with
# its number of rows.
MAX_PILES = 100_000
# Rows a pair's bins are aggregated from at a time (`_binned`). The peak of a
# streaming group_by with many groups grows with its rows: binning x against
# y with about 700K non-empty bins peaked at 2.34GB on 100M rows and 4.17GB
# on 200M in one query, against 1.53GB and 1.57GB 25M rows at a time, in
# about the same time (2.2s and 1.9s on 200M rows). 10M rows at a time
# peaked a little lower (1.50GB on 200M) but reads the files in more passes.
ROWS_PER_PASS = 25_000_000
# Rows the levels of a column among the rows of the local filter are found
# from at a time (`_levels_among_filter`): the levels of each slice are
# merged into those found so far, and the reading stops once they pass the
# limit.
LEVEL_ROWS_PER_PASS = 25_000_000


@dataclass(frozen=True)
class Piles:
    """The piles drawn in the panels of a pair of axis columns (`ddviz.compute.stacked.StackedBins`).

    Parameters
    ----------
    x, y : str
        The pair's columns.
    piles : polars.DataFrame
        One pile per pixel (`ddviz.compute.stacks.tops`).
    series : polars.DataFrame or None
        The rows of each pile by series; None without piles.
    """

    x: str
    y: str
    piles: pl.DataFrame
    series: pl.DataFrame | None


@dataclass(frozen=True)
class Aggregation:
    """Result of `aggregate`.

    Parameters
    ----------
    grid : BinGrid
        Key space of the bins.
    layout : GridLayout
        Panels in the figure; one bin is one pixel of a panel.
    axes : AxisGrid
        Facet cell and pair of axis columns of each panel.
    x_ranges, y_ranges : list of tuple of float
        Data range of each x and each y column that the bins cover; along x
        in a panel of the x column ``xi``, bin ``i`` spans
        ``lo + i * (hi - lo) / grid.width`` onward, where ``lo, hi`` is
        ``x_ranges[xi]``. Those of a column on a log axis are positions:
        the log10 of its values (`ddviz.shared.axisscale`).
    x_auto, y_auto : list of tuple of float
        Automatic range of each x and each y column, in the same
        coordinates: a continuous axis spans the finite values (on a log
        axis, the positive ones) of its column alone among the rows that
        pass the local filter, padded (`_padded`, `padded_log_range`); a
        column without one there spans those of every row, and a
        categorical axis its bands. The overview's ranges are these.
    levels : dict
        Levels of the ``"color"``, ``"symbol"``, ``"row"`` and ``"col"``
        roles as text, in index order, as drawn: the series of every row
        (pairs of a color and a symbol level), and the facet levels
        that have rows passing the local filter; a role without a column has
        the single level None.
    all_levels : dict
        Levels of the roles (`ddviz.shared.scatter.View.levels`): those of
        `ddviz.shared.scatter.ScatterSpec.levels_of_filter` are of the rows
        of the local filter, the others (a color or symbol column that
        keeps its levels) of every row; the facet levels of `levels` are
        those of them that have rows.
    cuts : dict
        Cuts of each role in the spec's ``binned`` (`ddviz.compute.cuts`);
        those of the color are of the rows of the local filter
        (`_color_scale`).
    color_range : tuple of float or None
        For a gradient, the finite minimum and maximum of the color column
        among the rows of the local filter (`_color_scale`); the bins then
        also hold the color of their representative row, and so do the
        selected bins.
    axis_levels : dict
        Levels of each categorical axis column among the rows of the local
        filter, as text: the bands of its axis (`ddviz.compute.bands`).
    piles : list of Piles
        The piles drawn in the panels of each pair with a categorical axis
        whose panels draw points (`ddviz.compute.stacks`); none when only
        the selection was aggregated.
    pile_bins : polars.DataFrame or None
        The rows of the piles in the bins of their centers (`KEY` and
        `COUNT`), sorted by key: not drawn as points, but rows of their
        series all the same. None when only the selection was aggregated.
    boxes : list of Boxes
        Box plots of each pair of `ddviz.shared.scatter.ScatterSpec.box_pairs`.
    smooths : list of Smooths
        Smoothing lines of each pair of
        `ddviz.shared.scatter.ScatterSpec.smooth_pairs`.
    lines : LinePixels
        The pixels the lines of each pair of
        `ddviz.shared.scatter.ScatterSpec.line_pairs` cover, one pixel wide
        (`ddviz.compute.lines`); the ranks run on over the pairs. None
        when only the selection was aggregated.
    line_values : polars.Series or None
        For a gradient's lines, the color of each row of every pair's lines
        by rank: item ``r - 1`` colors the pixels of rank ``r``.
    bins : polars.DataFrame or None
        One row per non-empty bin, sorted by `KEY`: the key, the number of
        rows in the bin (`COUNT`), the representative row's index (`INDEX`,
        the largest row index in the bin) and its hover columns. None when
        only the selection was aggregated.
    selected : polars.DataFrame or None
        For a spec with a selection, the bins of the selected rows in every
        panel (`KEY` and `COUNT`), sorted by key.
    selected_rows : int or None
        For a spec with a selection, the number of selected rows; a row in
        several panels counts once.
    selected_piles : polars.DataFrame or None
        For a spec with a selection, the bins of the selected rows of the
        piles at their centers (`KEY` and `COUNT`).
    nonpositive : list of tuple of str
        The role (``"x"`` or ``"y"``) and the name of each column on a log
        axis with a finite value that is not positive among the rows of
        the local filter: rows not drawn in its panels.
    """

    grid: BinGrid
    layout: GridLayout
    axes: AxisGrid
    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    x_auto: list[tuple[float, float]]
    y_auto: list[tuple[float, float]]
    levels: dict[str, list]
    all_levels: dict[str, list]
    bins: pl.DataFrame | None
    selected: pl.DataFrame | None = None
    selected_rows: int | None = None
    cuts: dict[str, dict] = field(default_factory=dict)
    color_range: tuple[float, float] | None = None
    axis_levels: dict[str, list[str]] = field(default_factory=dict)
    piles: list[Piles] = field(default_factory=list)
    pile_bins: pl.DataFrame | None = None
    selected_piles: pl.DataFrame | None = None
    boxes: list[Boxes] = field(default_factory=list)
    smooths: list[Smooths] = field(default_factory=list)
    nonpositive: list[tuple[str, str]] = field(default_factory=list)
    lines: LinePixels | None = None
    line_values: pl.Series | None = None


def _padded(lo: float | None, hi: float | None) -> tuple[float, float]:
    """Return a data range with a margin, or a unit range around a constant."""
    if lo is None or hi is None:
        return (0.0, 1.0)
    if lo == hi:
        return (lo - 0.5, hi + 0.5)
    pad = (hi - lo) * RANGE_PADDING
    return (lo - pad, hi + pad)


def _bin_expr(value: pl.Expr, bounds: tuple[float, float], n: int) -> pl.Expr:
    """Return the bin index of a position over `bounds` split into `n` bins."""
    lo, hi = bounds
    scaled = (value - lo) * (n / (hi - lo))
    return scaled.floor().clip(0, n - 1).cast(pl.Int64)


def _binned(
    scan: pl.LazyFrame, rows: int, query: Callable[[pl.LazyFrame], pl.LazyFrame]
) -> pl.DataFrame:
    """Return the bins of `query` over `scan`, `ROWS_PER_PASS` rows at a time.

    Parameters
    ----------
    scan : polars.LazyFrame
        The rows, with their row index `INDEX` (`_scan`): a slice keeps the
        index of the whole scan, so the representative row of a bin is the
        same row whichever slice it is in.
    rows : int
        Rows of `scan`.
    query : callable
        Turns rows into their bins: `KEY`, `COUNT` (UInt32) and the largest
        `INDEX` of each key.

    Returns
    -------
    polars.DataFrame
        The bins of all the rows, one per key, in no particular order.
    """
    found = None
    for start in range(0, max(rows, 1), ROWS_PER_PASS):
        part = query(scan.slice(start, ROWS_PER_PASS)).collect(engine="streaming")
        if found is not None:
            part = (
                pl.concat([found, part])
                .group_by(KEY)
                .agg(pl.col(COUNT).sum().cast(pl.UInt32), pl.col(INDEX).max())
            )
        found = part
    return found


def _scan(
    spec: ScatterSpec, columns: list[str], row_index: str | None = None
) -> pl.LazyFrame:
    """Return a scan of only `columns` of the plot.

    Each query gets its own scan: queries in one `collect_all` sharing a scan
    followed by a ``select`` made the streaming engine peak at about 6.7GB on
    100M rows, against about 1.2GB with separate scans.
    """
    return scan_columns({c: spec.files[c] for c in dict.fromkeys(columns)}, row_index)


def _range_query(
    spec: ScatterSpec, column: str, filtered: bool = False, log: bool = False
) -> pl.LazyFrame:
    """Return the query of the finite minimum and maximum of a numeric column.

    `filtered` takes only the rows of the local filter, reading the column
    and the filter's columns alone; `log` only the positive values, those
    a log axis draws.
    """
    value = pl.col(column).cast(pl.Float64)
    # Not ``value.filter(...)``: a filter inside an expression holds the rows
    # it keeps until the minimum is taken, and the ranges of x and y on 1.11
    # billion rows went past 6GB; nulls in their place peaked at 0.69GB.
    finite = pl.when(on_axis(value, log)).then(value)
    if filtered and spec.filters:
        scan = _scan(spec, [column, *filter_columns(spec.filters)]).filter(
            *filter_conditions(spec.filters)
        )
    else:
        scan = _scan(spec, [column])
    return scan.select(finite.min().alias("min"), finite.max().alias("max"))


def _found_ranges(
    spec: ScatterSpec, columns: list[str], filtered: bool, log: bool = False
) -> dict[str, tuple[float, float] | None]:
    """Return the finite (`log`: positive) minimum and maximum of each column, None for one without such a value (`_range_query`)."""
    if not columns:
        return {}
    found = pl.collect_all(
        [_range_query(spec, c, filtered, log) for c in columns], engine="streaming"
    )
    out = {}
    for c, f in zip(columns, found, strict=True):
        lo, hi = f.row(0)
        out[c] = None if lo is None else (lo, hi)
    return out


@dataclass(frozen=True)
class _LogAxes:
    """What the rows of the local filter hold for the log axes (`_log_axes`)."""

    ranges: dict[str, tuple[float, float] | None]
    nonpositive: list[tuple[str, str]]


def _log_axes(spec: ScatterSpec) -> _LogAxes:
    """Return the positive finite range of each column on a log axis, and those with a value not positive.

    Over the rows of the local filter, in one pass per column.
    """
    columns = list(dict.fromkeys([*spec.log_x, *spec.log_y]))
    if not columns:
        return _LogAxes({}, [])
    queries = []
    for c in columns:
        value = pl.col(c).cast(pl.Float64)
        # Nulls in place of the others, as `_range_query` does.
        positive = pl.when(on_axis(value, True)).then(value)
        queries.append(
            _scan(spec, [c, *filter_columns(spec.filters)])
            .filter(*filter_conditions(spec.filters))
            .select(
                positive.min().alias("min"),
                positive.max().alias("max"),
                (value.is_finite() & (value <= 0)).any().alias("nonpositive"),
            )
        )
    found = pl.collect_all(queries, engine="streaming")
    ranges, flagged = {}, set()
    for c, f in zip(columns, found, strict=True):
        lo, hi, nonpositive = f.row(0)
        ranges[c] = None if lo is None else (lo, hi)
        if nonpositive:
            flagged.add(c)
    nonpositive = [
        (role, c)
        for role, logs in (("x", spec.log_x), ("y", spec.log_y))
        for c in logs
        if c in flagged
    ]
    return _LogAxes(ranges, nonpositive)


@dataclass(frozen=True)
class _Overview:
    """What the overview finds over every row (`_overview`)."""

    # The finite minimum and maximum of each numeric axis column, or None.
    ranges: dict[str, tuple[float, float] | None]
    levels: dict[str, list]
    cuts: dict[str, dict]
    color_range: tuple[float, float] | None
    axis_levels: dict[str, list[str]]


def _check_levels(
    spec: ScatterSpec,
    roles: dict[str, str | None],
    counted: dict[str, int],
    axes: list[str],
) -> None:
    """Refuse the columns with more levels over every row than a role they are on allows.

    A column on the color, symbol, row or col role (`roles`) may have at
    most `ScatterSpec.max_levels` levels, a categorical x or y column
    (`axes`) at most `ScatterSpec.max_axis_levels`; a column on both kinds
    of role has to meet both. These are the roles and axes whose levels are
    of every row: those of the rows of the local filter are counted there
    (`_found_levels`).

    Raises
    ------
    ValueError
        Naming each column refused, its levels and the limit it passes.
    """
    series = {c for r, c in roles.items() if c and r not in numeric_roles(spec)}
    over = []
    for c, n in counted.items():
        limits = []
        if c in series:
            limits.append((spec.max_levels, "Color・Symbol・Group・Wrap の上限"))
        if c in axes:
            limits.append((spec.max_axis_levels, "X・Y のカテゴリの軸の上限"))
        refused = [
            f"{c} は {n:,} 個で、{name}は {limit:,} 個"
            for limit, name in limits
            if n > limit
        ]
        if refused:
            over.append((c, refused))
    if not over:
        return
    # A color column that keeps its levels counts them before the filter;
    # any other has them of the rows of the filter, which lowers them.
    kept = spec.color if spec.keep_unfiltered_color_levels else None
    advice = (
        "水準はフィルタの前の行から数える設定のため、別の列を使うか、"
        "「フィルタで除外された水準も凡例に残す」を外す"
        if any(c == kept for c, _ in over)
        else "フィルタで水準を絞るか、別の列を使う"
    )
    raise ValueError(
        "水準が上限を超えるため描けない（"
        + "。".join(text for _, refused in over for text in refused)
        + "）。"
        + advice
    )


def _overview(
    spec: ScatterSpec, roles: dict[str, str | None], axes: list[str]
) -> _Overview:
    """Return the data range of each numeric axis column and the levels of each role, over every row.

    The ranges and the levels of the categorical roles (`roles`, None for
    one whose levels are found among the rows of the filter) and of the
    categorical axis columns `axes` come in one pass, the cuts of each
    binned role in passes of their own (`ddviz.compute.cuts.find_cuts`). A
    role that draws its missing rows
    (`ddviz.shared.scatter.ScatterSpec.null_roles`) ends in the missing
    level (`ddviz.shared.missing.MISSING`) when its column has a null or NaN
    value: among the rows of the local filter for a numeric column
    (`_has_missing`); a categorical column counts it as one of its levels
    against the limits of its roles (`_check_levels`).
    """
    numeric = [
        c for c in dict.fromkeys([*spec.x, *spec.y]) if c not in spec.categorical
    ]
    used = list(
        dict.fromkeys(
            [
                *(c for r, c in roles.items() if c and r not in numeric_roles(spec)),
                *axes,
            ]
        )
    )
    # The one band has its level without reading the data.
    used = [c for c in used if c != ONE_BAND]
    gradient = [spec.color] if spec.gradient else []
    # Whether each numeric column of a role that draws its missing rows has
    # any; a categorical one has a null level among its levels.
    read_as_numbers = numeric_columns(spec)
    asked = [
        c
        for c in dict.fromkeys(roles[r] for r in spec.null_roles if roles.get(r))
        if c in read_as_numbers
    ]
    # Levels and ranges come from the unfiltered scan: a row filter on the
    # same pass made the streaming engine peak at about 6.5GB on 100M rows,
    # against about 1.1GB without it. The ranges of the rows of the filter
    # come in passes of their own (`_auto_ranges`); these stand in for an
    # axis column the filter leaves without a value.
    found = pl.collect_all(
        [
            *[_range_query(spec, c) for c in numeric],
            *[_scan(spec, [c]).group_by(pl.col(c).cast(pl.String)).len() for c in used],
            *[_range_query(spec, c) for c in gradient],
        ],
        engine="streaming",
    )
    has_null = _has_missing(spec, asked)
    color_range = None
    no_values = False
    if gradient:
        lo, hi = found.pop().row(0)
        no_values = lo is None
        color_range = (0.0, 1.0) if lo is None else (lo, hi)
    ranges = {}
    for c, f in zip(numeric, found, strict=False):
        lo, hi = f.row(0)
        ranges[c] = None if lo is None else (lo, hi)
    column_levels = {}
    for c, f in zip(used, found[len(numeric) :], strict=True):
        column_levels[c] = sorted(f[c].drop_nulls().to_list(), key=natural_key)
        has_null[c] = f[c].null_count() > 0
    missing = {r for r in spec.null_roles if roles.get(r) and has_null[roles[r]]}
    # The missing level's name is no text of the data.
    taken = [c for c in column_levels if MISSING in column_levels[c]]
    if taken:
        raise ValueError(_missing_name_message(taken))
    if ONE_BAND in axes:
        column_levels[ONE_BAND] = [""]
    axis_levels = {c: column_levels[c] for c in axes}
    # The missing level drawn counts as one level of its column.
    counted = {
        c: len(v) + any(roles[r] == c for r in missing)
        for c, v in column_levels.items()
    }
    _check_levels(spec, roles, counted, axes)
    cuts = {
        role: find_cuts(_scan(spec, [roles[role]]), roles[role], binning)
        for role, binning in spec.binned.items()
    }
    levels = {}
    for role, c in roles.items():
        if c is None or (role == "color" and spec.gradient):
            levels[role] = [None]
        elif role in cuts:
            levels[role] = cut_labels(cuts[role], spec.temporal.get(c))
        else:
            levels[role] = column_levels[c]
        if role in missing:
            # A gradient without a finite value has only the missing level.
            empty = role == "color" and spec.gradient and no_values
            levels[role] = [MISSING] if empty else [*levels[role], MISSING]
    return _Overview(ranges, levels, cuts, color_range, axis_levels)


def _values_among_filter(
    spec: ScatterSpec, column: str, start: int, length: int
) -> pl.Series:
    """Return the values of a column, as text, of the rows ``start`` to ``start + length`` that pass the local filter, once each; a null among them if any."""
    return (
        _scan(spec, [column, *filter_columns(spec.filters)])
        .slice(start, length)
        .filter(*filter_conditions(spec.filters))
        .select(pl.col(column).cast(pl.String))
        .unique()
        .collect(engine="streaming")[column]
    )


def _levels_among_filter(
    spec: ScatterSpec, column: str, limit: int
) -> tuple[list[str], bool] | None:
    """Return the levels of a categorical column among the rows of the local filter, and whether those rows have a null value.

    Reads only the column and the filter's columns, in a pass of its own: a
    row filter on the overview's pass made it peak far higher
    (`_overview`). The rows are read `LEVEL_ROWS_PER_PASS` at a time, the
    levels of each slice merged into those found so far, and the reading
    stops as soon as they pass `limit`, so that a column of a level per row
    (an ID) never holds them all. The levels are text, as those found over
    every row, in natural order, the empty text one of them.

    Returns
    -------
    tuple of (list of str, bool) or None
        The levels and whether a null value is among the rows; None when
        the levels pass `limit`.

    Raises
    ------
    ValueError
        When a value is the missing level's name.
    """
    rows = _scan(spec, [column]).select(pl.len()).collect().item()
    found: set[str] = set()
    has_null = False
    for start in range(0, max(rows, 1), LEVEL_ROWS_PER_PASS):
        part = _values_among_filter(spec, column, start, LEVEL_ROWS_PER_PASS)
        has_null = has_null or part.null_count() > 0
        found.update(part.drop_nulls().to_list())
        if len(found) > limit:
            return None
    if MISSING in found:
        raise ValueError(_missing_name_message([column]))
    return sorted(found, key=natural_key), has_null


def _has_missing(spec: ScatterSpec, columns: list[str]) -> dict[str, bool]:
    """Return whether each numeric column has a null or NaN value among the rows of the local filter (every row without a filter).

    Each column is read with the filter's columns alone, apart from the
    overview's pass (`_overview`).
    """
    if not columns:
        return {}
    found = pl.collect_all(
        [
            _scan(spec, [c, *filter_columns(spec.filters)])
            .filter(*filter_conditions(spec.filters))
            .select(is_missing(c, numeric=True).any())
            for c in columns
        ],
        engine="streaming",
    )
    return {c: bool(f.item()) for c, f in zip(columns, found, strict=True)}


def _role_name(spec: ScatterSpec, role: str) -> str:
    """Return the name the page gives a role (its zone)."""
    if role == "col":
        return "Wrap" if spec.wrap else "Group X"
    return {"color": "Color", "symbol": "Symbol", "row": "Group Y"}[role]


def _found_levels(
    spec: ScatterSpec,
    roles: dict[str, str | None],
    levels: dict[str, list],
    find: list[str],
    axes: list[str],
) -> tuple[dict[str, list], dict[str, list[str]]]:
    """Return the levels of the roles `find` and of the categorical axis columns `axes` among the rows of the local filter.

    A categorical role (`ddviz.shared.scatter.ScatterSpec.levels_of_filter`)
    has the levels of its column among those rows (`_levels_among_filter`),
    then the missing level (`ddviz.shared.missing.MISSING`) when it draws
    its missing rows and they have a null value, which counts as one level
    against `ScatterSpec.max_levels`. A numeric role keeps its levels
    (`levels`), but for the missing level, last when those rows have a null
    or NaN value (`_has_missing`); a gradient without a finite value over
    every row has only the missing level, or else its one level. An axis
    column has the levels of those rows, up to `ScatterSpec.max_axis_levels`.
    A column on two of them is read once.

    Raises
    ------
    FilteredLevelsError
        Naming each role and axis past its limit.
    ValueError
        When a value is the missing level's name.
    """
    numeric = numeric_roles(spec)
    # Each column read, with the limits of its roles and axes.
    limits: dict[str, list[tuple[int, str, str | None]]] = {}
    for role in find:
        if role not in numeric:
            limits.setdefault(roles[role], []).append(
                (spec.max_levels, _role_name(spec, role), role)
            )
    for c in axes:
        limits.setdefault(c, []).append(
            (spec.max_axis_levels, "X・Y のカテゴリの軸", None)
        )
    found = {
        c: _levels_among_filter(spec, c, max(n for n, _, _ in ls))
        for c, ls in limits.items()
    }
    # A facet role the filter leaves without a level to draw keeps the
    # levels of every row, its panels empty: a figure has a panel at least.
    # A missing row left is a level of a role that draws it, role by role.
    empty = [
        r
        for r in ("row", "col")
        if r in find
        and r not in numeric
        and found[roles[r]] is not None
        and not found[roles[r]][0]
        and not (found[roles[r]][1] and r in spec.null_roles)
    ]
    every_row = {
        c: _levels_among_filter(replace(spec, filters=[]), c, spec.max_levels)
        for c in dict.fromkeys(roles[r] for r in empty)
    }
    of_every_row = {r: every_row[roles[r]] for r in empty}
    over = []
    out_levels: dict[str, list] = {}
    out_axes: dict[str, list[str]] = {}
    for c, ls in limits.items():
        for limit, name, role in ls:
            got = of_every_row.get(role, found[c])
            if got is None:
                over.append((name, c, limit))
                continue
            column_levels, has_null = got
            if role is None:
                if len(column_levels) > limit:
                    over.append((name, c, limit))
                out_axes[c] = column_levels
                continue
            drawn = list(column_levels)
            if role in spec.null_roles and has_null:
                drawn.append(MISSING)
            if len(drawn) > limit:
                over.append((name, c, limit))
            out_levels[role] = drawn
    if over:
        raise FilteredLevelsError(filtered_levels_message(over))
    missing_roles = [r for r in find if r in numeric]
    has_null = _has_missing(
        spec, list(dict.fromkeys(roles[r] for r in missing_roles))
    )
    for role in missing_roles:
        normal = [v for v in levels[role] if v != MISSING]
        if not normal:
            # A gradient without a finite value over every row.
            out_levels[role] = [MISSING] if has_null[roles[role]] else [None]
        else:
            out_levels[role] = [*normal, MISSING] if has_null[roles[role]] else normal
    return out_levels, out_axes


def _numeric_color(spec: ScatterSpec) -> bool:
    """Return whether the color column is numeric: a gradient, or cut into intervals."""
    return spec.gradient or "color" in spec.binned


def _found_color_scale(spec: ScatterSpec, filtered: bool) -> dict | None:
    """Return the color scale of the finite values of a numeric color column, among the rows of the local filter (`filtered`) or every row.

    ``{"range": (lo, hi)}`` for a gradient, the cuts (`find_cuts`) of a
    column cut into intervals; None without a finite value. The rows of
    the filter are read in passes of their own, of the color column and the
    filter's columns alone, as the automatic ranges are (`_range_query`).
    """
    if spec.gradient:
        found = _found_ranges(spec, [spec.color], filtered=filtered)[spec.color]
        return None if found is None else {"range": found}
    return _found_cuts(spec, spec.color, spec.binned["color"], filtered)


def _found_cuts(
    spec: ScatterSpec, column: str, binning: Binning, filtered: bool
) -> dict | None:
    """Return the cuts (`find_cuts`) of the finite values of a numeric column, among the rows of the local filter (`filtered`) or every row; None without a finite value.

    The rows of the filter are read in a pass of their own, of the column
    and the filter's columns alone.
    """
    if filtered and spec.filters:
        scan = _scan(spec, [column, *filter_columns(spec.filters)]).filter(
            *filter_conditions(spec.filters)
        )
    else:
        scan = _scan(spec, [column])
    cuts = find_cuts(scan, column, binning)
    return cuts if cuts["breaks"] else None


def _color_scale(spec: ScatterSpec, progress: Callable[[str], None]) -> dict | None:
    """Return the color scale a numeric color column draws with, or None to keep the one known.

    The scale kept by the page (`ScatterSpec.color_scale`) comes first.
    Else the overview of a filter, and a view that finds it again
    (`ddviz.shared.scatter.View.find_color_scale`), take that of the rows of
    the filter; one that the filter leaves without a finite value takes
    that of every row: the overview's own, or found again by a view. The
    overview without a filter keeps that of every row, with no pass more.
    """
    if not _numeric_color(spec):
        return None
    if spec.color_scale is not None:
        return spec.color_scale
    view = spec.view
    if (view is None and not spec.filters) or (
        view is not None and not view.find_color_scale
    ):
        return None
    progress("scale")
    found = _found_color_scale(spec, filtered=True)
    if found is None and spec.filters:
        if view is None:
            return None
        found = _found_color_scale(spec, filtered=False)
    if found is None:
        # As the overview has it for a column without a finite value.
        return (
            {"range": (0.0, 1.0)} if spec.gradient else {"breaks": [], "values": False}
        )
    return found


def _role_cuts(
    spec: ScatterSpec, roles: dict[str, str | None], progress: Callable[[str], None]
) -> dict[str, dict]:
    """Return the cuts the roles of ``binned`` but the color (symbol, row, col) draw with; a role left out keeps those known.

    As the color scale (`_color_scale`): the cuts kept by the page
    (`ScatterSpec.kept_cuts`) come first. Else the overview of a filter,
    and a view that finds them again (`ddviz.shared.scatter.View.find_cuts`),
    take those of the rows of the filter; a role that the filter leaves
    without a finite value takes those of every row: the overview's own,
    or found again by a view. The overview without a filter keeps those of
    every row, with no pass more. A column on two roles is read once.
    """
    view = spec.view
    found: dict[str, dict] = {}
    by_column: dict[tuple[str, Binning], dict | None] = {}
    for role, binning in spec.binned.items():
        if role == "color":
            continue
        if role in spec.kept_cuts:
            found[role] = spec.kept_cuts[role]
            continue
        if (view is None and not spec.filters) or (
            view is not None and role not in view.find_cuts
        ):
            continue
        key = (roles[role], binning)
        if key not in by_column:
            progress("cuts")
            cuts = _found_cuts(spec, roles[role], binning, filtered=True)
            if cuts is None and spec.filters and view is not None:
                cuts = _found_cuts(spec, roles[role], binning, filtered=False)
            by_column[key] = cuts
        cuts = by_column[key]
        if cuts is not None:
            found[role] = cuts
        elif view is not None:
            # As the overview has it for a column without a finite value.
            found[role] = {"breaks": [], "values": False}
    return found


def _scaled(
    spec: ScatterSpec,
    roles: dict[str, str | None],
    scale: dict | None,
    levels: dict[str, list],
    cuts: dict,
    color_range: tuple[float, float] | None,
) -> tuple[dict[str, list], dict, tuple[float, float] | None]:
    """Return the levels, the cuts and the color range with the color scale `scale` (`_color_scale`, None to keep the one known) and the cuts of the other roles (`cuts`).

    The levels of each role cut into intervals are the names of its cuts,
    the missing level kept last: a view is given the levels of another
    result, and the cuts of the rows of its filter.
    """
    if scale is not None and spec.gradient:
        lo, hi = scale["range"]
        color_range = (float(lo), float(hi))
    elif scale is not None:
        cuts = {**cuts, "color": scale}
    cuts = {
        role: {"breaks": [float(b) for b in c["breaks"]], "values": bool(c["values"])}
        for role, c in cuts.items()
    }
    named = dict(levels)
    for role in spec.binned:
        names = cut_labels(cuts[role], spec.temporal.get(roles[role]))
        if levels[role][-1:] == [MISSING]:
            names = [*names, MISSING]
        named[role] = names
    return named, cuts, color_range


def _missing_name_message(columns: list[str]) -> str:
    """Return the error of columns with a value that is the missing level's name."""
    return (
        f"列 {'、'.join(columns)} の値に欠損の水準の内部名（{MISSING!r}）と同じ"
        "文字列があるため描けない"
    )


def _facet_levels(
    spec: ScatterSpec, levels: dict[str, list], cuts: dict[str, dict]
) -> dict[str, list]:
    """Return `levels` with the row and col levels left without rows by the local filter dropped.

    Reads only the facet columns and the filter's columns, in a pass of its
    own: on 100M rows it took at most 0.55s, peaking under 2.0GB.
    A filter that keeps no rows keeps every panel. A role that draws its
    missing rows (`ddviz.shared.scatter.ScatterSpec.null_roles`) keeps its
    missing level only while a row of the filter is missing.
    """
    facets = {r: getattr(spec, r) for r in ("row", "col") if getattr(spec, r)}
    if not spec.filters or not facets:
        return levels
    keys = []
    conditions = {}
    for r, c in facets.items():
        numeric = r in spec.binned
        draws_missing = r in spec.null_roles
        if numeric:
            key = cut_index(c, cuts[r])
            valid = pl.col(c).cast(pl.Float64).is_finite()
        else:
            key = pl.col(c).cast(pl.String)
            valid = pl.col(c).is_not_null()
        if draws_missing:
            # The rows of the missing level count in it: -1 for a cut
            # column, whose levels are the cuts' indexes.
            missing = is_missing(c, numeric)
            key = pl.when(missing).then(pl.lit(-1 if numeric else MISSING)).otherwise(key)
            valid = valid | missing
        keys.append(key.alias(r))
        conditions[(c, numeric, draws_missing)] = valid
    found = (
        _scan(spec, [*facets.values(), *filter_columns(spec.filters)])
        .filter(*conditions.values(), *filter_conditions(spec.filters))
        .group_by(keys)
        .len()
        .collect(engine="streaming")
    )
    if found.height == 0:
        return levels
    kept = dict(levels)
    for role in facets:
        present = set(found[role].to_list())
        if role in spec.binned:
            present = {MISSING if i == -1 else levels[role][i] for i in present}
        kept[role] = [v for v in levels[role] if v in present]
    return kept


@dataclass(frozen=True)
class _Found:
    """What the overview found, or a view carries: the ranges, levels, cuts and boxes and lines known."""

    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    # The automatic ranges of the filter (`Aggregation.x_auto`).
    x_auto: list[tuple[float, float]]
    y_auto: list[tuple[float, float]]
    all_levels: dict[str, list]
    # The drawn levels: `all_levels` with the facets of the filter.
    levels: dict[str, list]
    cuts: dict
    color_range: tuple[float, float] | None
    axis_levels: dict[str, list[str]]
    known_boxes: list[Boxes]
    known_smooths: list[Smooths]


def _index(spec: ScatterSpec, found: _Found, role: str) -> pl.Expr:
    """Return the index of each row's level of a role among the drawn levels."""
    return role_index(
        spec, role, found.levels[role], found.all_levels[role], found.cuts.get(role)
    )


@dataclass(frozen=True)
class _Drawn:
    """What every stage after the levels shares: the spec, what was found, the panels and the expressions of each row."""

    spec: ScatterSpec
    found: _Found
    logs: _LogAxes
    # The columns of the color, symbol, row and col.
    used: list[str]
    axes: AxisGrid
    layout: GridLayout
    grid: BinGrid
    # The panel's row and col of each row, placed (`AxisGrid.place`).
    row: pl.Expr
    col: pl.Expr
    # The facet cell of a box: the drawn row and col levels.
    row_level: pl.Expr
    col_level: pl.Expr
    series: pl.Expr
    # The boxes of the markers of each symbol level (`marker_boxes`).
    marker_box: tuple

    def index(self, role: str) -> pl.Expr:
        """Return the index of each row's level of a role among the drawn levels."""
        return _index(self.spec, self.found, role)

    def box_groups(self, x_col: str) -> BoxGroups:
        """Return the boxes of the pairs of an x column."""
        return BoxGroups(
            len(self.found.levels["row"]),
            len(self.found.levels["col"]),
            len(self.found.axis_levels[x_col]),
            self.grid.n_series,
        )

    def group(self, x_col: str) -> pl.Expr:
        """Return each row's box among those of a pair: its facet cell, x level and series."""
        level = level_index(x_col, self.found.axis_levels[x_col])
        return self.box_groups(x_col).key(
            self.row_level, self.col_level, level, self.series
        )


class _RowCount:
    """The rows of the plot, counted once from the files' footers."""

    def __init__(self, spec: ScatterSpec) -> None:
        self._spec = spec
        self._rows: int | None = None

    def __call__(self) -> int:
        """Return the rows of the plot, counting them on the first call."""
        if self._rows is None:
            # Any column read from files: the one band has none.
            column = next(c for c in [*self._spec.x, *self._spec.y] if c != ONE_BAND)
            self._rows = _scan(self._spec, [column]).select(pl.len()).collect().item()
        return self._rows


def _log_auto(spec: ScatterSpec, logs: _LogAxes) -> dict[str, tuple[float, float]]:
    """Return the automatic range of each column on a log axis, as positions.

    The padded exponents of its positive values among the rows of the
    filter (`_log_axes`), or among every row when the filter leaves it
    none.

    Raises
    ------
    NoPositiveValuesError
        When a column has no positive value among every row either.
    """
    columns = list(dict.fromkeys([*spec.log_x, *spec.log_y]))
    found = {c: logs.ranges[c] for c in columns}
    left = [c for c in columns if found[c] is None]
    if left and spec.filters:
        found.update(_found_ranges(spec, left, filtered=False, log=True))
    empty = [
        (role, c)
        for role, logged in (("x", spec.log_x), ("y", spec.log_y))
        for c in logged
        if found[c] is None
    ]
    if empty:
        raise NoPositiveValuesError(no_positive_message(empty))
    return {c: padded_log_range(*found[c]) for c in columns}


def _linear_auto(
    spec: ScatterSpec, every_row: dict[str, tuple[float, float] | None] | None
) -> dict[str, tuple[float, float]]:
    """Return the automatic range of each numeric column on a linear axis.

    The padded range of its finite values among the rows of the filter,
    each column alone, in a pass of its own that reads it and the filter's
    columns; a column the filter leaves without a value takes that of every
    row (`every_row`, from the overview, or found again), and a column
    without any value the unit range (`_padded`).
    """
    columns = [
        c
        for c in dict.fromkeys(
            [
                *(c for c in spec.x if c not in spec.log_x),
                *(c for c in spec.y if c not in spec.log_y),
            ]
        )
        if c not in spec.categorical
    ]
    if not spec.filters and every_row is not None:
        found = {c: every_row[c] for c in columns}
    else:
        found = _found_ranges(spec, columns, filtered=True)
    left = [c for c in columns if found[c] is None]
    if left and spec.filters:
        if every_row is None:
            found.update(_found_ranges(spec, left, filtered=False))
        else:
            found.update({c: every_row[c] for c in left})
    return {c: _padded(*(found[c] or (None, None))) for c in columns}


def _auto_ranges(
    spec: ScatterSpec,
    log: dict[str, tuple[float, float]],
    axis_levels: dict[str, list[str]],
    every_row: dict[str, tuple[float, float] | None] | None = None,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Return the automatic range of each x and each y column (`Aggregation.x_auto`), given those of the log axes (`_log_auto`)."""
    linear = _linear_auto(spec, every_row)
    bands = {c: band_range(v) for c, v in axis_levels.items()}

    def auto(columns: list[str], logged: list[str]) -> list[tuple[float, float]]:
        return [
            bands[c] if c in bands else log[c] if c in logged else linear[c]
            for c in columns
        ]

    return auto(spec.x, spec.log_x), auto(spec.y, spec.log_y)


def _with_bands(
    columns: list[str], auto: list[list[float]], axis_levels: dict[str, list[str]]
) -> list[tuple[float, float]]:
    """Return the automatic ranges `auto` of `columns`, a categorical one spanning the bands of its levels (`axis_levels`)."""
    return [
        band_range(axis_levels[c]) if c in axis_levels else (r[0], r[1])
        for c, r in zip(columns, auto, strict=True)
    ]


def _find(
    spec: ScatterSpec,
    roles: dict[str, str | None],
    logs: _LogAxes,
    progress: Callable[[str], None],
) -> _Found:
    """Return the ranges and levels of the overview, or of a view, then the drawn facet levels.

    The overview finds the levels over every row (`_overview`) but for
    those of the rows of the local filter (`_found_levels`): the
    categorical roles of `ScatterSpec.levels_of_filter` and the categorical
    axis columns, when the spec has a filter (a categorical color column
    always, so that its limit is checked without holding the levels of an
    ID column). It spans the automatic ranges (`_auto_ranges`); a view its
    own, but for a column without one, and finds the automatic ranges
    unless it knows them, and the levels the spec asks for again
    (`View.find_levels`, `View.find_axis_levels`). A categorical axis spans
    the bands of its levels. Raises `NoPositiveValuesError` when a log axis
    has no positive value among every row.
    """
    view = spec.view
    numeric = numeric_roles(spec)
    if view is not None:
        all_levels = view.levels
        cuts = view.cuts
        color_range = view.color_range
        if color_range is not None:
            color_range = (color_range[0], color_range[1])
        axis_levels = view.axis_levels
        known_boxes = view.boxes
        known_smooths = view.smooths
        if view.find_levels or view.find_axis_levels:
            progress("filtered_levels")
            found_levels, found_axes = _found_levels(
                spec, roles, all_levels, view.find_levels, view.find_axis_levels
            )
            all_levels = {**all_levels, **found_levels}
            axis_levels = {**axis_levels, **found_axes}
        if view.x_auto is not None and view.y_auto is not None:
            x_auto = _with_bands(spec.x, view.x_auto, axis_levels)
            y_auto = _with_bands(spec.y, view.y_auto, axis_levels)
        else:
            progress("ranges")
            x_auto, y_auto = _auto_ranges(spec, _log_auto(spec, logs), axis_levels)
        x_ranges = [
            a if r is None else (r[0], r[1])
            for r, a in zip(view.x_ranges, x_auto, strict=True)
        ]
        y_ranges = [
            a if r is None else (r[0], r[1])
            for r, a in zip(view.y_ranges, y_auto, strict=True)
        ]
    else:
        # Before the levels: a log axis without a positive value is refused.
        log = _log_auto(spec, logs)
        progress("levels")
        if spec.filters:
            find = [r for r in spec.levels_of_filter() if r not in numeric]
            axes = [c for c in spec.categorical if c != ONE_BAND]
        else:
            find = ["color"] if spec.filters_color() else []
            axes = []
        # The levels of the rows of the filter are found on their own,
        # after the limits of the levels over every row.
        overview = _overview(
            spec,
            {**roles, **dict.fromkeys(find)},
            [c for c in spec.categorical if c not in axes],
        )
        all_levels, cuts = overview.levels, overview.cuts
        color_range = overview.color_range
        axis_levels = overview.axis_levels
        if find or axes:
            progress("filtered_levels")
            found_levels, found_axes = _found_levels(
                spec, roles, all_levels, find, axes
            )
            all_levels = {**all_levels, **found_levels}
            axis_levels = {**axis_levels, **found_axes}
        known_boxes = []
        known_smooths = []
        if spec.filters:
            progress("ranges")
        x_auto, y_auto = _auto_ranges(spec, log, axis_levels, overview.ranges)
        x_ranges, y_ranges = x_auto, y_auto
    scale = _color_scale(spec, progress)
    cuts = {**cuts, **_role_cuts(spec, roles, progress)}
    all_levels, cuts, color_range = _scaled(
        spec, roles, scale, all_levels, cuts, color_range
    )
    if view is not None and view.facets is not None:
        levels = {**all_levels, **view.facets}
    else:
        progress("facets")
        levels = _facet_levels(spec, all_levels, cuts)
    return _Found(
        x_ranges=x_ranges,
        y_ranges=y_ranges,
        x_auto=x_auto,
        y_auto=y_auto,
        all_levels=all_levels,
        levels=levels,
        cuts=cuts,
        color_range=color_range,
        axis_levels=axis_levels,
        known_boxes=known_boxes,
        known_smooths=known_smooths,
    )


def _drawn(spec: ScatterSpec, found: _Found, logs: _LogAxes, used: list[str]) -> _Drawn:
    """Return the panels of the drawn levels and the expressions of each row's panel and series."""
    levels = found.levels
    axes = facet_grid(
        len(levels["row"]),
        len(levels["col"]),
        len(spec.x),
        len(spec.y),
        spec.wrap,
        spec.wrap_cols,
        spec.width,
        spec.height,
        spec.margin_left,
        spec.margin_bottom,
    )
    layout = grid_layout(
        spec.width,
        spec.height,
        axes.rows,
        axes.cols,
        WRAP_GAP if spec.wrap else GAP,
        spec.margin_left,
        spec.margin_bottom,
    )
    grid = BinGrid(
        n_panels=layout.nrow * layout.ncol,
        n_series=len(levels["color"]) * len(levels["symbol"]),
        width=layout.panel_width,
        height=layout.panel_height,
    )
    row_level, col_level = _index(spec, found, "row"), _index(spec, found, "col")
    # A series is a pair of a color level and a symbol level.
    series = _index(spec, found, "color") * len(levels["symbol"]) + _index(
        spec, found, "symbol"
    )
    # The panel of a wrapped level is its index (`AxisGrid`).
    row, col = axes.place(row_level, col_level)
    marker_box = marker_boxes(
        spec.marker_shapes(levels["symbol"]), spec.marker_sizes(levels["symbol"])
    )
    return _Drawn(
        spec=spec,
        found=found,
        logs=logs,
        used=used,
        axes=axes,
        layout=layout,
        grid=grid,
        row=row,
        col=col,
        row_level=row_level,
        col_level=col_level,
        series=series,
        marker_box=marker_box,
    )


def aggregate(
    spec: ScatterSpec,
    progress: Callable[[str], None] = lambda _: None,
    selection_only: bool = False,
) -> Aggregation:
    """Aggregate a scatter plot into pixel bins and pick their representative rows.

    Each pair of an x and a y column is a panel of each facet cell
    (`ddviz.shared.layout.AxisGrid`); a row is in the panels of the pairs whose x
    and y it has; a wrapped spec lays its col levels out in rows instead.
    The pairs are aggregated one after another in this
    process. A panel leaves out
    rows with a null or non-finite x or y, and for a view, rows outside the
    ranges of its columns; every panel leaves out rows with a null color,
    symbol, row or col, and rows the local filter leaves out (`ddviz.compute.rowfilter`).
    What the plot draws follows the rows of the local filter: the overview
    finds the levels of the categorical roles and axes among them
    (`_found_levels`; a color or symbol column that keeps its levels has
    those of every row, `_overview`), and spans the automatic ranges of its
    filter (`Aggregation.x_auto`); a view takes the levels from the spec,
    but for those of another filter it finds again, and its ranges but for
    those it leaves to the automatic ones. With a filter, the facet levels
    left without rows are then dropped, with their panels
    (`_facet_levels`), unless the view already knows the facet levels of
    its filter.

    With a selection, the selected rows are also aggregated into bins of
    their own, in every panel (`ddviz.compute.selection.selection_filter`).

    Parameters
    ----------
    spec : ScatterSpec
        What to aggregate.
    progress : callable
        Called with the name of each stage as it starts.
    selection_only : bool
        Aggregate only the selection, for the layer of a result already
        drawn; the spec must have a view (its levels and ranges) and a
        selection.

    Returns
    -------
    Aggregation
        The bins.

    Raises
    ------
    ValueError
        When a column has more levels than a role it is on allows
        (`_check_levels`); `FilteredLevelsError` for a column past a limit
        among the rows of the filter (`_found_levels`).
    """
    roles = {
        "color": spec.color,
        "symbol": spec.symbol,
        "row": spec.row,
        "col": spec.col,
    }
    used = list(dict.fromkeys(c for c in roles.values() if c is not None))

    # A selection's layer keeps the ranges of its result.
    logs = _LogAxes({}, []) if selection_only else _log_axes(spec)
    found = _find(spec, roles, logs, progress)
    drawn = _drawn(spec, found, logs, used)
    boxes = _all_boxes(drawn, progress)
    boxes_of = {(b.x, b.y): b for b in boxes}
    smooths = _all_smooths(drawn, progress)
    lines = line_values = None
    if not selection_only:
        lines, line_values = _lines(drawn, progress)
    n_rows = _RowCount(spec)

    bins = pile_bins = None
    piles: list[Piles] = []
    if not selection_only:
        progress("bins")
        bins, pile_bins, piles = _all_pairs(
            drawn,
            boxes_of,
            n_rows,
            filter_conditions(spec.filters),
            filter_columns(spec.filters),
            True,
        )
        n_piles = sum(p.piles.height for p in piles)
        if n_piles > MAX_PILES:
            raise ValueError(
                f"同じ座標に重なる点の集まりが {n_piles:,} 個あり、上限の "
                f"{MAX_PILES:,} 個を超えるため描けない。フィルタで行を絞るか、"
                "別の列を使う"
            )
        progress("rows")
        hover = list(dict.fromkeys(spec.hover))
        rows = (
            _scan(spec, hover, INDEX)
            .join(bins.lazy().select(INDEX), on=INDEX, how="semi")
            .select(INDEX, *hover)
            .collect(engine="streaming")
        )
        bins = bins.join(rows, on=INDEX, how="left", maintain_order="left")
    selected = selected_rows = selected_piles = None
    if spec.selection is not None:
        progress("selection")
        conditions = selection_filter(spec, INDEX)
        columns = selection_columns(spec)
        selected, selected_piles, _ = _all_pairs(
            drawn, boxes_of, n_rows, conditions, columns
        )
        if spec.gradient:
            # The top selected row of each bin colors it, as in the result.
            colors = (
                _scan(spec, [spec.color], INDEX)
                .join(selected.lazy().select(INDEX), on=INDEX, how="semi")
                .collect(engine="streaming")
            )
            selected = selected.join(
                colors, on=INDEX, how="left", maintain_order="left"
            )
            selected = selected.select(KEY, COUNT, INDEX, spec.color)
        else:
            selected = selected.select(KEY, COUNT)
        selected_rows = (
            _scan(spec, columns, INDEX)
            .filter(*conditions)
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
    return Aggregation(
        grid=drawn.grid,
        layout=drawn.layout,
        axes=drawn.axes,
        x_ranges=found.x_ranges,
        y_ranges=found.y_ranges,
        x_auto=found.x_auto,
        y_auto=found.y_auto,
        levels=found.levels,
        all_levels=found.all_levels,
        bins=bins,
        selected=selected,
        selected_rows=selected_rows,
        selected_piles=selected_piles,
        cuts=found.cuts,
        color_range=found.color_range,
        axis_levels=found.axis_levels,
        piles=piles,
        pile_bins=pile_bins,
        boxes=boxes,
        smooths=smooths,
        nonpositive=logs.nonpositive,
        lines=lines,
        line_values=line_values,
    )


def _all_boxes(drawn: _Drawn, progress: Callable[[str], None]) -> list[Boxes]:
    """Return the box plots of each pair that has them: those the view knows, the others over the drawn rows that pass the local filter."""
    spec = drawn.spec
    known_boxes_of = {(b.x, b.y): b for b in drawn.found.known_boxes}
    boxes = []
    pairs_with_boxes = spec.box_pairs()
    if pairs_with_boxes:
        progress("boxes")
    for y_col in spec.y:
        for x_col in spec.x:
            if (x_col, y_col) not in pairs_with_boxes:
                continue
            if (x_col, y_col) in known_boxes_of:
                boxes.append(known_boxes_of[x_col, y_col])
                continue
            value = pl.col(y_col).cast(pl.Float64)
            frame = (
                _scan(spec, _kept_columns(spec, [x_col, y_col, *drawn.used]))
                .filter(
                    pl.col(x_col).is_not_null(),
                    # On a log axis, the box of the positive values.
                    on_axis(value, y_col in spec.log_y),
                    *_kept(spec),
                )
                .select(drawn.group(x_col).alias(GROUP), value.alias(VALUE))
            )
            boxes.append(
                _boxes(x_col, y_col, box_stats(frame), drawn.box_groups(x_col))
            )
    return boxes


def _all_smooths(drawn: _Drawn, progress: Callable[[str], None]) -> list[Smooths]:
    """Return the smoothing lines of each pair that has them: those the view knows, the others fitted again (`_smooths`)."""
    spec = drawn.spec
    known_smooths_of = {(k.x, k.y): k for k in drawn.found.known_smooths}
    smooths = []
    pairs_with_smooths = spec.smooth_pairs()
    if pairs_with_smooths:
        progress("smooth")
    for y_col in spec.y:
        for xi, x_col in enumerate(spec.x):
            if (x_col, y_col) not in pairs_with_smooths:
                continue
            if (x_col, y_col) in known_smooths_of:
                smooths.append(known_smooths_of[x_col, y_col])
                continue
            # The automatic range of the filter, the overview's, whose bins
            # a view's lines keep: a view with another filter fits them
            # again over its own. On a log axis, the lines are fitted over
            # the values themselves of the positive rows (the page draws
            # them at their log10).
            bounds = values(drawn.found.x_auto[xi], x_col in spec.log_x)
            smooths.append(_smooths(drawn, x_col, y_col, bounds))
    return smooths


def _pair(
    drawn: _Drawn,
    boxes_of: dict[tuple[str, str], Boxes],
    n_rows: _RowCount,
    xi: int,
    yj: int,
    extra: list[pl.Expr],
    extra_columns: list[str],
) -> pl.DataFrame:
    """Return the bins of the panels of one pair of axis columns, of the rows `extra` keeps."""
    spec, grid, found = drawn.spec, drawn.grid, drawn.found
    x_col, y_col = spec.x[xi], spec.y[yj]
    outlier = pl.lit(True)
    lines_only = (x_col, y_col) in spec.line_pairs() and not (
        (x_col, y_col) in spec.box_pairs()
    )
    if lines_only or spec.draws_points(x_col, y_col):
        # Two numeric axes: the stacks place the points of a categorical
        # one. A pair of lines without points keeps the bins of its rows
        # for the hover and the selection, a categorical x's at the centers
        # of its bands; its images leave them out
        # (`ddviz.compute.tasks.plot`), and it has no piles.
        if x_col in spec.categorical:
            x = level_index(x_col, found.axis_levels[x_col]).cast(pl.Float64)
        else:
            x = pl.col(x_col).cast(pl.Float64)
        y = pl.col(y_col).cast(pl.Float64)
    elif (x_col, y_col) in spec.smooth_pairs():
        # Only the smoothing lines: no row is drawn as a point.
        x = pl.col(x_col).cast(pl.Float64)
        y = pl.col(y_col).cast(pl.Float64)
        outlier = pl.lit(False)
    else:
        # Only the outliers, spread in the slot of their series' box.
        y = pl.col(y_col).cast(pl.Float64)
        x = outlier_position(
            x_col,
            found.axis_levels[x_col],
            drawn.series,
            grid.n_series,
            jitter(INDEX, JITTER_X),
        )
        groups = drawn.box_groups(x_col)
        stats = _group_stats(boxes_of[x_col, y_col], groups)
        outlier = is_outlier(y, drawn.group(x_col), fences(stats, groups.size))
    # Positions on the axes: the log10 of a value on a log axis; the
    # outliers above are of the values themselves.
    x = position(x, x_col in spec.log_x)
    y = position(y, y_col in spec.log_y)
    key = grid.pack(
        drawn.axes.panel(drawn.row, drawn.col, xi, yj),
        drawn.series,
        _bin_expr(y, found.y_ranges[yj], grid.height),
        _bin_expr(x, found.x_ranges[xi], grid.width),
    )
    valid = drawn_conditions(spec)

    def query(rows: pl.LazyFrame) -> pl.LazyFrame:
        return (
            rows.filter(
                within(x, *found.x_ranges[xi]),
                within(y, *found.y_ranges[yj]),
                *valid,
                *extra,
            )
            # The group, like the key, reads the drawn facet levels: only
            # the rows kept above have one.
            .select(key.alias(KEY), pl.col(INDEX), outlier.alias(_OUTLIER))
            .filter(pl.col(_OUTLIER))
            .group_by(KEY)
            .agg(pl.len().alias(COUNT), pl.col(INDEX).max())
        )

    # The slices are of the scan, before the filter: each holds the same
    # rows whatever the filter keeps.
    return _binned(
        _scan(spec, [x_col, y_col, *drawn.used, *extra_columns], INDEX),
        n_rows(),
        query,
    )


def _stacked(
    drawn: _Drawn,
    xi: int,
    yj: int,
    extra: list[pl.Expr],
    extra_columns: list[str],
    piles: bool,
) -> tuple[pl.DataFrame, pl.DataFrame, Piles | None]:
    """Return the bins, the bins of the piles and the piles of a pair with a categorical axis drawing points (`ddviz.compute.stacked`)."""
    spec, grid, axes, levels = drawn.spec, drawn.grid, drawn.axes, drawn.found.levels
    x_ranges, y_ranges = drawn.found.x_ranges, drawn.found.y_ranges
    categorical = set(spec.categorical)
    x_col, y_col = spec.x[xi], spec.y[yj]
    x = Axis(x_col in categorical, *x_ranges[xi], grid.width, x_col in spec.log_x)
    y = Axis(y_col in categorical, *y_ranges[yj], grid.height, y_col in spec.log_y)
    columns = _kept_columns(spec, [x_col, y_col, *drawn.used, *extra_columns])
    n_col = len(levels["col"])
    panels = []
    for cell in range(len(levels["row"]) * n_col):
        r, c = axes.place(*divmod(cell, n_col))
        panels.append(axes.panel(r, c, xi, yj))
    frame, coordinates = stack_frame(
        {c: spec.files[c] for c in dict.fromkeys(columns)},
        INDEX,
        x_col,
        y_col,
        x,
        y,
        drawn.found.axis_levels,
        _kept(spec),
        drawn.row_level * n_col + drawn.col_level,
        panels,
        drawn.series,
        drawn.index("symbol"),
        drawn.marker_box,
        extra,
    )
    found = stacked_bins(
        frame,
        x,
        y,
        grid,
        INDEX,
        coordinates,
        spec.color if spec.gradient else None,
        piles,
        tuple(dict.fromkeys([x_col, y_col])),
    )

    bins = found.bins.select(
        KEY,
        pl.col(ROWS).cast(pl.UInt32).alias(COUNT),
        pl.col(TOP).cast(pl.get_index_type()).alias(INDEX),
    )
    in_piles = found.pile_bins.select(KEY, pl.col(ROWS).cast(pl.UInt32).alias(COUNT))
    if not piles:
        return bins, in_piles, None
    return bins, in_piles, Piles(x_col, y_col, found.piles, found.pile_series)


def _all_pairs(
    drawn: _Drawn,
    boxes_of: dict[tuple[str, str], Boxes],
    n_rows: _RowCount,
    extra: list[pl.Expr],
    extra_columns: list[str],
    piles: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame, list[Piles]]:
    """Return the bins of every pair, the bins of their piles and, when asked, their piles."""
    spec = drawn.spec
    categorical = set(spec.categorical)
    # One query per pair, one after another: the pairs' panels differ, so
    # their keys do too. One query over all pairs was about 10% faster but
    # its peak grew with the pairs (9 pairs of 100M rows: 9.0GB against 4.0GB).
    found = []
    pile_bins = [pl.DataFrame(schema={KEY: pl.Int64, COUNT: pl.UInt32})]
    drawn_piles = []
    for yj in range(drawn.axes.ny):
        for xi in range(drawn.axes.nx):
            x_col, y_col = spec.x[xi], spec.y[yj]
            if {x_col, y_col} & categorical and spec.draws_points(x_col, y_col):
                bins, in_piles, pair_piles = _stacked(
                    drawn, xi, yj, extra, extra_columns, piles
                )
                found.append(bins)
                pile_bins.append(in_piles)
                if pair_piles is not None:
                    drawn_piles.append(pair_piles)
            else:
                found.append(
                    _pair(drawn, boxes_of, n_rows, xi, yj, extra, extra_columns)
                )
    return pl.concat(found).sort(KEY), pl.concat(pile_bins).sort(KEY), drawn_piles


def _kept(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions of the rows drawn that pass the local filter: `drawn_conditions` then `filter_conditions`."""
    return [*drawn_conditions(spec), *filter_conditions(spec.filters)]


def _kept_columns(spec: ScatterSpec, columns: list[str]) -> list[str]:
    """Return `columns` then the columns the local filter reads."""
    return [*columns, *filter_columns(spec.filters)]


def _lines(
    drawn: _Drawn, progress: Callable[[str], None]
) -> tuple[LinePixels, pl.Series | None]:
    """Return the pixels of the lines of each pair, over the drawn rows that pass the local filter (`ddviz.compute.lines`).

    A pair's series are its facet cells by color level; a gradient's color
    splits none, and the color of each row is kept instead. A categorical
    x joins the centers of its bands, in the order of its levels. The rows
    are aggregated (`ddviz.shared.scatter.ScatterSpec.line_aggregation`)
    before the view's ranges, so that a zoom keeps the lines as they are.
    """
    spec, grid = drawn.spec, drawn.grid
    pairs = spec.line_pairs()
    if not pairs:
        return LinePixels.empty(), None
    progress("lines")
    categorical = set(spec.categorical)
    color = drawn.index("color")
    # A gradient's lines are one series a panel; the others', one a color level.
    n_series = 1 if spec.gradient else len(drawn.found.levels["color"])
    parts, values = [], []
    offset = 0
    for yj, y_col in enumerate(spec.y):
        for xi, x_col in enumerate(spec.x):
            if (x_col, y_col) not in pairs:
                continue
            rows = _scan(
                spec, _kept_columns(spec, [x_col, y_col, *drawn.used]), INDEX
            ).filter(*_kept(spec))
            frame = line_frame(
                rows,
                x_col,
                y_col,
                drawn.axes.panel(drawn.row, drawn.col, xi, yj),
                pl.lit(0) if spec.gradient else color,
                n_series,
                color,
                INDEX,
                pl.col(spec.color) if spec.gradient else None,
                drawn.found.axis_levels.get(x_col) if x_col in categorical else None,
                spec.line_aggregation,
                y_col in spec.log_y,
                # Not streaming: its sort peaked at 1.34GB on 10M rows,
                # against 0.90GB in memory (`docs/spec.md`, "点を結ぶ線").
            ).collect()
            found = line_pixels(
                frame,
                x_col in spec.log_x,
                y_col in spec.log_y,
                drawn.found.x_ranges[xi],
                drawn.found.y_ranges[yj],
                grid.width,
                grid.height,
                n_series,
            )
            parts.append(LinePixels(found.pixel, found.layer, found.rank + offset))
            if spec.gradient:
                values.append(frame[LINE_VALUE])
            offset += frame.height
    return LinePixels.concat(parts), pl.concat(values) if values else None


def _smooths(
    drawn: _Drawn, x_col: str, y_col: str, bounds: tuple[float, float]
) -> Smooths:
    """Return the smoothing lines of a pair over the drawn rows that pass the local filter, one per facet cell and series (`ddviz.compute.smooth`)."""
    spec = drawn.spec
    x = pl.col(x_col).cast(pl.Float64)
    y = pl.col(y_col).cast(pl.Float64)
    # On a log axis, only the positive values have a place to be drawn.
    frame = _scan(spec, _kept_columns(spec, [x_col, y_col, *drawn.used])).filter(
        on_axis(x, x_col in spec.log_x),
        on_axis(y, y_col in spec.log_y),
        *_kept(spec),
    )
    n_col = len(drawn.found.levels["col"])
    cells = drawn.row_level * n_col + drawn.col_level
    bins = bin_query(frame, x, y, cells, drawn.series, bounds).collect(
        engine="streaming"
    )
    lines = [
        [cell // n_col, cell % n_col, s, xs, ys]
        for cell, s, xs, ys in fit_lines(bins, spec.smooth)
    ]
    return Smooths(x=x_col, y=y_col, lines=lines)


def _boxes(x: str, y: str, stats: dict[int, list[float]], groups: BoxGroups) -> Boxes:
    """Return the box plots of a pair from the boxes of its groups (`_Drawn.group`)."""
    rows = [[*groups.parts(g), *stats[g]] for g in sorted(stats)]
    return Boxes(x=x, y=y, stats=rows)


def _group_stats(boxes: Boxes, groups: BoxGroups) -> dict[int, list[float]]:
    """Return the boxes of a pair by their group, as `ddviz.compute.boxes.box_stats` gives them."""
    return {
        groups.key(row, col, level, series): stats
        for row, col, level, series, *stats in (
            [int(v) for v in b[:4]] + b[4:] for b in boxes.stats
        )
    }
