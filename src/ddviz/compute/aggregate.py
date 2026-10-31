"""Pixel-bin aggregation of a scatter plot with one representative row per bin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

from ddviz.compute.bands import (
    JITTER_X,
    band_range,
    count_spread,
    jitter,
    level_index,
    pair_positions,
)
from ddviz.compute.boxes import (
    GROUP,
    VALUE,
    box_stats,
    fences,
    is_outlier,
    outlier_position,
)
from ddviz.compute.cuts import cut_index, cut_labels, find_cuts
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.compute.scan import scan_columns
from ddviz.compute.selection import (
    drawn_conditions,
    numeric_roles,
    selection_columns,
    selection_filter,
)
from ddviz.compute.smooth import bin_query, fit_lines
from ddviz.shared.keys import BinGrid
from ddviz.shared.layout import (
    GAP,
    WRAP_GAP,
    AxisGrid,
    GridLayout,
    facet_grid,
    grid_layout,
)
from ddviz.shared.scatter import ONE_BAND, Boxes, ScatterSpec, Smooths, Spread

KEY = "__key"
COUNT = "__n"
INDEX = "__idx"
# Whether a row is an outlier of its box plot, or any row of a pair whose
# panels draw points.
_OUTLIER = "__outlier"

# Margin added on each side of the data range, as a fraction of the range.
RANGE_PADDING = 0.02


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
        ``x_ranges[xi]``.
    levels : dict
        Levels of the ``"color"``, ``"overlay"``, ``"row"`` and ``"col"``
        roles as text, in index order, as drawn: the series of every row
        (pairs of a color and an overlay level), and the facet levels
        that have rows passing the local filter; a role without a column has
        the single level None.
    all_levels : dict
        Levels of the roles over every row, the local filter aside
        (`ddviz.shared.scatter.View.levels`).
    cuts : dict
        Cuts of each role in the spec's ``binned`` (`ddviz.compute.cuts`).
    color_range : tuple of float or None
        For a gradient, the finite minimum and maximum of the color column
        over every row; the bins then also hold the color of their
        representative row, and so do the selected bins.
    axis_levels : dict
        Levels of each categorical axis column over every row, as text: the
        bands of its axis (`ddviz.compute.bands`).
    spreads : list of Spread
        How the points spread in the bands of each pair of axis columns
        with a categorical axis whose panels draw points.
    boxes : list of Boxes
        Box plots of each pair of `ddviz.shared.scatter.ScatterSpec.box_pairs`.
    smooths : list of Smooths
        Smoothing lines of each pair of
        `ddviz.shared.scatter.ScatterSpec.smooth_pairs`.
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
    """

    grid: BinGrid
    layout: GridLayout
    axes: AxisGrid
    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    levels: dict[str, list]
    all_levels: dict[str, list]
    bins: pl.DataFrame | None
    selected: pl.DataFrame | None = None
    selected_rows: int | None = None
    cuts: dict[str, dict] = field(default_factory=dict)
    color_range: tuple[float, float] | None = None
    axis_levels: dict[str, list[str]] = field(default_factory=dict)
    spreads: list[Spread] = field(default_factory=list)
    boxes: list[Boxes] = field(default_factory=list)
    smooths: list[Smooths] = field(default_factory=list)


def _padded(lo: float | None, hi: float | None) -> tuple[float, float]:
    """Return a data range with a margin, or a unit range around a constant."""
    if lo is None or hi is None:
        return (0.0, 1.0)
    if lo == hi:
        return (lo - 0.5, hi + 0.5)
    pad = (hi - lo) * RANGE_PADDING
    return (lo - pad, hi + pad)


def _bin_expr(value: pl.Expr, bounds: tuple[float, float], n: int) -> pl.Expr:
    """Return the bin index of a position (`ddviz.compute.bands.pair_positions`) over `bounds` split into `n` bins."""
    lo, hi = bounds
    scaled = (value - lo) * (n / (hi - lo))
    return scaled.floor().clip(0, n - 1).cast(pl.Int64)


def _index_expr(column: str | None, levels: list) -> pl.Expr:
    """Return the level index of a categorical column by its text, or 0 without a column."""
    if column is None:
        return pl.lit(0, pl.Int64)
    return level_index(column, levels)


def _scan(
    spec: ScatterSpec, columns: list[str], row_index: str | None = None
) -> pl.LazyFrame:
    """Return a scan of only `columns` of the plot.

    Each query gets its own scan: queries in one `collect_all` sharing a scan
    followed by a ``select`` made the streaming engine peak at about 6.7GB on
    100M rows, against about 1.2GB with separate scans.
    """
    return scan_columns({c: spec.files[c] for c in dict.fromkeys(columns)}, row_index)


