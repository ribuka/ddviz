"""The progress stages the compute side sends are the ones the page names."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "ddviz"
COMPUTE = SRC / "compute"
APP_JS = SRC / "static" / "js" / "app.js"

# Stages the page does not name in its status line (`STAGES` of ``app.js``).
NOT_IN_STAGES = {
    "convert": "the cover shows it (`showConverting`)",
    "export": "the save's toast shows it (`saves.js`)",
    "values": "the save's toast shows it (`saves.js`)",
    "summary": "the summary pool's progress is not streamed",
    "level_index": "the levels pool's progress is not streamed",
    "level_search": "the levels pool's progress is not streamed",
}


def _sent_stages() -> set[str]:
    """Return the stages the compute side names in ``progress("…")`` and ``"stage": "…"``."""
    stages: set[str] = set()
    for module in COMPUTE.rglob("*.py"):
        text = module.read_text(encoding="utf-8")
        stages |= set(re.findall(r'\bprogress\("([a-z_]+)"\)', text))
        stages |= set(re.findall(r'"stage": "([a-z_]+)"', text))
    return stages


def _named_stages() -> set[str]:
    """Return the keys of ``const STAGES = {…}`` in ``app.js``."""
    text = APP_JS.read_text(encoding="utf-8")
    body = re.search(r"const STAGES = \{(.*?)\};", text, re.DOTALL)
    assert body is not None
    return set(re.findall(r"^\s*([a-z_]+):", body.group(1), re.MULTILINE))


def test_the_page_names_every_stage_sent() -> None:
    """A stage the compute side sends is in `STAGES`, or in `NOT_IN_STAGES` with its reason."""
    sent = _sent_stages()
    assert sent
    missing = sent - _named_stages() - set(NOT_IN_STAGES)
    assert not missing, sorted(missing)
