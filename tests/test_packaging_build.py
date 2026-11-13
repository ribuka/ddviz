"""Tests of the check that the distribution folder is not in use before a build."""

from __future__ import annotations

import ctypes
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

BUILD = Path(__file__).resolve().parents[1] / "packaging" / "build.py"

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x1
_OPEN_EXISTING = 3


def _load_build() -> ModuleType:
    """Load ``packaging/build.py``, which is not in a package.

    Returns
    -------
    ModuleType
        The module.
    """
    spec = importlib.util.spec_from_file_location("ddviz_build", BUILD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _held_like_a_running_exe(path: Path) -> Iterator[None]:
    """Hold ``path`` open and deny writes to others, as a running exe does.

    Parameters
    ----------
    path : Path
        The file to hold.

    Yields
    ------
    None
        While the file is held.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(
        str(path), _GENERIC_READ, _FILE_SHARE_READ, None, _OPEN_EXISTING, 0, None
    )
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        yield
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def test_a_missing_folder_has_no_busy_files(tmp_path: Path) -> None:
    r"""A first build, with no ``dist\ddviz`` yet, goes on."""
    assert _load_build().busy_files(tmp_path / "ddviz") == []


def test_files_nobody_holds_are_not_busy(tmp_path: Path) -> None:
    """Files closed after an earlier build are not busy."""
    (tmp_path / "_internal").mkdir()
    (tmp_path / "ddviz.exe").write_bytes(b"exe")
    (tmp_path / "_internal" / "a.dll").write_bytes(b"dll")
    assert _load_build().busy_files(tmp_path) == []


@pytest.mark.skipif(sys.platform != "win32", reason="share modes are Windows only")
def test_a_file_held_without_write_sharing_is_busy(tmp_path: Path) -> None:
    """A DLL that a running exe holds is busy, and the others are not."""
    (tmp_path / "_internal").mkdir()
    held = tmp_path / "_internal" / "a.dll"
    held.write_bytes(b"dll")
    (tmp_path / "ddviz.exe").write_bytes(b"exe")
    with _held_like_a_running_exe(held):
        assert _load_build().busy_files(tmp_path) == [held]