def _range_query(spec: ScatterSpec, column: str) -> pl.LazyFrame:
    """Return the query of the finite minimum and maximum of a numeric column."""
    value = pl.col(column).cast(pl.Float64)
    finite = value.filter(value.is_finite())
    return _scan(spec, [column]).select(
        finite.min().alias("min"), finite.max().alias("max")
    )


@dataclass(frozen=True)
class _Overview:
    """What the overview finds over every row (`_overview`)."""

    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    levels: dict[str, list]
    cuts: dict[str, dict]
    color_range: tuple[float, float] | None
    axis_levels: dict[str, list[str]]


def _overview(spec: ScatterSpec, roles: dict[str, str | None]) -> _Overview:
    """Return the padded data range of each axis column and the levels of each role.

    The ranges and the levels of the categorical roles and axis columns
    come in one pass, the cuts of each binned role in passes of their own
    (`ddviz.compute.cuts.find_cuts`). A categorical axis column spans its
    bands (`ddviz.compute.bands.band_range`).
    """
    numeric = [
        c for c in dict.fromkeys([*spec.x, *spec.y]) if c not in spec.categorical
    ]
    used = list(
        dict.fromkeys(
            [
                *(c for r, c in roles.items() if c and r not in numeric_roles(spec)),
                *spec.categorical,
            ]
        )
    )
    # The one band has its level without reading the data.
    used = [c for c in used if c != ONE_BAND]
    gradient = [spec.color] if spec.gradient else []
    # Levels and ranges come from the unfiltered scan: a row filter on the
    # same pass made the streaming engine peak at about 6.5GB on 100M rows,
    # against about 1.1GB without it. The range of an axis column covers all
    # its rows, so that all its panels share one axis.
    found = pl.collect_all(
        [
            *[_range_query(spec, c) for c in numeric],
            *[_scan(spec, [c]).group_by(pl.col(c).cast(pl.String)).len() for c in used],
            *[_range_query(spec, c) for c in gradient],
        ],
        engine="streaming",
    )
    color_range = None
    if gradient:
        lo, hi = found.pop().row(0)
        color_range = (0.0, 1.0) if lo is None else (lo, hi)
    ranges = {c: _padded(*f.row(0)) for c, f in zip(numeric, found, strict=False)}
    column_levels = {
        c: sorted(f[c].drop_nulls().to_list())
        for c, f in zip(used, found[len(numeric) :], strict=True)
    }
    if ONE_BAND in spec.categorical:
        column_levels[ONE_BAND] = [""]
    axis_levels = {c: column_levels[c] for c in spec.categorical}
    ranges.update({c: band_range(v) for c, v in axis_levels.items()})
    x_ranges = [ranges[c] for c in spec.x]
    y_ranges = [ranges[c] for c in spec.y]
    many = {c: len(v) for c, v in column_levels.items() if len(v) > spec.max_levels}
    if many:
        raise ValueError(
            f"too many levels (at most {spec.max_levels}): "
            + ", ".join(f"{c} has {n}" for c, n in many.items())
        )
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
    return _Overview(x_ranges, y_ranges, levels, cuts, color_range, axis_levels)


