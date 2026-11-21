"""Levels of the columns and roles: the overview's pass, the levels among the rows of the local filter, and the facet levels."""

from __future__ import annotations

from dataclasses import dataclass, replace

import polars as pl

from ddviz.compute.cuts import cut_index, cut_labels, find_cuts
from ddviz.compute.missing import is_missing, numeric_columns, numeric_roles
from ddviz.compute.plotscan import plot_scan, range_query
from ddviz.compute.rowfilter import filter_columns, filter_conditions
from ddviz.shared.missing import MISSING
from ddviz.shared.natural import natural_key
from ddviz.shared.scatter import (
    ONE_BAND,
    FilteredLevelsError,
    ScatterSpec,
    filtered_levels_message,
)

# Rows the levels of a column among the rows of the local filter are found
# from at a time (`levels_among_filter`): the levels of each slice are
# merged into those found so far, and the reading stops once they pass the
# limit.
LEVEL_ROWS_PER_PASS = 25_000_000


@dataclass(frozen=True)
class Overview:
    """What the overview finds over every row (`overview`).

    Attributes
    ----------
    ranges : dict
        The finite minimum and maximum of each numeric axis column, or None.
    levels : dict
        The levels of each role.
    cuts : dict
        The cuts of each binned role.
    color_range : tuple of float or None
        The range of a gradient color column.
    axis_levels : dict
        The levels of each categorical axis column.
    """

    # The finite minimum and maximum of each numeric axis column, or None.
    ranges: dict[str, tuple[float, float] | None]
    levels: dict[str, list]
    cuts: dict[str, dict]
    color_range: tuple[float, float] | None
    axis_levels: dict[str, list[str]]


