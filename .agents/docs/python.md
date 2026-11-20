# Python coding

Follow [coding.md](coding.md) first; this file adds what is specific to Python.

## Rules

- Add docstrings for all functions and classes with NumPy style.
- Add type hints for all function parameters and return types.

## Structure

- State each module's responsibility in its module docstring.
- Choose the package for new code from "パッケージ構成" in `docs/spec.md` (the packages, what each may import, and the modules inside `server` and `compute`). `tests/test_layers.py` checks the import boundaries.
- When adding a module to `server` or `compute`, add it to its module table in `docs/spec.md`.
- Keep `__init__.py` files to a docstring. NEVER re-export names from them (importing `ddviz.compute` would then load polars).
