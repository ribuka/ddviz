"""Tests of the column list's search history."""

from __future__ import annotations

import json
from pathlib import Path

from ddviz.server.history import SearchHistory, history_file


def _history(tmp_path: Path, limit: int = 20) -> SearchHistory:
    paths = [str(tmp_path / "a.parquet")]
    return SearchHistory(history_file(tmp_path / "history", paths), paths, limit)


def test_newest_first_and_the_same_keyword_moves_to_the_top(tmp_path: Path) -> None:
    """A keyword searched again, in any case or spacing, moves first instead of repeating."""
    history = _history(tmp_path)
    history.add("L3_S29")
    history.add("L0 S1")
    assert history.add("  l3_s29 ") == ["l3_s29", "L0 S1"]
    assert history.add("L0   S1") == ["L0 S1", "l3_s29"]


def test_blank_keywords_are_not_kept(tmp_path: Path) -> None:
    """An empty search box adds nothing and writes no file."""
    history = _history(tmp_path)
    assert history.add("   ") == []
    assert not history.path.exists()


def test_the_oldest_go_past_the_limit(tmp_path: Path) -> None:
    """Only `limit` keywords stay, the newest; a lower limit cuts the file when read."""
    history = _history(tmp_path, limit=3)
    for word in "abcde":
        history.add(word)
    assert history.words() == ["e", "d", "c"]
    assert _history(tmp_path, limit=2).words() == ["e", "d"]


def test_remove_one_or_all(tmp_path: Path) -> None:
    """One keyword goes on its own; clear removes them all."""
    history = _history(tmp_path)
    for word in "abc":
        history.add(word)
    assert history.remove("b") == ["c", "a"]
    assert history.remove("missing") == ["c", "a"]
    assert history.clear() == []
    assert history.words() == []


def test_the_file_names_its_input(tmp_path: Path) -> None:
    """The file holds the input's paths beside the keywords."""
    history = _history(tmp_path)
    history.add("x")
    data = json.loads(history.path.read_text(encoding="utf-8"))
    assert data == {"paths": history.paths, "words": ["x"]}


def test_each_input_has_its_own_file(tmp_path: Path) -> None:
    """Different inputs, or the same files in another order, use different files."""
    root = tmp_path / "history"
    a, b = str(tmp_path / "a.parquet"), str(tmp_path / "b.parquet")
    files = {history_file(root, p) for p in ([a], [b], [a, b], [b, a])}
    assert len(files) == 4
    assert history_file(root, [a]) == history_file(root, [a])


def test_a_broken_file_reads_as_empty(tmp_path: Path) -> None:
    """A file that is not the history reads as no keywords, and the next add rewrites it."""
    history = _history(tmp_path)
    history.path.parent.mkdir(parents=True)
    history.path.write_text("{broken", encoding="utf-8")
    assert history.words() == []
    assert history.add("x") == ["x"]