def _facet_levels(
    spec: ScatterSpec, levels: dict[str, list], cuts: dict[str, dict]
) -> dict[str, list]:
    """Return `levels` with the row and col levels left without rows by the local filter dropped.

    Reads only the facet columns and the filter's columns, in a pass of its
    own: on 100M rows it took at most 0.55s, peaking under 2.0GB.
    A filter that keeps no rows keeps every panel.
    """
    facets = {r: getattr(spec, r) for r in ("row", "col") if getattr(spec, r)}
    if not spec.filters or not facets:
        return levels
    numeric = {c for r, c in facets.items() if r in spec.binned}
    keys = [
        (
            cut_index(c, cuts[r]) if r in spec.binned else pl.col(c).cast(pl.String)
        ).alias(r)
        for r, c in facets.items()
    ]
    found = (
        _scan(spec, [*facets.values(), *filter_columns(spec.filters)])
        .filter(
            *[
                pl.col(c).cast(pl.Float64).is_finite()
                if c in numeric
                else pl.col(c).is_not_null()
                for c in dict.fromkeys(facets.values())
            ],
            *filter_conditions(spec.filters),
        )
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
            present = {levels[role][i] for i in present}
        kept[role] = [v for v in levels[role] if v in present]
    return kept


def _spreads(
    spec: ScatterSpec,
    axis_levels: dict[str, list[str]],
    known: list[Spread],
    ranges: dict[str, tuple[float, float]],
) -> list[Spread]:
    """Return the spread of each pair of axis columns with a categorical axis whose panels draw points.

    A spread with widths in `known` is kept; the others are counted over the
    drawn rows that pass the local filter (`ddviz.compute.bands.count_spread`),
    the numeric axis cut over the bounds a known spread has, else over its
    range in `ranges` (the overview's). On 100M rows and 20 levels, counting
    took about 0.6s.
    """
    categorical = set(spec.categorical)
    known_by_pair = {(k.x, k.y): k for k in known}
    pairs = dict.fromkeys(
        (x, y)
        for y in spec.y
        for x in spec.x
        if {x, y} & categorical and spec.draws_points(x, y)
    )
    spreads = []
    for x, y in pairs:
        old = known_by_pair.get((x, y))
        if old is not None and old.widths is not None:
            spreads.append(old)
            continue
        both = x in categorical and y in categorical
        other = None if both else (y if x in categorical else x)
        if old is not None:
            bounds = old.bounds
        else:
            bounds = None if other is None else list(ranges[other])
        drawn = [
            pl.col(c).is_not_null()
            if c in categorical
            else pl.col(c).cast(pl.Float64).is_finite()
            for c in (x, y)
        ]
        frame = _scan(
            spec,
            [x, y, *(c for c in (spec.color, spec.overlay, spec.row, spec.col) if c)]
            + filter_columns(spec.filters),
        ).filter(*drawn, *drawn_conditions(spec), *filter_conditions(spec.filters))
        spreads.append(count_spread(frame, x, y, categorical, axis_levels, bounds))
    return spreads


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
    overlay, row or col, and rows the local filter leaves out (`ddviz.compute.rowfilter`).
    The overview finds the levels and the data ranges first, over every
    row, so that the filter changes neither the series nor the axes; a view
    takes them from the spec. With a filter, the facet levels left without
    rows are then dropped, with their panels (`_facet_levels`), unless the
    view already knows the facet levels of its filter.

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
        When the color, overlay, row or col column has more than `ScatterSpec.max_levels` levels.
    """
    roles = {
        "color": spec.color,
        "overlay": spec.overlay,
        "row": spec.row,
        "col": spec.col,
    }
    used = list(dict.fromkeys(c for c in roles.values() if c is not None))

    if spec.view is not None:
        x_ranges = [(lo, hi) for lo, hi in spec.view.x_ranges]
        y_ranges = [(lo, hi) for lo, hi in spec.view.y_ranges]
        all_levels = spec.view.levels
        cuts = spec.view.cuts
        color_range = spec.view.color_range
        if color_range is not None:
            color_range = (color_range[0], color_range[1])
        axis_levels = spec.view.axis_levels
        known = spec.view.spreads
        known_boxes = spec.view.boxes
        known_smooths = spec.view.smooths
    else:
        progress("levels")
        found = _overview(spec, roles)
        x_ranges, y_ranges = found.x_ranges, found.y_ranges
        all_levels, cuts, color_range = found.levels, found.cuts, found.color_range
        axis_levels = found.axis_levels
        known = []
        known_boxes = []
        known_smooths = []
    if spec.view is not None and spec.view.facets is not None:
        levels = {**all_levels, **spec.view.facets}
    else:
        progress("facets")
        levels = _facet_levels(spec, all_levels, cuts)

    if spec.categorical:
        progress("spread")
    ranges = dict(zip(spec.x, x_ranges, strict=True)) | dict(
        zip(spec.y, y_ranges, strict=True)
    )
    spreads = _spreads(spec, axis_levels, known, ranges) if spec.categorical else []
    spread_of = {(k.x, k.y): k for k in spreads}

    axes = facet_grid(
        len(levels["row"]),
        len(levels["col"]),
        len(spec.x),
        len(spec.y),
        spec.wrap,
        spec.wrap_cols,
        spec.width,
        spec.height,
    )
    layout = grid_layout(
        spec.width, spec.height, axes.rows, axes.cols, WRAP_GAP if spec.wrap else GAP
    )
    grid = BinGrid(
        n_panels=layout.nrow * layout.ncol,
        n_series=len(levels["color"]) * len(levels["overlay"]),
        width=layout.panel_width,
        height=layout.panel_height,
    )

    def index(role: str) -> pl.Expr:
        """Return the index of each row's level of a role among the drawn levels."""
        if role in spec.binned:
            kept = [all_levels[role].index(v) for v in levels[role]]
            return cut_index(roles[role], cuts[role], kept)
        if role == "color" and spec.gradient:
            return pl.lit(0, pl.Int64)
        return _index_expr(roles[role], levels[role])

    row, col = index("row"), index("col")
    # A series is a pair of a color level and an overlay level.
    series = index("color") * len(levels["overlay"]) + index("overlay")
    # The facet cell of a box: the drawn row and col levels.
    row_level, col_level = row, col
    if spec.wrap:
        # The panel of a wrapped level is its index (`AxisGrid`).
        row, col = col // axes.ncol, col % axes.ncol
    valid = drawn_conditions(spec)

    def group(x_col: str) -> pl.Expr:
        """Return each row's box among those of a pair: its facet cell, x level and series."""
        cell = row_level * len(levels["col"]) + col_level
        level = level_index(x_col, axis_levels[x_col])
        return (cell * len(axis_levels[x_col]) + level) * grid.n_series + series

    known_boxes_of = {(b.x, b.y): b for b in known_boxes}
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
                _scan(spec, [x_col, y_col, *used, *filter_columns(spec.filters)])
                .filter(
                    pl.col(x_col).is_not_null(),
                    value.is_finite(),
                    *valid,
                    *filter_conditions(spec.filters),
                )
                .select(group(x_col).alias(GROUP), value.alias(VALUE))
            )
            boxes.append(
                _boxes(x_col, y_col, box_stats(frame), levels, axis_levels, grid)
            )
    boxes_of = {(b.x, b.y): b for b in boxes}

    known_smooths_of = {(k.x, k.y): k for k in known_smooths}
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
            # The overview's range, whose bins a view's lines keep: a view
            # with another filter fits them again over the whole range.
            if spec.view is None:
                bounds = x_ranges[xi]
            else:
                bounds = _overview_range(spec, x_col)
            smooths.append(
                _smooths(
                    spec,
                    x_col,
                    y_col,
                    used,
                    valid,
                    row_level,
                    col_level,
                    series,
                    levels,
                    bounds,
                )
            )

    def pair(
        xi: int, yj: int, extra: list[pl.Expr], extra_columns: list[str]
    ) -> pl.LazyFrame:
        """Return the bins of the panels of one pair of axis columns, of the rows `extra` keeps."""
        x_col, y_col = spec.x[xi], spec.y[yj]
        outlier = pl.lit(True)
        if (x_col, y_col) in pairs_with_smooths and not spec.draws_points(x_col, y_col):
            # Only the smoothing lines: no row is drawn as a point.
            x = pl.col(x_col).cast(pl.Float64)
            y = pl.col(y_col).cast(pl.Float64)
            outlier = pl.lit(False)
        elif spec.draws_points(x_col, y_col):
            x, y = pair_positions(
                x_col,
                y_col,
                set(spec.categorical),
                axis_levels,
                spread_of.get((x_col, y_col)),
                INDEX,
            )
        else:
            # Only the outliers, spread in the slot of their series' box.
            y = pl.col(y_col).cast(pl.Float64)
            x = outlier_position(
                x_col,
                axis_levels[x_col],
                series,
                grid.n_series,
                jitter(INDEX, JITTER_X),
            )
            n_groups = len(levels["row"]) * len(levels["col"])
            n_groups *= len(axis_levels[x_col]) * grid.n_series
            stats = _group_stats(boxes_of[x_col, y_col], levels, axis_levels, grid)
            outlier = is_outlier(y, group(x_col), fences(stats, n_groups))
        key = grid.pack(
            axes.panel(row, col, xi, yj),
            series,
            _bin_expr(y, y_ranges[yj], grid.height),
            _bin_expr(x, x_ranges[xi], grid.width),
        )
        return (
            _scan(spec, [x_col, y_col, *used, *extra_columns], INDEX)
            .filter(
                x.is_finite(),
                y.is_finite(),
                x.is_between(*x_ranges[xi]),
                y.is_between(*y_ranges[yj]),
                *valid,
                *extra,
            )
            # The group, like the key, reads the drawn facet levels: only the
            # rows kept above have one.
            .select(key.alias(KEY), pl.col(INDEX), outlier.alias(_OUTLIER))
            .filter(pl.col(_OUTLIER))
            .group_by(KEY)
            .agg(pl.len().alias(COUNT), pl.col(INDEX).max())
        )

    def all_pairs(extra: list[pl.Expr], extra_columns: list[str]) -> pl.DataFrame:
        # One query per pair, one after another: the pairs' panels differ, so
        # their keys do too. One query over all pairs was about 10% faster but
        # its peak grew with the pairs (9 pairs of 100M rows: 9.0GB against 4.0GB).
        return pl.concat(
            [
                pair(xi, yj, extra, extra_columns).collect(engine="streaming")
                for yj in range(axes.ny)
                for xi in range(axes.nx)
            ]
        ).sort(KEY)

    bins = None
    if not selection_only:
        progress("bins")
        bins = all_pairs(filter_conditions(spec.filters), filter_columns(spec.filters))
        progress("rows")
        hover = list(dict.fromkeys(spec.hover))
        rows = (
            _scan(spec, hover, INDEX)
            .join(bins.lazy().select(INDEX), on=INDEX, how="semi")
            .select(INDEX, *hover)
            .collect(engine="streaming")
        )
        bins = bins.join(rows, on=INDEX, how="left", maintain_order="left")
    selected = selected_rows = None
    if spec.selection is not None:
        progress("selection")
        conditions = selection_filter(spec, INDEX)
        columns = selection_columns(spec)
        selected = all_pairs(conditions, columns)
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
            selected = selected.select(KEY, COUNT, spec.color)
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
        grid=grid,
        layout=layout,
        axes=axes,
        x_ranges=x_ranges,
        y_ranges=y_ranges,
        levels=levels,
        all_levels=all_levels,
        bins=bins,
        selected=selected,
        selected_rows=selected_rows,
        cuts=cuts,
        color_range=color_range,
        axis_levels=axis_levels,
        spreads=spreads,
        boxes=boxes,
        smooths=smooths,
    )


