r"""Read access of app packages to the bundled WebView2 fixed-version runtime.

On Windows 10 and its servers (Server 2016 among them), the fixed-version
runtime 120 and later runs its renderers in an AppContainer, so the runtime
folder must be readable by ALL APPLICATION PACKAGES (``S-1-15-2-1``) and ALL
RESTRICTED APPLICATION PACKAGES (``S-1-15-2-2``); Windows 11 does not need it.
Before the window opens, the app reads the folder's ACL only (fast), grants
the access with ``icacls`` when it is missing (works when the user owns the
folder), and otherwise tells the administrator the command to run.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Windows 11 starts at this build; earlier ones are of the Windows 10 line.
_WINDOWS_11_BUILD = 22000

SIDS = ("S-1-15-2-2", "S-1-15-2-1")

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x4
_ACL_SIZE_INFORMATION = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_OBJECT_INHERIT_ACE = 0x1
_CONTAINER_INHERIT_ACE = 0x2
_INHERIT_ONLY_ACE = 0x8
# FILE_GENERIC_READ | FILE_GENERIC_EXECUTE, the (RX) of icacls.
_READ_EXECUTE = 0x1200A9
_GENERIC_ALL = 0x10000000
_GENERIC_EXECUTE = 0x20000000
_GENERIC_READ = 0x80000000
_FILE_GENERIC_READ = 0x120089
_FILE_GENERIC_EXECUTE = 0x1200A0


@dataclass(frozen=True)
class Ace:
    """An access-allowed entry of a DACL, as far as the check needs it.

    Attributes
    ----------
    sid : str
        The trustee, e.g. ``"S-1-15-2-1"``.
    mask : int
        The access mask; generic rights are not mapped yet.
    flags : int
        The ACE flags (inheritance).
    """

    sid: str
    mask: int
    flags: int


def needs_access(build: int) -> bool:
    """Tell whether the Windows build is of the Windows 10 line, which needs the access.

    Parameters
    ----------
    build : int
        The build number of Windows (``sys.getwindowsversion().build``).

    Returns
    -------
    bool
        True below Windows 11 (Server 2016 is 14393).
    """
    return build < _WINDOWS_11_BUILD


def _file_rights(mask: int) -> int:
    """Map the generic rights of an access mask to the file rights they stand for."""
    if mask & _GENERIC_ALL:
        mask |= _READ_EXECUTE
    if mask & _GENERIC_READ:
        mask |= _FILE_GENERIC_READ
    if mask & _GENERIC_EXECUTE:
        mask |= _FILE_GENERIC_EXECUTE
    return mask


def granted(aces: list[Ace], sid: str) -> bool:
    """Tell whether the entries give the SID read access to the folder and all inside it.

    The folder itself needs an entry that applies to it, and its files and
    subfolders need one that both kinds inherit; one ``(OI)(CI)(RX)`` entry,
    explicit or inherited, does both.

    Parameters
    ----------
    aces : list of Ace
        The access-allowed entries of the folder's DACL.
    sid : str
        The trustee.

    Returns
    -------
    bool
        Whether the SID can read and execute everything in the folder.
    """
    on_folder = on_children = False
    for ace in aces:
        if ace.sid != sid or _file_rights(ace.mask) & _READ_EXECUTE != _READ_EXECUTE:
            continue
        if not ace.flags & _INHERIT_ONLY_ACE:
            on_folder = True
        both = _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE
        if ace.flags & both == both:
            on_children = True
    return on_folder and on_children


def missing_sids(aces: list[Ace]) -> list[str]:
    """Return the SIDs that lack read access, in the order of `SIDS`.

    Parameters
    ----------
    aces : list of Ace
        The access-allowed entries of the folder's DACL.

    Returns
    -------
    list of str
        Empty when the folder is ready.
    """
    return [sid for sid in SIDS if not granted(aces, sid)]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", ctypes.c_uint32),
        ("AclBytesInUse", ctypes.c_uint32),
        ("AclBytesFree", ctypes.c_uint32),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_uint16),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("Header", _AceHeader),
        ("Mask", ctypes.c_uint32),
        ("SidStart", ctypes.c_uint32),
    ]


def read_aces(folder: Path) -> list[Ace]:
    """Read the access-allowed entries of a folder's DACL; files inside are not read.

    Parameters
    ----------
    folder : pathlib.Path
        The folder.

    Returns
    -------
    list of Ace
        The entries, explicit and inherited.

    Raises
    ------
    OSError
        When the DACL cannot be read.
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]

    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    error = advapi32.GetNamedSecurityInfoW(
        str(folder),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if error:
        raise ctypes.WinError(error)
    try:
        if not dacl.value:  # a null DACL lets everyone in
            inherit = _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE
            return [Ace(sid, _GENERIC_ALL, inherit) for sid in SIDS]
        size = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl, ctypes.byref(size), ctypes.sizeof(size), _ACL_SIZE_INFORMATION
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        aces = []
        for index in range(size.AceCount):
            pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(pointer)):
                raise ctypes.WinError(ctypes.get_last_error())
            ace = ctypes.cast(pointer, ctypes.POINTER(_AccessAllowedAce)).contents
            if ace.Header.AceType != _ACCESS_ALLOWED_ACE_TYPE:
                continue
            text = ctypes.c_void_p()
            sid = pointer.value + _AccessAllowedAce.SidStart.offset
            if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                sid_text = ctypes.wstring_at(text.value)
                aces.append(Ace(sid_text, ace.Mask, ace.Header.AceFlags))
            finally:
                kernel32.LocalFree(text)
        return aces
    finally:
        kernel32.LocalFree(descriptor)


