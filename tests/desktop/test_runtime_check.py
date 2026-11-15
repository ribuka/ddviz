"""Tests of the exe's check that the window's .NET DLLs load, without a window."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ddviz.desktop import messages, runtime_check
from ddviz.desktop.dll_access import UnblockError
from ddviz.desktop.runtime_check import ASSEMBLIES, PLATFORMS, check_desktop_runtime


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Record the unblocking and the imports, as in the exe; fail on a message box."""
    done: list[str] = []
    monkeypatch.setattr(runtime_check, "bundle_dir", lambda: tmp_path)
    monkeypatch.setattr(
        runtime_check, "unblock_bundle", lambda root: done.append(f"unblock {root}") or 0
    )
    monkeypatch.setattr(runtime_check, "_import", lambda name: done.append(name))
    monkeypatch.setattr(runtime_check, "_loaded_assemblies", lambda: {"System", *ASSEMBLIES})
    monkeypatch.setattr(messages, "show_warning", lambda text: pytest.fail(text))
    return done


def _run() -> tuple[int, str, str]:
    """Run the check and return its exit code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    code = check_desktop_runtime(out, err)
    return code, out.getvalue(), err.getvalue()


def test_unblocks_then_imports_the_platforms_and_prints_ok(
    steps: list[str], tmp_path: Path
) -> None:
    """The bundle is unblocked before WinForms, then Edge Chromium, is imported."""
    code, out, err = _run()
    assert code == 0
    assert steps == [f"unblock {tmp_path}", *PLATFORMS]
    assert PLATFORMS == ("webview.platforms.winforms", "webview.platforms.edgechromium")
    assert out.splitlines() == ['{"type":"desktop_runtime_ok"}']
    assert json.loads(out) == {"type": "desktop_runtime_ok"}
    assert err == ""


def test_an_import_failure_exits_1_with_the_exception(
    monkeypatch: pytest.MonkeyPatch, steps: list[str], tmp_path: Path
) -> None:
    """A platform that fails to load is reported on stderr, and nothing on stdout."""

    def fail(name: str) -> None:
        raise RuntimeError(f"Failed to resolve Python.Runtime.Loader.Initialize ({name})")

    monkeypatch.setattr(runtime_check, "_import", fail)
    code, out, err = _run()
    assert code == 1
    assert out == ""
    assert str(tmp_path) in err
    assert "Failed to resolve Python.Runtime.Loader.Initialize" in err
    assert "Traceback" in err


def test_a_missing_sdk_assembly_exits_1(
    monkeypatch: pytest.MonkeyPatch, steps: list[str]
) -> None:
    """The imports alone do not pass: the SDK's assemblies must be loaded."""
    monkeypatch.setattr(runtime_check, "_loaded_assemblies", lambda: {ASSEMBLIES[0]})
    code, out, err = _run()
    assert code == 1
    assert out == ""
    assert ASSEMBLIES[1] in err


def test_an_unblock_failure_exits_1_before_the_imports(
    monkeypatch: pytest.MonkeyPatch, steps: list[str], tmp_path: Path
) -> None:
    """A DLL that cannot be unblocked stops the check, with its path, and no dialog."""
    dll = tmp_path / "Python.Runtime.dll"

    def fail(root: Path) -> int:
        raise UnblockError(dll, "remove", PermissionError(13, "Access is denied"))

    monkeypatch.setattr(runtime_check, "unblock_bundle", fail)
    code, out, err = _run()
    assert code == 1
    assert out == ""
    assert steps == []
    assert str(dll) in err
    assert "Access is denied" in err


def test_development_imports_without_unblocking(
    monkeypatch: pytest.MonkeyPatch, steps: list[str]
) -> None:
    """Run from the source there is no bundle to unblock."""
    monkeypatch.setattr(runtime_check, "bundle_dir", lambda: None)
    code, _, _ = _run()
    assert code == 0
    assert steps == list(PLATFORMS)
