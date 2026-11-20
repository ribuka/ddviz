"""A join of another table (the joined table) to the input: its checks and what the server keeps of it.

The input takes the joined table's columns side by side, by keys (a left
join) or by the order of the rows, once per session
(`ddviz.server.source.Source.join`). The rows, their order and their row
numbers stay those of the input. The columns added and their names are
`ddviz.shared.joined`'s; the map of the rows and the parts of the columns are
written by workers (`ddviz.compute.join`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException

from ddviz.shared.joined import KINDS, NESTED
from ddviz.shared.tasks import JoinTask

if TYPE_CHECKING:
    from ddviz.server.source import Source

# Start of the message of a key given wrong.
WRONG_KEYS = "キーの指定が正しくありません："


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
    names: dict[str, str | None]
    id: str
    matched: int
    maps: list[str]
    task: JoinTask | None
    exact: dict[str, int] = field(default_factory=dict)


def _wrong(reason: str) -> HTTPException:
    """Return the refusal of keys given wrong."""
    return HTTPException(400, WRONG_KEYS + reason)


def check_keys(
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
