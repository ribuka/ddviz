"""Tests of the read access of app packages to the bundled WebView2 runtime."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import webview

from ddviz.desktop import webview2_access, window
from ddviz.desktop.webview2_access import (
    SIDS,
    Ace,
    command_line,
    denied_message,
    ensure_access,
    grant_command,
    missing_sids,
    needs_access,
    read_aces,
)

_ALL = "S-1-15-2-1"
_RESTRICTED = "S-1-15-2-2"
_RX = 0x1200A9
_OI_CI = 0x3
_INHERITED = 0x10
_INHERIT_ONLY = 0x8


@pytest.mark.parametrize(
    ("build", "needed"),
    [(14393, True), (19045, True), (20348, True), (22000, False), (26200, False)],
)
def test_only_the_windows_10_line_needs_the_access(build: int, needed: bool) -> None:
    """Server 2016 (14393) up to Windows 10 and Server 2022 need it; Windows 11 does not."""
    assert needs_access(build) is needed


def test_an_explicit_or_inherited_read_entry_is_enough() -> None:
    """``(OI)(CI)(RX)`` for both SIDs, explicit or inherited, leaves nothing missing."""
    aces = [Ace(_RESTRICTED, _RX, _OI_CI), Ace(_ALL, _RX, _OI_CI | _INHERITED)]
    assert missing_sids(aces) == []


def test_generic_rights_in_an_inherit_only_entry_count_for_the_children() -> None:
    """Like Program Files: generic read and execute for the children, file rights for the folder."""
    generic = 0x80000000 | 0x20000000
    aces = [
        Ace(sid, mask, flags)
        for sid in SIDS
        for mask, flags in [(_RX, _INHERITED), (generic, _OI_CI | _INHERIT_ONLY)]
    ]
    assert missing_sids(aces) == []


@pytest.mark.parametrize(
    "ace",
    [
        Ace(_ALL, _RX, 0),  # the folder only, not what is inside
        Ace(_ALL, _RX, _OI_CI | _INHERIT_ONLY),  # what is inside only
        Ace(_ALL, _RX, 0x1),  # files but not subfolders
        Ace(_ALL, 0x120089, _OI_CI),  # read without execute
        Ace("S-1-1-0", _RX, _OI_CI),  # someone else
    ],
)
def test_an_entry_that_does_not_cover_everything_leaves_the_sid_missing(
    ace: Ace,
) -> None:
    """The SID needs read and execute on the folder and on its files and subfolders."""
    assert missing_sids([Ace(_RESTRICTED, _RX, _OI_CI), ace]) == [_ALL]


def test_the_command_for_the_administrator_is_microsofts_with_the_real_path() -> None:
    """One line, quoted so that it runs as is in cmd and in PowerShell."""
    folder = Path(r"C:\Program Files\ddviz\webview2")
    line = command_line(folder)
    assert line == (
        r'icacls "C:\Program Files\ddviz\webview2" /grant '
        '"*S-1-15-2-2:(OI)(CI)(RX)" "*S-1-15-2-1:(OI)(CI)(RX)"'
    )
    assert line in denied_message(folder)
    assert grant_command(folder) == [
        "icacls",
        str(folder),
        "/grant",
        "*S-1-15-2-2:(OI)(CI)(RX)",
        "*S-1-15-2-1:(OI)(CI)(RX)",
    ]


class _Folder:
    """Stands in for the DACL of a folder and for icacls granting on it."""

    def __init__(self, aces: list[Ace], grantable: bool = True) -> None:
        self.aces = aces
        self.grantable = grantable
        self.reads = 0
        self.runs: list[list[str]] = []

    def read(self, folder: Path) -> list[Ace]:
        self.reads += 1
        if self.aces is None:
            raise PermissionError("cannot read the DACL")
        return self.aces

    def run(self, args: list[str], **__: object) -> subprocess.CompletedProcess:
        self.runs.append(args)
        if not self.grantable:
            return subprocess.CompletedProcess(args, 5)
        self.aces = [Ace(sid, _RX, _OI_CI) for sid in SIDS]
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def folder(monkeypatch: pytest.MonkeyPatch) -> _Folder:
    """Return a folder without the access, which the user may change."""
    fake = _Folder([])
    monkeypatch.setattr(webview2_access, "read_aces", fake.read)
    monkeypatch.setattr(webview2_access.subprocess, "run", fake.run)
    return fake


def test_windows_11_neither_reads_nor_grants(folder: _Folder) -> None:
    """Nothing is done where the access is not needed."""
    assert ensure_access(Path("w"), 26200)
    assert folder.reads == 0
    assert folder.runs == []


def test_a_folder_with_the_access_is_not_changed(folder: _Folder) -> None:
    """Only the folder's DACL is read; icacls does not run."""
    folder.aces = [Ace(sid, _RX, _OI_CI) for sid in SIDS]
    assert ensure_access(Path("w"), 14393)
    assert folder.runs == []


