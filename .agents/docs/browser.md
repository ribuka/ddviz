# Checking the UI in a browser

## When

- After changing anything the screen shows or does (`src/ddviz/static`, or a server API the screen calls), check it in a browser before committing.
- Changes that only touch computation or tests need no browser check.

## Start the UI server for a browser

- Make the test data with a script under `tmp/` (synthetic Parquet; delete it when done).
- Start the server without a window; it prints the URL with the token of this run:
  - `uv run -m ddviz <file-or-folder> --port 8765`
- Open the printed `http://127.0.0.1:8765/?token=...` once. The server moves the token into a cookie and redirects to `/`; reloads then work with the cookie.
  - Without the token, every page, file and API answers 403 (`docs/spec.md`, "認証").
- In Claude Code's desktop app, run the server in the background and open the URL in the built-in browser.
- Stop the server when done; it kills its worker processes.

## What to check

- The console has no errors (`Error: <path> attribute d` from plotly is a known open issue in `docs/spec.md`, "未確認事項").
- The changed operation works on screen: drop columns on the builder, draw, hover, zoom, select, filter, as relevant.
- When a step was measured (times, sizes), write the result into `docs/spec.md` with the browser used.
  - The built-in browser is not WebView2. Timing that matters for the app is measured in the exe (`docs/spec.md`, "最小構成の exe").

## E2E tests

- `uv run -m pytest -m e2e --tb=short -q` runs the browser tests in `tests/e2e` with the installed Chrome (`--browser-channel chrome` in `pyproject.toml`).
  - The default `uv run -m pytest` deselects them.
  - Without Chrome: `uv run -m playwright install chrome`.
- Keep E2E to the end-to-end flow (load, draw, hover); test the logic in `tests/server` and `tests/compute`.
- To debug a failure, add `--tracing retain-on-failure --headed` and open the trace with `uv run -m playwright show-trace test-results/<test>/trace.zip`.
- CI runs the E2E job on ubuntu-latest and uploads `test-results/` as an artifact when it fails.
