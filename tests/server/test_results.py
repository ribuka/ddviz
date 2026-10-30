"""Tests of the drawn results' lifetimes."""

from __future__ import annotations

from pathlib import Path

from ddviz.server.results import Results


class _Index:
    """Stands for a `HoverIndex`: a result's directory and its files to close."""

    def __init__(self, out: Path) -> None:
        out.mkdir()
        self.out = out
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_a_held_result_keeps_its_directory_until_released(tmp_path: Path) -> None:
    """A result that a worker reads leaves its directory when replaced only after the last reader is done."""
    results = Results()
    old = _Index(tmp_path / "1")
    results.set_plot(old)
    with results.hold(old):
        with results.hold(old):
            results.set_overview(_Index(tmp_path / "2"))
        assert old.closed
        assert old.out.exists()
    assert not old.out.exists()


def test_a_held_result_not_replaced_stays(tmp_path: Path) -> None:
    """Releasing a result still drawn removes nothing; replacing it later does."""
    results = Results()
    index = _Index(tmp_path / "1")
    results.set_plot(index)
    with results.hold(index):
        pass
    assert index.out.exists()
    results.set_overview(_Index(tmp_path / "2"))
    assert not index.out.exists()
