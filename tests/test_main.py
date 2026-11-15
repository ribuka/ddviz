"""Tests of the command line: what runs before the window, and which starts unblock the DLLs."""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from ddviz import __main__ as entry
from ddviz.desktop import dll_access, messages, runlog, runtime_check

_WINDOW = "ddviz.desktop.window"


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the import of the window module and the window's run, without opening it."""
    done: list[str] = []
    fake = types.ModuleType(_WINDOW)
    fake.run_window = lambda *a: done.append("run") or 0
    monkeypatch.setitem(sys.modules, _WINDOW, fake)
    real_import = builtins.__import__

    def recording_import(name: str, *args: object, **kwargs: object) -> object:
        if name == _WINDOW:
            done.append("import window")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", recording_import)
    monkeypatch.setattr(runlog.RunLog, "start", lambda self: pytest.fail("run log"))
    return done


def _argv(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    """Set the command line."""
    monkeypatch.setattr(sys, "argv", ["ddviz", *args])


def _exe(monkeypatch: pytest.MonkeyPatch, bundle: Path) -> None:
    """Run as the PyInstaller exe on Windows with this bundle."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)


def test_the_window_start_unblocks_before_importing_the_window(
    monkeypatch: pytest.MonkeyPatch, steps: list[str]
) -> None:
    """The DLLs are unblocked before the window module (and pythonnet) is imported."""
    monkeypatch.setattr(
        dll_access, "unblock_or_warn", lambda warn: steps.append("unblock") or True
    )
    _argv(monkeypatch)
    assert entry.main() == 0
    assert steps == ["unblock", "import window", "run"]


def test_the_exe_unblocks_its_bundle_before_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, steps: list[str]
) -> None:
    """In the exe, a marked DLL of the bundle is unblocked without a message."""
    dll = tmp_path / "Python.Runtime.dll"
    dll.write_bytes(b"MZ")
    with open(f"{dll}:Zone.Identifier", "wb") as f:
        f.write(b"[ZoneTransfer]\r\nZoneId=3\r\n")
    _exe(monkeypatch, tmp_path)
    monkeypatch.setattr(messages, "show_warning", lambda text: pytest.fail(text))
    _argv(monkeypatch)
    assert entry.main() == 0
    assert steps == ["import window", "run"]
    assert not Path(f"{dll}:Zone.Identifier").exists()


def test_a_failure_warns_once_and_stops_before_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, steps: list[str]
) -> None:
    """A bundle that cannot be unblocked shows one message and exits 1, before the window and the run log."""

    def scan(folder: Path) -> list:
        raise PermissionError(13, "Access is denied", str(folder))

    _exe(monkeypatch, tmp_path)
    monkeypatch.setattr(dll_access, "_scan", scan)
    warned: list[str] = []
    monkeypatch.setattr(messages, "show_warning", warned.append)
    _argv(monkeypatch)
    assert entry.main() == 1
    assert len(warned) == 1
    assert str(tmp_path) in warned[0]
    assert steps == []


def test_development_does_not_unblock(
    monkeypatch: pytest.MonkeyPatch, steps: list[str]
) -> None:
    """Run from the source, the window starts without touching any DLL."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(dll_access, "unblock_bundle", lambda root: pytest.fail("unblock"))
    _argv(monkeypatch)
    assert entry.main() == 0
    assert steps == ["import window", "run"]


@pytest.fixture
def no_unblock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run as the exe, and fail if anything is unblocked."""
    _exe(monkeypatch, tmp_path)
    monkeypatch.setattr(dll_access, "unblock_or_warn", lambda warn: pytest.fail("unblock"))
    monkeypatch.setattr(dll_access, "unblock_bundle", lambda root: pytest.fail("unblock"))


def test_a_worker_does_not_unblock(
    monkeypatch: pytest.MonkeyPatch, no_unblock: None
) -> None:
    """``--worker`` runs the worker only."""
    from ddviz.workers import worker

    monkeypatch.setattr(worker, "main", lambda: 0)
    _argv(monkeypatch, "--worker")
    assert entry.main() == 0


def test_the_port_does_not_unblock(
    monkeypatch: pytest.MonkeyPatch, no_unblock: None, tmp_path: Path, steps: list[str]
) -> None:
    """``--port`` serves for a browser without unblocking or opening the window."""
    import uvicorn

    served = []
    monkeypatch.setattr(entry, "make_app", lambda *a: "app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.append(app))
    _argv(monkeypatch, str(tmp_path), "--port", "8000")
    assert entry.main() == 0
    assert served == ["app"]
    assert steps == []


def test_help_does_not_unblock_nor_list_the_check(
    monkeypatch: pytest.MonkeyPatch,
    no_unblock: None,
    capsys: pytest.CaptureFixture[str],
    steps: list[str],
) -> None:
    """``--help`` only prints the usage, which leaves out the internal check."""
    _argv(monkeypatch, "--help")
    with pytest.raises(SystemExit) as caught:
        entry.main()
    assert caught.value.code == 0
    assert "--check-desktop-runtime" not in capsys.readouterr().out
    assert steps == []


def test_the_check_runs_alone(
    monkeypatch: pytest.MonkeyPatch, steps: list[str]
) -> None:
    """``--check-desktop-runtime`` runs the check, not the window."""
    monkeypatch.setattr(runtime_check, "check_desktop_runtime", lambda: 0)
    _argv(monkeypatch, "--check-desktop-runtime")
    assert entry.main() == 0
    assert steps == []


@pytest.mark.parametrize(
    "args",
    [
        ["--check-desktop-runtime", "data.parquet"],
        ["--check-desktop-runtime", "--recursive"],
        ["--check-desktop-runtime", "--port", "8000"],
        ["--check-desktop-runtime", "--worker"],
        ["--worker", "--check-desktop-runtime"],
    ],
)
def test_the_check_takes_no_other_arguments(
    monkeypatch: pytest.MonkeyPatch, args: list[str], steps: list[str]
) -> None:
    """The check with a path, a start option or ``--worker`` is an argparse error."""
    from ddviz.workers import worker

    monkeypatch.setattr(
        runtime_check, "check_desktop_runtime", lambda: pytest.fail("check ran")
    )
    monkeypatch.setattr(worker, "main", lambda: pytest.fail("worker ran"))
    _argv(monkeypatch, *args)
    with pytest.raises(SystemExit) as caught:
        entry.main()
    assert caught.value.code == 2
    assert steps == []


def test_settings_that_cannot_be_read_warn_and_stop_before_the_window(
    monkeypatch: pytest.MonkeyPatch, steps: list[str]
) -> None:
    """A settings file that cannot be read, or has a wrong value, is told in a message box with the error (its file or key), and the window does not open."""
    from ddviz.server.settings_store import SettingsStore

    def broken(cls: type, path: Path | None = None) -> None:
        raise ValueError("plot.max_levels needs a positive integer: 0")

    monkeypatch.setattr(SettingsStore, "load", classmethod(broken))
    monkeypatch.setattr(dll_access, "unblock_or_warn", lambda warn: True)
    warned: list[str] = []
    monkeypatch.setattr(messages, "show_warning", warned.append)
    _argv(monkeypatch)
    assert entry.main() == 1
    assert warned == [
        f"{entry.SETTINGS_UNREADABLE}\n\nplot.max_levels needs a positive integer: 0"
    ]
    assert steps == []
