"""A join of another table (the joined table) to the input: its checks and what the server keeps of it.

The input takes the joined table's columns side by side, by keys (a left
join) or by the order of the rows, once per session
(`ddviz.server.source.Source.join`). The rows, their order and their row
numbers stay those of the input. The columns added and their names are
`ddviz.shared.joined`'s; the map of the rows and the parts of the columns are
written by workers (`ddviz.compute.join`). The join may add only some of the
joined table's columns, or leave out those named like the input's
(`check_columns`, `choose_columns`), maybe only when their values are the same
(`ddviz.compute.join.run_join_equal`). A join by keys may be tried first
without joining (a dry run, `JoinCheck`): its map is then taken by the join.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException

from ddviz.shared.joined import KINDS, NESTED, SAME_NAMES, SAME_NAMES_DEFAULT
from ddviz.shared.tasks import JoinTask

if TYPE_CHECKING:
    from ddviz.server.source import Source

# Start of the message of a key given wrong.
WRONG_KEYS = "キーの指定が正しくありません："
# Start of the message of the columns to keep given wrong.
WRONG_COLUMNS = "保持する列の指定が正しくありません："


@dataclass
class Join:
    """A join the input took.

    Parameters
    ----------
    right : Source
        The joined table.
    kind : str
        ``"key"`` or ``"rows"``.
    keys : list of dict of str to str
        The pairs of keys, ``{"left", "right"}``; empty for ``"rows"``.
    columns : list of str or None
        The columns of the joined table asked to be added; None for all.
    same_names : str or None
        What was done with a column named like one of the input
        (`SAME_NAMES`); None with columns chosen.
    names : dict of str to str or None
        The columns added, in order, with the column of the joined table
        each holds; None for ``_joined`` (`ddviz.shared.joined.joined_names`).
    id : str
        What names its parts (`ddviz.shared.joined.join_id`).
    matched : int
        The rows of the input a row of the joined table matched.
    maps : list of str
        For ``"key"``, the parts of the map, one per file of the input;
        empty for ``"rows"``.
    task : JoinTask or None
        For ``"key"``, the task writing the map and ``_joined``, run again
        when a part of them is gone.
    exact : dict of str to int
        The non-null values of each added column converted, counted from
        its parts.
    """

    right: Source
    kind: str
    keys: list[dict[str, str]]
    columns: list[str] | None
    same_names: str | None
    names: dict[str, str | None]
    id: str
    matched: int
    maps: list[str]
    task: JoinTask | None
    exact: dict[str, int] = field(default_factory=dict)


@dataclass
class JoinCheck:
    """The last dry run of a join by keys that ended (`ddviz.server.source.Source.check_join`).

    A join by the same keys of the same tables takes its map and
    ``_joined`` while their parts are there, instead of running the join
    task again; the rows of both tables are saved through its map
    (``POST /api/plot-data/join-rows``).

    Parameters
    ----------
    id : str
        The join it is of (`ddviz.shared.joined.join_id`).
    keys : list of dict of str to str
        The pairs of keys, ``{"left", "right"}``.
    task : JoinTask
        The join task it ran: its map and ``_joined`` parts.
    answer : dict
        What it answered (``POST /api/join/check``).
    """

    id: str
    keys: list[dict[str, str]]
    task: JoinTask
    answer: dict

    @property
    def parts(self) -> list[Path]:
        """Return the parts of the map and ``_joined`` the join task wrote."""
        return [Path(p) for p in [*self.task.maps, *self.task.indicators]]


def _wrong(reason: str) -> HTTPException:
    """Return the refusal of keys given wrong."""
    return HTTPException(400, WRONG_KEYS + reason)


def check_keys(  # noqa: C901
    kind: str,
    keys: list[dict[str, str]],
    left: dict[str, str],
    right: dict[str, str],
) -> None:
    """Refuse a join whose kind or keys are wrong (400).

    Parameters
    ----------
    kind : str
        The kind asked for.
    keys : list of dict of str to str
        The pairs of keys asked for, ``{"left", "right"}``.
    left, right : dict of str to str
        The type of each column of the input and of the joined table.

    Raises
    ------
    fastapi.HTTPException
        400 for an unknown kind, keys missing for ``"key"`` or given for
        ``"rows"``, a column twice on the same side, a column that is not
        there, or a nested column.
    """
    if kind not in KINDS:
        raise _wrong(f"知らない種類です：{kind}")
    if kind == "key" and not keys:
        raise _wrong("キーで結合するときはキーが要ります")
    if kind == "rows" and keys:
        raise _wrong("行の順で結合するときはキーを指定しません")
    for side, label in (("left", "元の表"), ("right", "結合する表")):
        seen: set[str] = set()
        for pair in keys:
            name = pair[side]
            if name in seen:
                raise _wrong(f"{label}の列が 2 回あります：{name}")
            seen.add(name)
    for pair in keys:
        for side, types in (("left", left), ("right", right)):
            name = pair[side]
            if name not in types:
                raise HTTPException(400, f"列がありません：{name}")
            if types[name].startswith(NESTED):
                raise HTTPException(400, f"キーにできない型です：{name}（{types[name]}）")


def check_rows(left: int, right: int) -> None:
    """Refuse a join by rows of tables of different rows (400)."""
    if left != right:
        raise HTTPException(
            400, f"行数が違います：元の表 {left:,} 行、結合する表 {right:,} 行"
        )


def _repeated(names: list[str]) -> str | None:
    """Return the first name of `names` given again, or None."""
    seen: set[str] = set()
    for name in names:
        if name in seen:
            return name
        seen.add(name)
    return None


def check_columns(
    columns: list[str] | None,
    same_names: str | None,
    right: dict[str, str],
    keys: list[dict[str, str]],
) -> str | None:
    """Refuse a join whose columns to add are given wrong (400), else return what to do with the same names.

    Parameters
    ----------
    columns : list of str or None
        The columns of the joined table asked to be added; None for all.
    same_names : str or None
        What to do with a column named like one of the input (`SAME_NAMES`);
        None for `SAME_NAMES_DEFAULT` with all the columns, and the only
        value taken with columns chosen.
    right : dict of str to str
        The type of each column of the joined table.
    keys : list of dict of str to str
        The pairs of keys asked for, ``{"left", "right"}``.

    Returns
    -------
    str or None
        For all the columns, `same_names` or its default; None with columns
        chosen.

    Raises
    ------
    fastapi.HTTPException
        400 for an unknown `same_names`, `same_names` given with columns
        chosen, no column chosen, a column chosen twice, a column that is
        not there, or a key chosen.
    """
    if columns is None:
        if same_names is None:
            return SAME_NAMES_DEFAULT
        if same_names not in SAME_NAMES:
            raise HTTPException(400, f"{WRONG_COLUMNS}知らない扱いです：{same_names}")
        return same_names
    if same_names is not None:
        raise HTTPException(400, WRONG_COLUMNS + "列を選んだときは同じ名前の扱いを指定しません")
    if not columns:
        raise HTTPException(400, WRONG_COLUMNS + "列を 1 つ以上選んでください")
    twice = _repeated(columns)
    if twice is not None:
        raise HTTPException(400, f"{WRONG_COLUMNS}列が 2 回あります：{twice}")
    missing = next((name for name in columns if name not in right), None)
    if missing is not None:
        raise HTTPException(400, f"列がありません：{missing}")
    taken = {k["right"] for k in keys}
    key = next((name for name in columns if name in taken), None)
    if key is not None:
        raise HTTPException(400, f"{WRONG_COLUMNS}キーの列は足せません：{key}")
    return None


def choose_columns(
    left: dict[str, str],
    right: dict[str, str],
    generated: dict[str, str],
    keys: list[dict[str, str]],
    columns: list[str] | None,
    same_names: str | None,
) -> tuple[list[str], dict[str, str], list[str], list[str]]:
    """Select the columns to add, leave out by name, or compare before naming them.

    Parameters
    ----------
    left, right : dict of str to str
        The column types of the input and the joined table, in schema order,
        including generated columns.
    generated : dict of str to str
        The generated columns of the joined table with their kinds (`ddviz.shared.generated`).
    keys : list of dict of str to str
        The pairs of keys, ``{"left", "right"}``: its keys are not added.
    columns : list of str or None
        The columns asked to be added (`check_columns`); None for all.
    same_names : str or None
        What to do with a column named like one of the input, for all the
        columns (`check_columns`): ``"skip"`` leaves out same-named ordinary
        columns; ``"skip_equal"`` compares them when neither type is nested.

    Returns
    -------
    tuple of (list of str, dict of str to str, list of str, list of str)
        The ordinary columns to add and the generated columns to add with
        their kinds (`ddviz.shared.joined.joined_names`); then the columns
        left out by name and the columns to compare, in the joined table's order.
    """
    taken = {k["right"] for k in keys}
    if columns is not None:
        asked = set(columns)
        plain = [c for c in right if c in asked and c not in generated]
        return plain, {c: k for c, k in generated.items() if c in asked}, [], []
    plain = [c for c in right if c not in generated and c not in taken]
    added = {c: k for c, k in generated.items() if c not in taken}
    same = [c for c in plain if c in left]
    if same_names == "skip":
        skipped = set(same)
        return [c for c in plain if c not in skipped], added, same, []
    pairs = [c for c in same if not left[c].startswith(NESTED) and not right[c].startswith(NESTED)]
    return plain, added, [], pairs


def check_added(kind: str, names: dict[str, str | None]) -> None:
    """Refuse a join by rows that adds no column, all of the joined table's being named like the input's (400)."""
    if kind == "rows" and not names:
        raise HTTPException(400, "保持する列がありません：結合する表の列はすべて元の表と同じ名前です")
