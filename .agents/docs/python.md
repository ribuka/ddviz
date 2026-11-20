# Python coding

## Rules

- Add docstrings for all functions and classes with NumPy style.
- Add type hints for all function parameters and return types.

## Keeping the code easy to change

Every change must leave the code it touches no harder to change than before.

### Before writing code

- Search for code that already does the same thing (`git grep` for the operation, not only the name). Reuse or extend it instead of writing another copy.
- Choose where new code goes from "パッケージ構成" in `docs/spec.md` (the packages, what each may import, and the modules inside `server` and `compute`) and from the module docstrings. `tests/test_layers.py` checks the import boundaries.
- If no module's docstring covers the new code without adding "and", create a focused module and add it to the module table in `docs/spec.md`.

### Scope of a change

- Keep the change to what the task needs. The following are part of the task, not extra work:
  - Extracting logic the change would otherwise duplicate. Extract when the copies hold the same knowledge and would change for the same reason, not because they look alike.
  - Deleting functions, parameters, and branches the change made unused.
  - Updating the module docstring when the module's responsibility changes.
- Put such refactoring in its own `refactor:` commit before the change that needs it, and keep behavior the same in that commit.
- Do NOT refactor code the task does not touch. List debt noticed there in the PR description under "気づいた負債" instead.

### Modules

- Keep one primary responsibility per module, stated in its docstring.
- NEVER append a distinct responsibility to an existing module; create a focused module or package instead.
- Keep `__init__.py` files to a docstring. NEVER re-export names; import from the module that defines them. When refactoring changes an import path, update every reference.
- NEVER introduce circular imports or generic catch-all modules such as `utils.py`.
- Size is a reason to look, not a reason to split. NEVER split modules based on line count alone.

### Functions and classes

- For a variant of existing behavior, pass the difference as a value or a callable instead of copying the function.
- Prefer a separate function over a boolean parameter that switches what a function does.
- Do not grow a function by adding another mode branch; split it into stages first (as a `refactor:` commit).

### Tests

- The rules above apply to tests too. Before adding a helper or fixture, search `conftest.py` (`tests/`, `tests/e2e/`, `tests/js/`) and the test file you are editing.
- Organize tests by responsibility and share setup through narrowly scoped pytest fixtures.
