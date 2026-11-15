"""Tests of the smoke test's check of a copy of the exe with DLLs marked as from the internet.

The exe is replaced by a function in place of `subprocess.run`, so these run
off Windows too (the mark is then a file named ``<dll>:Zone.Identifier``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
_DLLS = (
    "pythonnet/runtime/Python.Runtime.dll",
    "webview/lib/Microsoft.Web.WebView2.Core.dll",
    "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
    "ClrLoader.DLL",
)
_OK = '{"type":"desktop_runtime_ok"}\n'


@pytest.fixture
def modules(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ModuleType]:
    """Import ``packaging/desktop_check.py`` and ``zone_mark.py``, which are not in a package."""
    monkeypatch.syspath_prepend(str(PACKAGING))
    for name in ("desktop_check", "zone_mark"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import desktop_check
    import zone_mark

    return desktop_check, zone_mark


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """Make a distribution folder with an exe and the DLLs, unmarked."""
    folder = tmp_path / "dist" / "ddviz"
    for name in _DLLS:
        path = folder / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ" + name.encode())
    (folder / "_internal" / "x.pyd").write_bytes(b"x")
    (folder / "ddviz.exe").write_bytes(b"MZ")
    return folder


def _proc(returncode: int = 0, stdout: str = _OK, stderr: str = "") -> Callable:
    """Return a `subprocess.run` that answers once with this result."""

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return run


def _unblocking(zone_mark: ModuleType, calls: list[list[str]], change: bool = False) -> Callable:
    """Return a `subprocess.run` that unblocks the exe's DLLs as the real check does."""

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        for dll in zone_mark.dlls(Path(args[0]).parent / "_internal"):
            if zone_mark.is_marked(dll):
                os.remove(zone_mark.stream(dll))
            if change:
                dll.write_bytes(b"changed")
        return subprocess.CompletedProcess(args, 0, _OK, "")

    return run


# --- running the exe's check


def test_run_check_passes_on_the_success_line(modules: tuple) -> None:
    """Exit 0 with the one JSON line passes, and the exe gets the option with a timeout."""
    desktop_check, _ = modules
    seen = {}

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen.update(args=args, **kwargs)
        return subprocess.CompletedProcess(args, 0, _OK, "")

    desktop_check.run_check(Path("ddviz.exe"), run)
    assert seen["args"] == ["ddviz.exe", "--check-desktop-runtime"]
    assert seen["timeout"] == 120


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ({"returncode": 1, "stdout": "", "stderr": "Failed to resolve"}, "exited 1"),
        ({"stdout": ""}, "printed"),
        ({"stdout": "ok\n"}, "printed"),
        ({"stdout": '{"type":"other"}\n'}, "printed"),
        ({"stdout": _OK + _OK}, "printed"),
    ],
    ids=["non-zero exit", "no output", "not json", "other json", "twice"],
)
def test_run_check_fails_without_the_success_line(
    modules: tuple, result: dict, message: str
) -> None:
    """A non-zero exit or any output but the success line fails."""
    desktop_check, _ = modules
    with pytest.raises(RuntimeError, match=message):
        desktop_check.run_check(Path("ddviz.exe"), _proc(**result))


def test_run_check_fails_on_a_timeout(modules: tuple) -> None:
    """A check that does not end in time fails."""
    desktop_check, _ = modules

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    with pytest.raises(RuntimeError, match="took over"):
        desktop_check.run_check(Path("ddviz.exe"), run)


# --- marking


def test_mark_reads_back(modules: tuple, tmp_path: Path) -> None:
    """The mark is written and found."""
    _, zone_mark = modules
    dll = tmp_path / "a.dll"
    dll.write_bytes(b"MZ")
    zone_mark.mark(dll)
    assert zone_mark.is_marked(dll)
    with open(zone_mark.stream(dll), "rb") as f:
        assert f.read() == b"[ZoneTransfer]\r\nZoneId=3\r\n"


def test_mark_fails_when_it_cannot_be_written(modules: tuple, tmp_path: Path) -> None:
    """A mark that cannot be written fails instead of being skipped."""
    _, zone_mark = modules
    with pytest.raises(RuntimeError, match="cannot mark"):
        zone_mark.mark(tmp_path / "missing" / "a.dll")


