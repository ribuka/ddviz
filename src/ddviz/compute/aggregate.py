"""Pixel-bin aggregation of a scatter plot with one representative row per bin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

from ddviz.compute.axisposition import on_axis, position, within
from ddviz.compute.bands import JITTER_X, jitter, level_index
from ddviz.compute.boxes import (
    GROUP,
    VALUE,
    BoxGroups,
    box_stats,
    fences,
    is_outlier,
    outlier_position,
)
from ddviz.compute.found import Found, find
from ddviz.compute.foundranges import LogAxes, log_axes
from ddviz.compute.lines import VALUE as LINE_VALUE
from ddviz.compute.lines import LinePixels, line_frame, line_pixels
from ddviz.compute.missing import (
    drawn_conditions,
    role_index,
)
from ddviz.compute.plotscan import plot_scan
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.selection import selection_columns, selection_filter
from ddviz.compute.smooth import bin_query, fit_lines
from ddviz.compute.stacked import ROWS, TOP, marker_boxes, stack_frame, stacked_bins
from ddviz.compute.stacks import pair_axes
from ddviz.shared.axisscale import (
    values,
)
from ddviz.shared.keys import BinGrid
from ddviz.shared.layout import AxisGrid, GridLayout
from ddviz.shared.scatter import (
    ONE_BAND,
    Boxes,
    ScatterSpec,
    Smooths,
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
        pass the local filter, padded (`ddviz.compute.foundranges.padded`, `padded_log_range`); a
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
        (`ddviz.compute.foundcolor.color_scale`).
    color_range : tuple of float or None
        For a gradient, the finite minimum and maximum of the color column
        among the rows of the local filter (`ddviz.compute.foundcolor.color_scale`); the bins then
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
        The rows, with their row index `INDEX` (`ddviz.compute.plotscan.plot_scan`): a slice keeps the
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


def _index(spec: ScatterSpec, found: Found, role: str) -> pl.Expr:
    """Return the index of each row's level of a role among the drawn levels."""
    return role_index(
        spec, role, found.levels[role], found.all_levels[role], found.cuts.get(role)
    )


@dataclass(frozen=True)
class _Drawn:
    """What every stage after the levels shares: the spec, what was found, the panels and the expressions of each row."""

    spec: ScatterSpec
    found: Found
    logs: LogAxes
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
            self._rows = plot_scan(self._spec, [column]).select(pl.len()).collect().item()
        return self._rows


def _drawn(spec: ScatterSpec, found: Found, logs: LogAxes, used: list[str]) -> _Drawn:
    """Return the panels of the drawn levels and the expressions of each row's panel and series."""
    levels = found.levels
    axes, layout = spec.facet_layout(levels)
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
    (`ddviz.compute.foundlevels.found_levels`; a color or symbol column that keeps its levels has
    those of every row, `ddviz.compute.foundlevels.overview`), and spans the automatic ranges of its
    filter (`Aggregation.x_auto`); a view takes the levels from the spec,
    but for those of another filter it finds again, and its ranges but for
    those it leaves to the automatic ones. With a filter, the facet levels
    left without rows are then dropped, with their panels
    (`ddviz.compute.foundlevels.facet_levels`), unless the view already knows the facet levels of
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
        (`ddviz.compute.foundlevels.check_levels`); `FilteredLevelsError` for a column past a limit
        among the rows of the filter (`ddviz.compute.foundlevels.found_levels`).
    """
    roles = {
        "color": spec.color,
        "symbol": spec.symbol,
        "row": spec.row,
        "col": spec.col,
    }
    used = list(dict.fromkeys(c for c in roles.values() if c is not None))

    # A selection's layer keeps the ranges of its result.
    logs = LogAxes({}, []) if selection_only else log_axes(spec)
    found = find(spec, roles, logs, progress)
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
            plot_scan(spec, hover, INDEX)
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
                plot_scan(spec, [spec.color], INDEX)
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
            plot_scan(spec, columns, INDEX)
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
                plot_scan(spec, _kept_columns(spec, [x_col, y_col, *drawn.used]))
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
        plot_scan(spec, [x_col, y_col, *drawn.used, *extra_columns], INDEX),
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
    x_col, y_col = spec.x[xi], spec.y[yj]
    x, y = pair_axes(
        spec, x_col, y_col, x_ranges[xi], y_ranges[yj], grid.width, grid.height
    )
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
            rows = plot_scan(
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
    frame = plot_scan(spec, _kept_columns(spec, [x_col, y_col, *drawn.used])).filter(
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
