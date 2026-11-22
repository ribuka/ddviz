# Python coding

Follow [coding.md](coding.md) first; this file adds what is specific to Python.

## Rules

- Add docstrings for all functions and classes with NumPy style.
- Add type hints for all function parameters and return types.

## Structure

- State each module's responsibility in its module docstring.
- Keep `__init__.py` files to a docstring. NEVER re-export names from them: importing the package would then load every module behind those names, with their dependencies.

## Lint

- ruff checks the limits of coding.md (C901, PLR0912, PLR0915) with the values in `pyproject.toml`, and fails on a stale `noqa` (RUF100). Existing debt is marked `# noqa: <codes>` on the `def` line.
- ruff also flags unused arguments (ARG; not in tests, where pytest passes fixtures). An argument a caller's signature requires stays, with `# noqa: ARG001 - <why>`.

## Tests

- Before adding a helper or fixture, search the `conftest.py` files under `tests/` and the test file you are editing.
- Share setup through pytest fixtures scoped as narrowly as the tests that use them.
