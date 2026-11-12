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
- Test the JS logic (axis dialog validation, tick and format attributes, time strings, legend and toast logic) in `tests/js` (marker `js`), not in E2E.
  - `uv run -m pytest -m js --tb=short -q` calls the static modules in a blank browser page without the app (`tests/js/conftest.py`: `js_page`, and `clock_page` for `page.clock`). The default `uv run -m pytest` deselects them.
  - An E2E test checks validation with one value only: the error shows beside the field and the plot does not change.
  - CI runs them in the `E2E (1/3)` job, before its E2E tests.
- To debug a failure, add `--tracing retain-on-failure --headed` and open the trace with `uv run -m playwright show-trace test-results/<test>/trace.zip`.
- CI runs the E2E job on ubuntu-latest and uploads `test-results/` as an artifact when it fails.

### Do not depend on font metrics

CI runs on Linux, where the fonts differ from Windows (no Segoe UI; Japanese text and line heights differ). A size measured locally does not hold there.

- Never make a test's premise a value that text width or height decides: whether something overflows or fits, how many lines text wraps to, or whether a margin grows.
- To test overflow or wrapping, use a condition that makes it certain with any font: shrink the window well past the limit, or use a string far longer (or a number with far more digits) than needed.
- When comparing heights or widths, allow a margin for the font difference instead of an exact value; compare positions measured on the page with each other rather than with numbers measured on Windows.
- Past failures on CI:
  - 786d511: the left-margin E2E assumed that tick labels like `1.06e+5` overflow the 50px margin; the narrower Linux font fit them. Rewritten with ticks of more digits (`1.00020e+5`) that exceed 50px with any font.
  - 3b7dbbf (PR #112; `docs/spec.md`, "フッターのエラーと警告"): with the low line height of the Linux font, the warning icon made the footer taller, the plot area shrank and re-aggregated, and the E2E drag was taken as a zoom.
  - `docs/spec.md`, "最悪のデータでの表示" (確かめたこと): the status-bar height check allows an increase under 10px, because Japanese text makes it 2px taller on Linux.
  - 6b48d0c (PR #137): the E2E assumed the filter cards overflow a 520px-high window; locally (Segoe UI) they overflowed by only 32px, and on CI they did not overflow. Rewritten to shrink the window to 360px.