def test_mark_fails_when_it_does_not_read_back(
    modules: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A mark that reads back differently (a file system that drops it) fails."""
    _, zone_mark = modules
    dll = tmp_path / "a.dll"
    dll.write_bytes(b"MZ")
    monkeypatch.setattr(zone_mark, "MARK", b"[ZoneTransfer]")
    real_open = open

    def short_open(path: str, mode: str = "r", *args: object) -> object:
        f = real_open(path, mode, *args)
        if "r" in mode:
            f.read = lambda *a: b""
        return f

    monkeypatch.setattr("builtins.open", short_open)
    with pytest.raises(RuntimeError, match="reads back"):
        zone_mark.mark(dll)


# --- the marked copy


def test_check_marked_copy_marks_the_copy_and_checks_twice(
    modules: tuple, dist: Path, tmp_path: Path
) -> None:
    """Every DLL of the copy is marked, unblocked by the exe, and checked again; the original stays unmarked."""
    desktop_check, zone_mark = modules
    calls: list[list[str]] = []
    work = tmp_path / "tmp" / "exe-smoke"
    marked_seen = []

    unblock = _unblocking(zone_mark, calls)

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        internal = Path(args[0]).parent / "_internal"
        marked_seen.append([zone_mark.is_marked(d) for d in zone_mark.dlls(internal)])
        return unblock(args, **kwargs)

    assert desktop_check.check_marked_copy(dist, work, run) == len(_DLLS)
    assert len(calls) == 2
    assert Path(calls[0][0]).parent.parent.parent == work
    assert calls[0][0] != str(dist / "ddviz.exe")
    assert marked_seen == [[True] * len(_DLLS), [False] * len(_DLLS)]
    assert not any(zone_mark.is_marked(d) for d in zone_mark.dlls(dist))
    assert list(work.iterdir()) == []


def test_check_marked_copy_fails_when_marks_remain(
    modules: tuple, dist: Path, tmp_path: Path
) -> None:
    """A check that passes but leaves the marks fails."""
    desktop_check, _ = modules
    work = tmp_path / "work"
    with pytest.raises(RuntimeError, match="still marked"):
        desktop_check.check_marked_copy(dist, work, _proc())
    assert list(work.iterdir()) == []


def test_check_marked_copy_fails_when_a_dll_changes(
    modules: tuple, dist: Path, tmp_path: Path
) -> None:
    """Unblocking must not change the DLLs' content."""
    desktop_check, zone_mark = modules
    with pytest.raises(RuntimeError, match="changed"):
        desktop_check.check_marked_copy(
            dist, tmp_path / "work", _unblocking(zone_mark, [], change=True)
        )


def test_check_marked_copy_fails_when_marking_fails(
    modules: tuple, dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mark that cannot be written fails the smoke test without running the exe."""
    desktop_check, zone_mark = modules

    def fail(path: Path) -> None:
        raise RuntimeError(f"cannot mark {path}")

    monkeypatch.setattr(zone_mark, "mark", fail)
    work = tmp_path / "work"
    with pytest.raises(RuntimeError, match="cannot mark"):
        desktop_check.check_marked_copy(dist, work, lambda *a, **k: pytest.fail("ran"))
    assert list(work.iterdir()) == []


def test_check_marked_copy_fails_without_the_required_dlls(
    modules: tuple, dist: Path, tmp_path: Path
) -> None:
    """A copy without pythonnet's or the SDK's DLLs fails, not passes with less to check."""
    desktop_check, _ = modules
    (dist / "_internal" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll").unlink()
    with pytest.raises(RuntimeError, match="Microsoft.Web.WebView2.Core.dll"):
        desktop_check.check_marked_copy(
            dist, tmp_path / "work", lambda *a, **k: pytest.fail("ran")
        )


def test_check_marked_copy_fails_on_a_timeout_and_cleans_up(
    modules: tuple, dist: Path, tmp_path: Path
) -> None:
    """A check that times out fails, and the folder of the run is removed."""
    desktop_check, _ = modules
    work = tmp_path / "work"
    (work / "other").mkdir(parents=True)

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    with pytest.raises(RuntimeError, match="took over"):
        desktop_check.check_marked_copy(dist, work, run)
    assert [p.name for p in work.iterdir()] == ["other"]
