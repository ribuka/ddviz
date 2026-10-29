"""Boundaries between the packages of ddviz and between its processes."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "ddviz"

# The ddviz packages each package may import, besides itself.
ALLOWED = {
    "shared": set(),
    "compute": {"shared"},
    "workers": set(),
    "server": {"shared", "workers"},
    "desktop": set(),
}
# Modules that may import more than their package: the worker's entry point
# imports the tasks once the worker has started.
EXCEPTIONS = {"ddviz.workers.worker": {"compute"}}


def _modules() -> list[tuple[str, Path]]:
    """Return the name and file of every module in the packages of `ALLOWED`, subpackages too."""
    return [
        (
            ".".join(
                ("ddviz", *p.relative_to(PACKAGE).with_suffix("").parts)
            ).removesuffix(".__init__"),
            p,
        )
        for package in ALLOWED
        for p in sorted((PACKAGE / package).rglob("*.py"))
    ]


def _imported_packages(path: Path) -> set[str]:
    """Return the ddviz packages a module imports, also inside functions."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "ddviz" and len(parts) > 1:
                found.add(parts[1])
    return found


@pytest.mark.parametrize(
    ("module", "path"), [pytest.param(m, p, id=m) for m, p in _modules()]
)
def test_package_imports_only_lower_layers(module: str, path: Path) -> None:
    """A module imports only its own package and the ones below it."""
    package = module.split(".")[1]
    allowed = {package} | ALLOWED[package] | EXCEPTIONS.get(module, set())
    assert _imported_packages(path) <= allowed


def test_ui_process_does_not_import_polars() -> None:
    """Every module of the UI process imports without polars, in a fresh interpreter."""
    modules = [m for m, _ in _modules() if not m.startswith("ddviz.compute")]
    code = (
        "import importlib, sys\n"
        f"for m in {modules + ['ddviz.__main__']!r}:\n"
        "    importlib.import_module(m)\n"
        "print('polars' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
