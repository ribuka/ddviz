"""A join of another table (the joined table) to the input: its checks and what the server keeps of it.

The input takes the joined table's columns side by side, by keys (a left
join) or by the order of the rows, once per session
(`ddviz.server.source.Source.join`). The rows, their order and their row
numbers stay those of the input. The columns added and their names are
`ddviz.shared.joined`'s; the map of the rows and the parts of the columns are
written by workers (`ddviz.compute.join`). The join may add only some of the
joined table's columns, or leave out those named like the input's
(`check_columns`, `chosen`), maybe only when their values are the same
(`compared`, `ddviz.compute.join.run_join_equal`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException

from ddviz.shared.joined import KINDS, NESTED, SAME_NAMES
from ddviz.shared.tasks import JoinTask

if TYPE_CHECKING:
    from ddviz.server.source import Source

# Start of the message of a key given wrong.
WRONG_KEYS = "キーの指定が正しくありません："
# Start of the message of the columns to add given wrong.
WRONG_COLUMNS = "足す列の指定が正しくありません："


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
    same_names : str
        What was done with a column named like one of the input
        (`SAME_NAMES`).
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
    same_names: str
    names: dict[str, str | None]
    id: str
    matched: int
    maps: list[str]
    task: JoinTask | None
    exact: dict[str, int] = field(default_factory=dict)


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
    same_names: str,
    right: dict[str, str],
    keys: list[dict[str, str]],
) -> None:
    """Refuse a join whose columns to add are given wrong (400).

    Parameters
    ----------
    columns : list of str or None
        The columns of the joined table asked to be added; None for all.
    same_names : str
        What to do with a column named like one of the input (`SAME_NAMES`).
    right : dict of str to str
        The type of each column of the joined table.
    keys : list of dict of str to str
        The pairs of keys asked for, ``{"left", "right"}``.

    Raises
    ------
    fastapi.HTTPException
        400 for an unknown `same_names`, `same_names` other than
        ``"rename"`` with columns chosen, no column chosen, a column chosen
        twice, a column that is not there, or a key chosen.
    """
    if same_names not in SAME_NAMES:
        raise HTTPException(400, f"{WRONG_COLUMNS}知らない扱いです：{same_names}")
    if columns is None:
        return
    if same_names != "rename":
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


def chosen(
    order: list[str],
    generated: dict[str, str],
    keys: list[dict[str, str]],
    columns: list[str] | None,
    same_names: str,
    left: Iterable[str],
) -> tuple[list[str], dict[str, str], list[str]]:
    """Return the columns of the joined table a join adds, as `ddviz.shared.joined.joined_names` takes them, and those left out.

    Parameters
    ----------
    order : list of str
        The columns of the joined table, in its order.
    generated : dict of str to str
        Its added columns, with their kinds (`ddviz.shared.generated`).
    keys : list of dict of str to str
        The pairs of keys, ``{"left", "right"}``: its keys are not added.
    columns : list of str or None
        The columns asked to be added (`check_columns`); None for all.
    same_names : str
        What to do with a column named like one of the input, for all the
        columns (`SAME_NAMES`): ``"skip"`` leaves it out, unless it is an
        added column; ``"skip_equal"`` keeps it here, to compare
        (`compared`).
    left : iterable of str
        The columns of the input, its added columns included.

    Returns
    -------
    tuple of (list of str, dict of str to str, list of str)
        The columns to add but the added ones, in the joined table's order;
        the added columns to add with their kinds; and the columns left out
        by name, in the joined table's order.
    """
    taken = {k["right"] for k in keys}
    if columns is not None:
        asked = set(columns)
        plain = [c for c in order if c in asked and c not in generated]
        return plain, {c: k for c, k in generated.items() if c in asked}, []
    plain = [c for c in order if c not in generated and c not in taken]
    added = {c: k for c, k in generated.items() if c not in taken}
    skipped: list[str] = []
    if same_names == "skip":
        names = set(left)
        skipped = [c for c in plain if c in names]
        plain = [c for c in plain if c not in names]
    return plain, added, skipped


def compared(plain: list[str], left: dict[str, str], right: dict[str, str]) -> list[str]:
    """Return the columns a join on ``"skip_equal"`` compares: those of `plain` named like a column of the input, neither of the two nested.

    Parameters
    ----------
    plain : list of str
        The columns of the joined table to add but its added ones, in its
        order (`chosen`).
    left, right : dict of str to str
        The type of each column of the input, its added columns included,
        and of the joined table.

    Returns
    -------
    list of str
        The columns, in the joined table's order.
    """
    return [
        c
        for c in plain
        if c in left and not left[c].startswith(NESTED) and not right[c].startswith(NESTED)
    ]


def check_added(kind: str, names: dict[str, str | None]) -> None:
    """Refuse a join by rows that adds no column, all of the joined table's being named like the input's (400)."""
    if kind == "rows" and not names:
        raise HTTPException(400, "足す列がありません：結合する表の列はすべて元の表と同じ名前です")