def grant_command(folder: Path) -> list[str]:
    """Return the ``icacls`` command that grants the access, as Microsoft documents it.

    Parameters
    ----------
    folder : pathlib.Path
        The runtime folder.

    Returns
    -------
    list of str
        The arguments.
    """
    return ["icacls", str(folder), "/grant", *(f"*{sid}:(OI)(CI)(RX)" for sid in SIDS)]


def command_line(folder: Path) -> str:
    """Return the command for an administrator, quoted for both cmd and PowerShell.

    Parameters
    ----------
    folder : pathlib.Path
        The runtime folder.

    Returns
    -------
    str
        One line to paste.
    """
    grants = " ".join(f'"*{sid}:(OI)(CI)(RX)"' for sid in SIDS)
    return f'icacls "{folder}" /grant {grants}'


def denied_message(folder: Path) -> str:
    """Return the message shown when the access is missing and cannot be granted.

    Parameters
    ----------
    folder : pathlib.Path
        The runtime folder.

    Returns
    -------
    str
        The text of the message box.
    """
    return (
        "WebView2 のランタイムのフォルダに、画面の表示に要る読み取りの権限がありません。\n"
        "このフォルダのアクセス許可を変える権限が無いため、ddviz からは付けられませんでした。\n\n"
        "管理者が、管理者として開いたコマンド プロンプトか PowerShell で、次を 1 回実行してください。\n\n"
        f"{command_line(folder)}\n\n"
        "（Ctrl+C でこのメッセージをコピーできます）"
    )


def ensure_access(folder: Path, build: int) -> bool:
    """Make sure app packages can read the runtime folder; grant the access if missing.

    Parameters
    ----------
    folder : pathlib.Path
        The bundled fixed-version runtime.
    build : int
        The build number of Windows.

    Returns
    -------
    bool
        True when the folder is ready (or the OS does not need the access);
        False when the access is missing and could not be granted.
    """
    if not needs_access(build) or not _missing(folder):
        return True
    subprocess.run(
        grant_command(folder),
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    return not _missing(folder)


def _missing(folder: Path) -> list[str]:
    """Return the SIDs that lack access; all of them when the DACL cannot be read."""
    try:
        return missing_sids(read_aces(folder))
    except OSError:
        return list(SIDS)


def windows_build() -> int:
    """Return the build number of the running Windows.

    Returns
    -------
    int
        E.g. 14393 on Server 2016.
    """
    return sys.getwindowsversion().build