def test_a_missing_access_is_granted_and_read_back(folder: _Folder) -> None:
    """A user who owns the folder gets the access granted without being asked."""
    assert ensure_access(Path("w"), 14393)
    assert folder.runs == [grant_command(Path("w"))]
    assert folder.reads == 2


def test_an_access_that_cannot_be_granted_is_reported(folder: _Folder) -> None:
    """When icacls is denied, the folder is still missing the access."""
    folder.grantable = False
    assert not ensure_access(Path("w"), 14393)
    assert len(folder.runs) == 1


def test_an_unreadable_dacl_counts_as_missing(folder: _Folder) -> None:
    """A DACL that cannot be read is granted, then reported if still unreadable."""
    folder.aces = None
    folder.grantable = False
    assert not ensure_access(Path("w"), 14393)
    assert len(folder.runs) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="reads and changes a real DACL")
def test_the_access_is_really_granted_on_a_folder_of_ones_own(tmp_path: Path) -> None:
    """On this Windows, a folder the user owns gets the access, files inside included."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.dll").write_bytes(b"")
    assert missing_sids(read_aces(tmp_path)) == list(SIDS)
    assert ensure_access(tmp_path, 14393)
    assert missing_sids(read_aces(tmp_path)) == []
    assert missing_sids(read_aces(tmp_path / "sub")) == []


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Collect the message boxes the window would show."""
    shown: list[str] = []
    monkeypatch.setattr(window, "show_warning", shown.append)
    monkeypatch.setattr(window, "windows_build", lambda: 14393)
    monkeypatch.setattr(webview, "settings", {})
    return shown


def test_development_uses_the_installed_runtime(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    """Without a bundled runtime nothing is checked."""
    monkeypatch.setattr(window, "bundled_runtime", lambda: None)
    assert window._use_bundled_runtime()
    assert warnings == []
    assert "WEBVIEW2_RUNTIME_PATH" not in webview.settings


def test_the_window_stops_with_the_command_when_the_access_is_denied(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str], tmp_path: Path
) -> None:
    """The message box shows the administrator's command with the bundled folder."""
    monkeypatch.setattr(window, "bundled_runtime", lambda: tmp_path)
    monkeypatch.setattr(window, "ensure_access", lambda folder, build: False)
    assert not window._use_bundled_runtime()
    assert warnings == [denied_message(tmp_path)]
    assert "WEBVIEW2_RUNTIME_PATH" not in webview.settings


def test_the_window_uses_a_runtime_with_the_access(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str], tmp_path: Path
) -> None:
    """A ready runtime is handed to pywebview without a message."""
    checked: list[tuple[Path, int]] = []
    monkeypatch.setattr(window, "bundled_runtime", lambda: tmp_path)
    monkeypatch.setattr(
        window,
        "ensure_access",
        lambda folder, build: checked.append((folder, build)) or True,
    )
    assert window._use_bundled_runtime()
    assert checked == [(tmp_path, 14393)]
    assert warnings == []
    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] == str(tmp_path)
