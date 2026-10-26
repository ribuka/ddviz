# instructions

- A repository for awesome-datatable: a polars table filtered, sorted, and paged on the server and shown with htmx.
- Always respond in Japanese.
- This repository is in development (0.x); backward compatibility is NOT required.
  - NEVER add or keep compatibility layers, deprecated aliases, or re-exports for old import paths.
  - When the public API (`__all__` of `awesome_datatable`), a template macro, a query parameter, or a CSS/JS name changes, update `README.md` and the tests in the same change.

## Component rules

- The package imports only the standard library, polars, and Jinja2 (`tests/test_table_imports.py`); it never depends on a web framework or on an application that uses it.
- The component loads no external resource (scripts, stylesheets, fonts, icons, or images from a CDN or any other URL).
  Keep icons as inline SVG in the templates or as files shipped in `static/` (`tests/test_no_external_resources.py`).
- `README.md` is the documentation of the component; update it whenever the component gains or changes a feature.

## Python

- Always use `uv run -m`.
- NEVER use `python -m`.
- Add NumPy-style docstrings and type hints to every function and class.
- Keep one primary responsibility per module and keep `__init__.py` a thin, explicit re-export of the public API.
- NEVER introduce circular imports or generic catch-all modules such as `utils.py`.

### Verification commands

- Run lint: `uv run -m ruff check .`
- Run tests: `uv run -m pytest --tb=short -q`
- CI runs both on every pull request to main.

## Github

### Commit

- Write the subject line as `<type>: <summary>`, with `<summary>` in Japanese and code identifiers kept as-is.
- Types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `style`, `build`, `ci`, `chore`, `revert`.
- NEVER include session URLs in commit messages or pull request descriptions.

### Applications that use this repository

- Applications depend on this repository through a git source pinned by their `uv.lock`.
- A change that an application needs is merged here first; the application then runs `uv lock --upgrade-package awesome-datatable` in its own pull request.

## Temporary files

- Create all temporary scripts and investigation files under `tmp/` at the repository root, and delete them when the task is complete.
