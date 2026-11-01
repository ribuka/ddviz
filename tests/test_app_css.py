"""The page's stylesheet: colors by role, numbers of one width, one look for what floats."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "src" / "ddviz" / "static" / "app.css"
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
# Rules that still write their colors: the pending view is being changed by
# Issue #45, and moves to the variables once that change is in.
LITERAL_COLORS = {"#plot.pending .image-layers", "#pending"}


def _rules() -> list[tuple[str, str]]:
    """Return the selector and the body of every rule in app.css.

    Returns
    -------
    list of tuple of str
        The selector (whitespace collapsed) and the declarations of each
        innermost rule, rules inside at-rules too.
    """
    text = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    return [(" ".join(sel.split()), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]


def _rule(selector: str) -> str:
    """Return the body of the first rule with `selector`.

    Parameters
    ----------
    selector : str
        The rule's selector, as written.

    Returns
    -------
    str
        Its declarations. Later rules with the same selector (inside
        `@starting-style` or `@media`) are left out.
    """
    bodies = [body for sel, body in _rules() if sel == selector]
    assert bodies, selector
    return bodies[0]


def test_colors_come_from_root_variables() -> None:
    """Only `:root` writes a color; the other rules use its variables."""
    written = [
        (sel, line.strip())
        for sel, body in _rules()
        if sel != ":root" and sel not in LITERAL_COLORS
        for line in body.split(";")
        if COLOR.search(line)
    ]
    assert written == []


def test_used_variables_are_defined() -> None:
    """Every `var(--name)` names a variable that the stylesheet defines."""
    text = CSS.read_text(encoding="utf-8")
    defined = set(re.findall(r"(--[\w-]+)\s*:", text))
    used = set(re.findall(r"var\((--[\w-]+)", text))
    assert used - defined == set()


def test_one_accent_blue() -> None:
    """The table's accent is the page's accent: no second blue is left."""
    text = CSS.read_text(encoding="utf-8").lower()
    assert "--dt-" not in text
    assert "#1a73e8" not in text
    assert "var(--accent)" in _rule(".tc.plot.th")


@pytest.mark.parametrize(
    "selector",
    ["#hover-label", "#statusbar", ".colorbar-ticks", ".table-pager", ".column-count", ".sticky-strip"],
)
def test_changing_numbers_have_one_width(selector: str) -> None:
    """Text whose numbers change in place sets its digits to one width."""
    assert "font-variant-numeric: tabular-nums" in _rule(selector)


@pytest.mark.parametrize("selector", [".scale-menu", ".toast"])
def test_floating_elements_share_shadow_and_corners(selector: str) -> None:
    """The right-click menus and the toasts float with one shadow and one radius."""
    body = _rule(selector)
    assert "box-shadow: var(--shadow-float)" in body
    assert "border-radius: var(--radius-float)" in body
