# instructions

- A repository for ddviz: a drag-and-drop graph builder app for very large Parquet data, shipped as a standalone exe that runs offline.
- Always respond in Japanese.
- `docs/spec.md` holds design decisions (with their reasons) and verified facts. Read the relevant sections before changing code.
  - When a decision is made or a fact is verified (including measurement results), update `docs/spec.md` in the same change.
- This repository is in development (0.x); backward compatibility is NOT required.
  - NEVER add or keep compatibility layers, deprecated aliases, or re-exports for old import paths.

## Python

- Always use `uv run -m`.
- NEVER use `python -m`.
- Coding rules: [.agents/docs/python.md](.agents/docs/python.md)
- Running tests: [.agents/docs/pytest.md](.agents/docs/pytest.md)
- Checking the UI in a browser and E2E tests: [.agents/docs/browser.md](.agents/docs/browser.md)

### Verification commands

- Run lint: `uv run -m ruff check .`
- Run tests: `uv run -m pytest --tb=short -q`
- Run E2E tests (needs Chrome): `uv run -m pytest -m e2e --tb=short -q`
- CI runs all three on every pull request to main.

## Github

- Commit: [.agents/docs/commit.md](.agents/docs/commit.md)
- Pull request: [.agents/docs/pull-request.md](.agents/docs/pull-request.md)

## Temporary files

- Create all temporary scripts and investigation files under `tmp/<task-name>/` at the repository root (one subdirectory per task), never directly in `tmp/`.
- When the task is complete, delete only the files you created, then the empty `tmp/<task-name>/` with `rmdir`. NEVER delete `tmp/` itself or other subdirectories: other agents may be using them.
