# JavaScript coding

Follow [coding.md](coding.md) first; this file adds what is specific to the JS under `src/ddviz/static/js/`.

## Rules

- Write plain ES modules served as they are. NEVER add a build step or npm dependencies ("Python だけの体制" in `docs/spec.md`).
- Start each module with a comment that states its responsibility, and put a comment above each function saying what it does and what it returns.

## Structure

- `app.js` wires the page together. Do not add new behavior to it; put the behavior in a focused module and call it from `app.js`.
- When JS needs a value that Python also defines, add the copy to `tests/js/test_mirrored_constants.py` so the two are checked against each other.

## Complexity limits

- `tests/test_js_complexity.py` checks the limits of coding.md for each function, with the codes of ruff (C901, PLR0912, PLR0915). A nested function is measured on its own. Existing debt is marked `// noqa: <codes>` at the end of the line the function starts on.

## Tests

- Test JS logic with unit tests in `tests/js/test_<module>.py` (marker `js`), not in E2E. Keep E2E for flows through the whole page ("E2E テスト" in `docs/spec.md`).
