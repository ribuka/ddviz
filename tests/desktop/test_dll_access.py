"""Tests of unblocking the exe's bundled DLLs that carry the Mark of the Web.

The mark is the stream ``<file>:Zone.Identifier``: an alternate data stream
on NTFS, and a file of that name off Windows, so the tests run on both.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path

import pytest

from ddviz.desktop import dll_access
from ddviz.desktop.dll_access import (
    UnblockError,
    bundle_dir,
    bundled_dlls,
    failure_message,
    powershell_literal,
    unblock_bundle,
    unblock_dll,
    unblock_or_warn,
)

_MARK = b"[ZoneTransfer]\r\nZoneId=3\r\n"


def _mark(path: Path) -> None:
    """Give a file the Mark of the Web."""
    with open(f"{path}:Zone.Identifier", "wb") as f:
        f.write(_MARK)


def _marked(path: Path) -> bool:
    """Tell whether a file has the Mark of the Web."""
    return os.path.exists(f"{path}:Zone.Identifier")


def _dll(path: Path, marked: bool = True) -> Path:
    """Write a DLL-named file, marked or not."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + path.name.encode())
    if marked:
        _mark(path)
    return path


def _sha(path: Path) -> str:
    """Return the SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- the bundle's folder


def test_bundle_dir_is_meipass_in_the_exe_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The PyInstaller exe on Windows unblocks its ``sys._MEIPASS``."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundle_dir() == tmp_path


def test_bundle_dir_is_none_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``sys.frozen`` nothing is unblocked."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert bundle_dir() is None


def test_bundle_dir_is_none_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A frozen app off Windows has no marks to remove."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert bundle_dir() is None


# --- listing the DLLs


def test_bundled_dlls_finds_dlls_in_subfolders_in_any_case(tmp_path: Path) -> None:
    """``.dll`` and ``.DLL`` in the folder and its subfolders are found, other files are not."""
    dlls = {
        _dll(tmp_path / "a.dll", marked=False),
        _dll(tmp_path / "pythonnet" / "runtime" / "Python.Runtime.DLL", marked=False),
        _dll(tmp_path / "webview" / "lib" / "Microsoft.Web.WebView2.Core.Dll", marked=False),
    }
    (tmp_path / "b.pyd").write_bytes(b"x")
    (tmp_path / "c.dll.txt").write_bytes(b"x")
    (tmp_path / "d.dll").mkdir()
    assert set(bundled_dlls(tmp_path)) == dlls


def test_bundled_dlls_does_not_follow_a_symbolic_link(tmp_path: Path) -> None:
    """A linked folder outside the bundle is not entered, nor a linked DLL taken."""
    root = tmp_path / "bundle"
    outside = _dll(tmp_path / "outside" / "x.dll", marked=False)
    inside = _dll(root / "in.dll", marked=False)
    try:
        os.symlink(outside.parent, root / "linked", target_is_directory=True)
        os.symlink(outside, root / "linked.dll")
    except OSError as error:  # Windows without the privilege
        pytest.skip(f"cannot make a symbolic link: {error}")
    assert list(bundled_dlls(root)) == [inside]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are NTFS's")
def test_bundled_dlls_does_not_follow_a_junction(tmp_path: Path) -> None:
    """A junction to a folder outside the bundle is not entered."""
    import _winapi

    root = tmp_path / "bundle"
    _dll(tmp_path / "outside" / "x.dll", marked=False)
    inside = _dll(root / "in.dll", marked=False)
    _winapi.CreateJunction(str(tmp_path / "outside"), str(root / "junction"))
    assert list(bundled_dlls(root)) == [inside]


class _Entry:
    """A folder entry that is a reparse point by its attributes only."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)
        self.name = path.name

    def is_symlink(self) -> bool:
        return False

    def is_junction(self) -> bool:
        return False

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return True

    def is_file(self, follow_symlinks: bool = True) -> bool:
        return False

    def stat(self, follow_symlinks: bool = True) -> os.stat_result:
        class _Stat:
            st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT

        return _Stat()