def _overview_range(spec: ScatterSpec, column: str) -> tuple[float, float]:
    """Return the padded finite range of a numeric column over every row, as the overview's axis has it."""
    return _padded(*_range_query(spec, column).collect(engine="streaming").row(0))


def _smooths(
    spec: ScatterSpec,
    x_col: str,
    y_col: str,
    used: list[str],
    valid: list[pl.Expr],
    row: pl.Expr,
    col: pl.Expr,
    series: pl.Expr,
    levels: dict[str, list],
    bounds: tuple[float, float],
) -> Smooths:
    """Return the smoothing lines of a pair over the drawn rows that pass the local filter, one per facet cell and series (`ddviz.compute.smooth`)."""
    x = pl.col(x_col).cast(pl.Float64)
    y = pl.col(y_col).cast(pl.Float64)
    frame = _scan(spec, [x_col, y_col, *used, *filter_columns(spec.filters)]).filter(
        x.is_finite(), y.is_finite(), *valid, *filter_conditions(spec.filters)
    )
    n_col = len(levels["col"])
    bins = bin_query(frame, x, y, row * n_col + col, series, bounds).collect(
        engine="streaming"
    )
    lines = [
        [cell // n_col, cell % n_col, s, xs, ys]
        for cell, s, xs, ys in fit_lines(bins, spec.smooth)
    ]
    return Smooths(x=x_col, y=y_col, lines=lines)


def _boxes(
    x: str,
    y: str,
    stats: dict[int, list[float]],
    levels: dict[str, list],
    axis_levels: dict[str, list[str]],
    grid: BinGrid,
) -> Boxes:
    """Return the box plots of a pair from the boxes of its groups (`aggregate`'s ``group``)."""
    n_levels, n_series, n_col = len(axis_levels[x]), grid.n_series, len(levels["col"])
    rows = []
    for g in sorted(stats):
        cell, rest = divmod(g, n_levels * n_series)
        level, series = divmod(rest, n_series)
        row, col = divmod(cell, n_col)
        rows.append([row, col, level, series, *stats[g]])
    return Boxes(x=x, y=y, stats=rows)


def _group_stats(
    boxes: Boxes,
    levels: dict[str, list],
    axis_levels: dict[str, list[str]],
    grid: BinGrid,
) -> dict[int, list[float]]:
    """Return the boxes of a pair by their group, as `ddviz.compute.boxes.box_stats` gives them."""
    n_levels, n_series, n_col = (
        len(axis_levels[boxes.x]),
        grid.n_series,
        len(levels["col"]),
    )
    return {
        ((row * n_col + col) * n_levels + level) * n_series + series: stats
        for row, col, level, series, *stats in (
            [int(v) for v in b[:4]] + b[4:] for b in boxes.stats
        )
    }
