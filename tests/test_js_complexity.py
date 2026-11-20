"""The functions of the static JS stay within the complexity limits ruff applies to Python.

Each function is measured on its own: the functions nested in it are measured
separately and add nothing to it. A function over a limit carries
`// noqa: <codes>` on the line it starts on, as Python does for ruff; such a
mark is debt from before the limits, and a mark no longer needed fails too.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest
import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "ddviz" / "static" / "js"

FUNCTIONS = {
    "function_declaration",
    "function_expression",
    "generator_function_declaration",
    "generator_function",
    "arrow_function",
    "method_definition",
}
# Decision points of the cyclomatic complexity (as mccabe counts them for
# Python: boolean operators are not counted).
DECISIONS = {
    "if_statement",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "switch_case",
    "catch_clause",
    "ternary_expression",
}
BRANCHES = {
    "if_statement",
    "else_clause",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "switch_case",
    "switch_default",
    "catch_clause",
}
STATEMENTS = {
    "expression_statement",
    "lexical_declaration",
    "variable_declaration",
    "if_statement",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "return_statement",
    "throw_statement",
    "try_statement",
    "switch_statement",
    "break_statement",
    "continue_statement",
    "labeled_statement",
    "function_declaration",
    "generator_function_declaration",
    "class_declaration",
}
NOQA = re.compile(r"//\s*noqa:\s*([A-Z0-9, ]+)")


@dataclass(frozen=True)
class Measured:
    """The size of one JS function.

    Attributes
    ----------
    file : str
        The file's name under `static/js`.
    line : int
        The line the function starts on (1-based).
    name : str
        The function's name, or `<anonymous>`.
    codes : frozenset[str]
        The ruff codes of the limits the function is over.
    """

    file: str
    line: int
    name: str
    codes: frozenset[str]


def _limits() -> dict[str, int]:
    """Return the limit of each ruff code, from `pyproject.toml`."""
    lint = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["tool"]["ruff"]["lint"]
    pylint = lint["pylint"]
    return {
        "C901": lint["mccabe"]["max-complexity"],
        "PLR0912": pylint["max-branches"],
        "PLR0915": pylint["max-statements"],
    }


def _own(node: Node) -> list[Node]:
    """Return the nodes inside the function `node`, without the functions nested in it."""
    found = []
    stack = list(node.children)
    while stack:
        child = stack.pop()
        found.append(child)
        if child.type not in FUNCTIONS:
            stack.extend(child.children)
    return found


def _name(node: Node) -> str:
    """Return the name of the function `node`: its own, or the variable or key it is assigned to."""
    named = node.child_by_field_name("name")
    if named is None and node.parent is not None:
        named = node.parent.child_by_field_name("name") or node.parent.child_by_field_name("key")
    return named.text.decode() if named is not None and named.text else "<anonymous>"


def _codes(node: Node, limits: dict[str, int]) -> frozenset[str]:
    """Return the ruff codes of the limits the function `node` is over."""
    own = _own(node)
    types = [n.type for n in own]
    size = {
        "C901": 1 + sum(t in DECISIONS for t in types),
        "PLR0912": sum(t in BRANCHES for t in types),
        "PLR0915": sum(t in STATEMENTS for t in types),
    }
    return frozenset(code for code, value in size.items() if value > limits[code])


def _measure() -> tuple[list[Measured], dict[tuple[str, int], frozenset[str]]]:
    """Return every JS function over a limit, and the `noqa` marks by file and line."""
    parser = Parser(Language(tree_sitter_javascript.language()))
    limits = _limits()
    over, marks = [], {}
    for path in sorted(JS.glob("*.js")):
        source = path.read_bytes()
        # tree-sitter does not parse a NUL in a string literal; a space keeps
        # the positions.
        root = parser.parse(source.replace(b"\x00", b" ")).root_node
        for number, text in enumerate(source.decode("utf-8").splitlines(), 1):
            if mark := NOQA.search(text):
                codes = {c.strip() for c in mark.group(1).split(",") if c.strip()}
                marks[path.name, number] = frozenset(codes & set(limits))
        stack = [root]
        while stack:
            node = stack.pop()
            stack.extend(node.children)
            if node.type in FUNCTIONS and (codes := _codes(node, limits)):
                line = node.start_point.row + 1
                over.append(Measured(path.name, line, _name(node), codes))
    return over, marks


@pytest.fixture(scope="module")
def measured() -> tuple[list[Measured], dict[tuple[str, int], frozenset[str]]]:
    """Return the JS functions over a limit and the `noqa` marks, measured once."""
    return _measure()


def test_functions_within_limits(
    measured: tuple[list[Measured], dict[tuple[str, int], frozenset[str]]],
) -> None:
    """Every function over a limit carries `// noqa` with its codes on its first line."""
    over, marks = measured
    unmarked = [
        f"{m.file}:{m.line} {m.name}: {', '.join(sorted(m.codes - marks.get((m.file, m.line), frozenset())))}"
        for m in over
        if not m.codes <= marks.get((m.file, m.line), frozenset())
    ]
    assert not unmarked, "split these functions:\n" + "\n".join(unmarked)


def test_no_stale_marks(
    measured: tuple[list[Measured], dict[tuple[str, int], frozenset[str]]],
) -> None:
    """Every `// noqa` code for a limit is still needed by a function starting on its line."""
    over, marks = measured
    needed: dict[tuple[str, int], set[str]] = {}
    for m in over:
        needed.setdefault((m.file, m.line), set()).update(m.codes)
    stale = [
        f"{file}:{line}: {', '.join(sorted(codes - needed.get((file, line), set())))}"
        for (file, line), codes in sorted(marks.items())
        if codes - needed.get((file, line), set())
    ]
    assert not stale, "remove these noqa codes:\n" + "\n".join(stale)