def test_bundled_dlls_skips_other_reparse_points(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A folder with the reparse point attribute is not entered, whatever its kind."""
    scanned = []

    def scan(folder: Path) -> list:
        scanned.append(folder)
        return [_Entry(folder / "mount")]

    monkeypatch.setattr(dll_access, "_scan", scan)
    assert list(bundled_dlls(tmp_path)) == []
    assert scanned == [tmp_path]


def test_bundled_dlls_reports_a_folder_that_cannot_be_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A listing error is raised with its folder, not taken as an empty folder."""

    def scan(folder: Path) -> list:
        raise PermissionError(13, "Access is denied", str(folder))

    monkeypatch.setattr(dll_access, "_scan", scan)
    with pytest.raises(UnblockError) as caught:
        list(bundled_dlls(tmp_path))
    assert caught.value.path == tmp_path
    assert caught.value.action == "list"
    assert isinstance(caught.value.error, PermissionError)


# --- removing the mark


def test_unblock_dll_removes_the_mark_and_keeps_the_bytes(tmp_path: Path) -> None:
    """Only the stream goes; the DLL's content stays the same."""
    dll = _dll(tmp_path / "a.dll")
    before = _sha(dll)
    assert unblock_dll(dll)
    assert not _marked(dll)
    assert _sha(dll) == before


def test_unblock_dll_without_a_mark_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A DLL without the mark succeeds without removing anything."""
    removed = []
    monkeypatch.setattr(dll_access, "_remove_stream", removed.append)
    assert not unblock_dll(_dll(tmp_path / "a.dll", marked=False))
    assert removed == []


def test_unblock_dll_works_on_a_read_only_dll_without_a_mark(tmp_path: Path) -> None:
    """A read-only bundle without marks can be used."""
    dll = _dll(tmp_path / "a.dll", marked=False)
    dll.chmod(stat.S_IREAD)
    try:
        assert not unblock_dll(dll)
    finally:
        dll.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_unblock_dll_reports_a_mark_that_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An access error on the stream is not taken as no mark."""

    def has_stream(stream: str) -> bool:
        raise PermissionError(13, "Access is denied", stream)

    monkeypatch.setattr(dll_access, "_has_stream", has_stream)
    dll = _dll(tmp_path / "a.dll")
    with pytest.raises(UnblockError) as caught:
        unblock_dll(dll)
    assert (caught.value.path, caught.value.action) == (dll, "read")


def test_unblock_dll_reports_a_mark_that_cannot_be_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A removal error is raised with the DLL."""

    def remove(stream: str) -> None:
        raise PermissionError(13, "Access is denied", stream)

    monkeypatch.setattr(dll_access, "_remove_stream", remove)
    dll = _dll(tmp_path / "a.dll")
    with pytest.raises(UnblockError) as caught:
        unblock_dll(dll)
    assert (caught.value.path, caught.value.action) == (dll, "remove")
    assert _marked(dll)


def test_unblock_bundle_removes_every_mark_and_nothing_outside(tmp_path: Path) -> None:
    """Every DLL of the bundle is unblocked; other files and files outside keep their mark."""
    root = tmp_path / "日本 語's" / "_internal"
    dlls = [
        _dll(root / "a.dll"),
        _dll(root / "B.DLL", marked=False),
        _dll(root / "pythonnet" / "runtime" / "Python.Runtime.dll"),
        _dll(root / "webview" / "lib" / "Microsoft.Web.WebView2.WinForms.dll"),
    ]
    before = [_sha(d) for d in dlls]
    other = root / "x.pyd"
    other.write_bytes(b"x")
    _mark(other)
    outside = _dll(tmp_path / "webview2" / "outside.dll")
    assert unblock_bundle(root) == 3
    assert not any(_marked(d) for d in dlls)
    assert [_sha(d) for d in dlls] == before
    assert _marked(other)
    assert _marked(outside)
    # Again, without marks.
    assert unblock_bundle(root) == 0


def test_unblock_bundle_stops_at_the_first_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The first DLL that cannot be unblocked stops the run; the marks removed stay removed."""
    first = _dll(tmp_path / "a.dll")
    second = _dll(tmp_path / "b.dll")
    remove = dll_access._remove_stream
    calls = []

    def remove_once(stream: str) -> None:
        calls.append(stream)
        if len(calls) > 1:
            raise PermissionError(13, "Access is denied", stream)
        remove(stream)

    monkeypatch.setattr(dll_access, "_remove_stream", remove_once)
    with pytest.raises(UnblockError) as caught:
        unblock_bundle(tmp_path)
    assert len(calls) == 2
    assert caught.value.path in (first, second)
    done = second if caught.value.path == first else first
    assert not _marked(done)
    assert _marked(caught.value.path)


# --- the message


def test_powershell_literal_doubles_single_quotes() -> None:
    """A ``'`` inside the path is doubled."""
    assert powershell_literal(r"C:\a b\o'neil") == r"'C:\a b\o''neil'"


def test_failure_message_names_the_path_the_error_and_both_fixes() -> None:
    """The message gives the cause, the DLL, the OS's error, the zip's fix and the command."""
    root = Path(r"C:\共有 フォルダ\o'neil\ddviz\_internal")
    dll = root / "pythonnet" / "runtime" / "Python.Runtime.dll"
    error = UnblockError(dll, "remove", PermissionError(13, "Access is denied"))
    text = failure_message(root, error)
    assert "インターネットから取得した DLL のブロックを解除できませんでした" in text
    assert str(dll) in text
    assert "Access is denied" in text
    assert "「許可する」" in text
    assert (
        r"Get-ChildItem -LiteralPath 'C:\共有 フォルダ\o''neil\ddviz\_internal' "
        "-Recurse -File -Filter '*.dll' | Unblock-File"
    ) in text


# --- before the window


def test_unblock_or_warn_does_nothing_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In development the run goes on without listing anything."""
    monkeypatch.setattr(dll_access, "bundle_dir", lambda: None)
    monkeypatch.setattr(dll_access, "unblock_bundle", pytest.fail)
    warned = []
    assert unblock_or_warn(warned.append)
    assert warned == []


def test_unblock_or_warn_unblocks_without_a_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bundle that can be unblocked shows nothing."""
    dll = _dll(tmp_path / "a.dll")
    monkeypatch.setattr(dll_access, "bundle_dir", lambda: tmp_path)
    warned = []
    assert unblock_or_warn(warned.append)
    assert warned == []
    assert not _marked(dll)


def test_unblock_or_warn_warns_once_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failure is shown once, and the run must stop."""

    def scan(folder: Path) -> list:
        raise PermissionError(13, "Access is denied", str(folder))

    monkeypatch.setattr(dll_access, "bundle_dir", lambda: tmp_path)
    monkeypatch.setattr(dll_access, "_scan", scan)
    warned = []
    assert not unblock_or_warn(warned.append)
    assert len(warned) == 1
    assert str(tmp_path) in warned[0]