def check_levels(
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
    (`found_levels`).

    Parameters
    ----------
    spec : ScatterSpec
        The plot, with its limits.
    roles : dict
        The column of each role whose levels are of every row.
    counted : dict
        The number of levels of each column over every row.
    axes : list of str
        The categorical axis columns whose levels are of every row.

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
    # A color, a symbol or an axis column that keeps its levels counts them before the
    # filter; any other has them of the rows of the filter, which lowers them.
    refused = {c for c, _ in over}
    settings = [
        name
        for kept, name in (
            (
                (spec.keep_unfiltered_color_levels and spec.color in refused)
                or (
                    spec.keep_unfiltered_symbol_levels
                    and "symbol" not in spec.binned
                    and spec.symbol in refused
                ),
                "「フィルタで除外された水準も凡例に残す」",
            ),
            (
                any(c in refused for c in spec.keep_unfiltered_axis_levels if c in axes),
                "「フィルタで除外された水準も軸に残す」",
            ),
        )
        if kept
    ]
    advice = (
        "水準はフィルタの前の行から数える設定のため、別の列を使うか、"
        + "か".join(settings)
        + "を外す"
        if settings
        else "フィルタで水準を絞るか、別の列を使う"
    )
    raise ValueError(
        "水準が上限を超えるため描けない（"
        + "。".join(text for _, refused in over for text in refused)
        + "）。"
        + advice
    )


def overview(
    spec: ScatterSpec, roles: dict[str, str | None], axes: list[str]
) -> Overview:
    """Return the data range of each numeric axis column and the levels of each role, over every row.

    The ranges and the levels of the categorical roles (`roles`, None for
    one whose levels are found among the rows of the filter) and of the
    categorical axis columns `axes` come in one pass, the cuts of each
    binned role in passes of their own (`ddviz.compute.cuts.find_cuts`). A
    role that draws its missing rows
    (`ddviz.shared.scatter.ScatterSpec.null_roles`) ends in the missing
    level (`ddviz.shared.missing.MISSING`) when its column has a null or NaN
    value: among the rows of the local filter for a numeric column
    (`has_missing`); a categorical column counts it as one of its levels
    against the limits of its roles (`check_levels`).

    Parameters
    ----------
    spec : ScatterSpec
        The plot.
    roles : dict
        The column of each role, None for one whose levels are found among
        the rows of the filter.
    axes : list of str
        The categorical axis columns whose levels are of every row.

    Returns
    -------
    Overview
        The ranges, levels, cuts and color range over every row.
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
    # come in passes of their own (`ddviz.compute.foundranges.auto_ranges`); these stand in for an
    # axis column the filter leaves without a value.
    found = pl.collect_all(
        [
            *[range_query(spec, c) for c in numeric],
            *[plot_scan(spec, [c]).group_by(pl.col(c).cast(pl.String)).len() for c in used],
            *[range_query(spec, c) for c in gradient],
        ],
        engine="streaming",
    )
    has_null = has_missing(spec, asked)
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
        raise ValueError(missing_name_message(taken))
    if ONE_BAND in axes:
        column_levels[ONE_BAND] = [""]
    axis_levels = {c: column_levels[c] for c in axes}
    # The missing level drawn counts as one level of its column.
    counted = {
        c: len(v) + any(roles[r] == c for r in missing)
        for c, v in column_levels.items()
    }
    check_levels(spec, roles, counted, axes)
    cuts = {
        role: find_cuts(plot_scan(spec, [roles[role]]), roles[role], binning)
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
    return Overview(ranges, levels, cuts, color_range, axis_levels)


def values_among_filter(
    spec: ScatterSpec, column: str, start: int, length: int
) -> pl.Series:
    """Return the values of a column, as text, of the rows ``start`` to ``start + length`` that pass the local filter, once each; a null among them if any.

    Parameters
    ----------
    spec : ScatterSpec
        The plot, with its local filter.
    column : str
        The column.
    start : int
        The first row.
    length : int
        The rows to read.

    Returns
    -------
    polars.Series
        The distinct values, as text.
    """
    return (
        plot_scan(spec, [column, *filter_columns(spec.filters)])
        .slice(start, length)
        .filter(*filter_conditions(spec.filters))
        .select(pl.col(column).cast(pl.String))
        .unique()
        .collect(engine="streaming")[column]
    )


def levels_among_filter(
    spec: ScatterSpec, column: str, limit: int
) -> tuple[list[str], bool] | None:
    """Return the levels of a categorical column among the rows of the local filter, and whether those rows have a null value.

    Reads only the column and the filter's columns, in a pass of its own: a
    row filter on the overview's pass made it peak far higher
    (`overview`). The rows are read `LEVEL_ROWS_PER_PASS` at a time, the
    levels of each slice merged into those found so far, and the reading
    stops as soon as they pass `limit`, so that a column of a level per row
    (an ID) never holds them all. The levels are text, as those found over
    every row, in natural order, the empty text one of them.

    Parameters
    ----------
    spec : ScatterSpec
        The plot, with its local filter.
    column : str
        The categorical column.
    limit : int
        The most levels to find.

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
    rows = plot_scan(spec, [column]).select(pl.len()).collect().item()
    found: set[str] = set()
    has_null = False
    for start in range(0, max(rows, 1), LEVEL_ROWS_PER_PASS):
        part = values_among_filter(spec, column, start, LEVEL_ROWS_PER_PASS)
        has_null = has_null or part.null_count() > 0
        found.update(part.drop_nulls().to_list())
        if len(found) > limit:
            return None
    if MISSING in found:
        raise ValueError(missing_name_message([column]))
    return sorted(found, key=natural_key), has_null


def has_missing(spec: ScatterSpec, columns: list[str]) -> dict[str, bool]:
    """Return whether each numeric column has a null or NaN value among the rows of the local filter (every row without a filter).

    Each column is read with the filter's columns alone, apart from the
    overview's pass (`overview`).

    Parameters
    ----------
    spec : ScatterSpec
        The plot.
    columns : list of str
        The numeric columns.

    Returns
    -------
    dict
        Whether each column has a null or NaN value.
    """
    if not columns:
        return {}
    found = pl.collect_all(
        [
            plot_scan(spec, [c, *filter_columns(spec.filters)])
            .filter(*filter_conditions(spec.filters))
            .select(is_missing(c, numeric=True).any())
            for c in columns
        ],
        engine="streaming",
    )
    return {c: bool(f.item()) for c, f in zip(columns, found, strict=True)}


def role_name(spec: ScatterSpec, role: str) -> str:
    """Return the name the page gives a role (its zone).

    Parameters
    ----------
    spec : ScatterSpec
        The plot.
    role : str
        The role: ``"color"``, ``"symbol"``, ``"row"`` or ``"col"``.

    Returns
    -------
    str
        The name of the role.
    """
    if role == "col":
        return "Wrap" if spec.wrap else "Group X"
    return {"color": "Color", "symbol": "Symbol", "row": "Group Y"}[role]


def found_levels(  # noqa: C901, PLR0912
    spec: ScatterSpec,
    roles: dict[str, str | None],
    levels: dict[str, list],
    find: list[str],
    axes: list[str],
) -> tuple[dict[str, list], dict[str, list[str]]]:
    """Return the levels of the roles `find` and of the categorical axis columns `axes` among the rows of the local filter.

    A categorical role (`ddviz.shared.scatter.ScatterSpec.levels_of_filter`)
    has the levels of its column among those rows (`levels_among_filter`),
    then the missing level (`ddviz.shared.missing.MISSING`) when it draws
    its missing rows and they have a null value, which counts as one level
    against `ScatterSpec.max_levels`. A numeric role keeps its levels
    (`levels`), but for the missing level, last when those rows have a null
    or NaN value (`has_missing`); a gradient without a finite value over
    every row has only the missing level, or else its one level. An axis
    column has the levels of those rows, up to `ScatterSpec.max_axis_levels`.
    A column on two of them is read once.

    Parameters
    ----------
    spec : ScatterSpec
        The plot, with its local filter.
    roles : dict
        The column of each role, None for a role without one.
    levels : dict
        The levels of each role known.
    find : list of str
        The roles whose levels are found among the rows of the filter.
    axes : list of str
        The categorical axis columns whose levels are found among the rows
        of the filter.

    Returns
    -------
    tuple of dict
        The levels of each role of `find`, and of each axis column of `axes`.

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
                (spec.max_levels, role_name(spec, role), role)
            )
    for c in axes:
        limits.setdefault(c, []).append(
            (spec.max_axis_levels, "X・Y のカテゴリの軸", None)
        )
    found = {
        c: levels_among_filter(spec, c, max(n for n, _, _ in ls))
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
        c: levels_among_filter(replace(spec, filters=[]), c, spec.max_levels)
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
    has_null = has_missing(
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


def missing_name_message(columns: list[str]) -> str:
    """Return the error of columns with a value that is the missing level's name.

    Parameters
    ----------
    columns : list of str
        The columns.

    Returns
    -------
    str
        The error message.
    """
    return (
        f"列 {'、'.join(columns)} の値に欠損の水準の内部名（{MISSING!r}）と同じ"
        "文字列があるため描けない"
    )


def facet_levels(
    spec: ScatterSpec, levels: dict[str, list], cuts: dict[str, dict]
) -> dict[str, list]:
    """Return `levels` with the row and col levels left without rows by the local filter dropped.

    Reads only the facet columns and the filter's columns, in a pass of its
    own: on 100M rows it took at most 0.55s, peaking under 2.0GB.
    A filter that keeps no rows keeps every panel. A role that draws its
    missing rows (`ddviz.shared.scatter.ScatterSpec.null_roles`) keeps its
    missing level only while a row of the filter is missing.

    Parameters
    ----------
    spec : ScatterSpec
        The plot, with its local filter.
    levels : dict
        The levels of each role.
    cuts : dict
        The cuts of each binned role.

    Returns
    -------
    dict
        The levels, the row and col levels without rows dropped.
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
        plot_scan(spec, [*facets.values(), *filter_columns(spec.filters)])
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
