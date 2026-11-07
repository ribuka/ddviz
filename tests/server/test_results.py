"""Tests of the drawn results' lifetimes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ddviz.server.results import Results


class _Index:
    """Stands for a `HoverIndex`: a result's directory, its files to close and their bytes."""

    def __init__(self, out: Path, hover_bytes: int = 0) -> None:
        out.mkdir()
        self.out = out
        self.closed = False
        self.manifest = SimpleNamespace(hover_bytes=hover_bytes)

    def close(self) -> None:
        self.closed = True


def test_a_held_result_keeps_its_directory_until_released(tmp_path: Path) -> None:
    """A result that a worker reads leaves its directory, and counts its hover files, when replaced only after the last reader is done."""
    results = Results()
    old = _Index(tmp_path / "1", 100)
    results.set_plot(old)
    with results.hold(old):
        with results.hold(old):
            assert results.held_bytes == 0
            results.set_overview(_Index(tmp_path / "2", 7))
        assert old.closed
        assert old.out.exists()
        assert results.held_bytes == 100
        # Another replacement does not forget it.
        results.set_plot(_Index(tmp_path / "3", 9))
        assert results.held_bytes == 100
    assert not old.out.exists()
    assert results.held_bytes == 0


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


def test_only_a_new_plot_result_moves_the_plot_id(tmp_path: Path) -> None:
    """A new plot's result drops the views and selections of the older plot; a resized overview or a view does not."""
    results = Results()
    assert results.plot_id == 0
    results.set_plot(_Index(tmp_path / "1"))
    assert results.plot_id == 1
    results.set_view(_Index(tmp_path / "2"))
    results.set_overview(_Index(tmp_path / "3"))
    assert results.plot_id == 1
    results.set_plot(_Index(tmp_path / "4"))
    assert results.plot_id == 2
