"""Tests of finding the WebView2 runtime: the fixed version next to the exe, or the installed one."""

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


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"HKEY_LOCAL_MACHINE": "156.0.4314.58"}, "156.0.4314.58"),
        ({"HKEY_CURRENT_USER": "155.0.1.2"}, "155.0.1.2"),
        (
            {"HKEY_LOCAL_MACHINE": "0.0.0.0", "HKEY_CURRENT_USER": "155.0.1.2"},
            "155.0.1.2",
        ),
        ({}, None),
        ({"HKEY_LOCAL_MACHINE": ""}, None),
        ({"HKEY_LOCAL_MACHINE": "0.0.0.0", "HKEY_CURRENT_USER": "0.0.0.0"}, None),
    ],
)
def test_installed_runtime_version_reads_the_machine_then_the_user(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, str], expected: str | None
) -> None:
    """The version under HKLM wins, then HKCU; missing, empty and 0.0.0.0 mean none."""
    read: list[tuple[str, str]] = []

    def read_pv(root: str, key: str) -> str | None:
        read.append((root, key))
        return values.get(root)

    monkeypatch.setattr(webview2_access, "_read_pv", read_pv)
    assert webview2_access.installed_runtime_version() == expected
    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    keys = [
        (
            "HKEY_LOCAL_MACHINE",
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
        ),
        ("HKEY_CURRENT_USER", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
    ]
    assert read == keys[: len(read)]


@pytest.mark.skipif(sys.platform != "win32", reason="reads the registry")
def test_installed_runtime_version_reads_a_missing_key_as_none() -> None:
    """A key that does not exist is read as no value, not an error."""
    assert (
        webview2_access._read_pv("HKEY_CURRENT_USER", r"SOFTWARE\ddviz-no-such-key")
        is None
    )


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Collect the message boxes the window would show."""
    shown: list[str] = []
    monkeypatch.setattr(window, "show_warning", shown.append)
    monkeypatch.setattr(window, "windows_build", lambda: 14393)
    monkeypatch.setattr(webview, "settings", {})
    return shown


@pytest.fixture
def exe_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run as the exe in a folder of its own."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ddviz.exe"))
    return tmp_path


def _installed(monkeypatch: pytest.MonkeyPatch, version: str | None) -> None:
    monkeypatch.setattr(window, "installed_runtime_version", lambda: version)


def test_development_uses_the_installed_runtime(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    """Outside the exe nothing is checked: pywebview finds the installed runtime."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    _installed(monkeypatch, None)
    assert window._choose_runtime() == "the WebView2 Runtime that pywebview finds"
    assert warnings == []
    assert "WEBVIEW2_RUNTIME_PATH" not in webview.settings


def test_the_exe_uses_the_fixed_version_next_to_it(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str], exe_dir: Path
) -> None:
    """A webview2 folder next to the exe wins over the installed runtime, once readable."""
    runtime = exe_dir / "webview2"
    runtime.mkdir()
    checked: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        window,
        "ensure_access",
        lambda folder, build: checked.append((folder, build)) or True,
    )
    _installed(monkeypatch, "156.0.4314.58")
    assert window._choose_runtime() == f"the WebView2 Runtime in {runtime}"
    assert checked == [(runtime, 14393)]
    assert warnings == []
    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] == str(runtime)


def test_the_exe_stops_with_the_command_when_the_access_is_denied(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str], exe_dir: Path
) -> None:
    """The message box shows the administrator's command with the runtime folder."""
    runtime = exe_dir / "webview2"
    runtime.mkdir()
    monkeypatch.setattr(window, "ensure_access", lambda folder, build: False)
    _installed(monkeypatch, "156.0.4314.58")
    assert window._choose_runtime() is None
    assert warnings == [denied_message(runtime)]
    assert "WEBVIEW2_RUNTIME_PATH" not in webview.settings


def test_the_exe_uses_the_installed_runtime_without_a_fixed_version(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str], exe_dir: Path
) -> None:
    """Without webview2 next to the exe, pywebview is left to the installed runtime."""
    monkeypatch.setattr(window, "ensure_access", lambda folder, build: pytest.fail())
    _installed(monkeypatch, "156.0.4314.58")
    assert window._choose_runtime() == "the installed WebView2 Runtime 156.0.4314.58"
    assert warnings == []
    assert "WEBVIEW2_RUNTIME_PATH" not in webview.settings


def test_the_exe_tells_how_to_get_a_runtime_when_there_is_none(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str], exe_dir: Path
) -> None:
    """With no runtime at all, the message names both ways and Microsoft's page."""
    _installed(monkeypatch, None)
    assert window._choose_runtime() is None
    expected = (
        "WebView2 のランタイムが見つかりません。\n\n"
        "次のどちらかを行ってから、もう一度起動してください。\n"
        "- Microsoft Edge WebView2 Runtime（Evergreen 版）をインストールする。\n"
        "- WebView2 の固定版ランタイムを Microsoft のページから取り、展開したフォルダを"
        "「webview2」という名前で ddviz.exe と同じフォルダに置く。\n\n"
        "https://developer.microsoft.com/microsoft-edge/webview2/"
    )
    assert warnings == [expected]
    assert "WEBVIEW2_RUNTIME_PATH" not in webview.settings
