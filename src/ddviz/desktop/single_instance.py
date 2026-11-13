r"""One window on the machine: a named mutex, and the window of this session brought to the front.

The window run creates the machine-wide mutex ``Global\ddviz`` before it opens
the window and holds it until the process ends (the OS releases it, however
the process ends). Its window records its handle and process id in
``%LOCALAPPDATA%\ddviz\window.json``. A second run that finds the mutex opens
nothing: when that file names a live window of a process in its own Windows
session, it brings the window to the front and ends normally; otherwise
(another user, or another session of the same account) the app is in use.
The file is per user and never removed: a stale one names a window that is
gone or belongs to another process, and is ignored.
"""

from __future__ import annotations

import ctypes
import enum
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ddviz.desktop.runlog import app_data_dir

_log = logging.getLogger(__name__)

MUTEX_NAME = "Global\\ddviz"

IN_USE_MESSAGE = (
    "他のユーザーが使用中です。\n\nしばらくしてから、もう一度起動してください。"
)

#: How long a second run waits for the first to record its window (the first
#: may still be starting).
WAIT_SECONDS = 5.0

_POLL_SECONDS = 0.2

_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5
_SW_RESTORE = 9


class Win32(Protocol):
    """The Win32 calls the check makes; tests replace them."""

    def create_mutex(self, name: str) -> tuple[int | None, int]:
        """Create or open a named mutex; return its handle (None on failure) and the last error."""

    def close_handle(self, handle: int) -> None:
        """Close a handle."""

    def is_window(self, hwnd: int) -> bool:
        """Return whether a window handle names an existing window (``IsWindow``)."""

    def window_pid(self, hwnd: int) -> int:
        """Return the id of the process that created a window (``GetWindowThreadProcessId``)."""

    def session_id(self, pid: int) -> int | None:
        """Return the Windows session of a process (``ProcessIdToSessionId``); None when unknown."""

    def current_pid(self) -> int:
        """Return the id of this process."""

    def bring_to_front(self, hwnd: int) -> None:
        """Restore a minimized window and make it the foreground window."""


class Outcome(enum.Enum):
    """What a run does after the check."""

    #: This run owns the mutex: open the window.
    FIRST = "first"
    #: The window of this session was brought to the front: end normally.
    FRONT = "front"
    #: Another user or session uses the app: tell the user and end.
    IN_USE = "in_use"


@dataclass(frozen=True)
class Claim:
    """The result of `claim`.

    Attributes
    ----------
    outcome : Outcome
        What the run does next.
    handle : int or None
        The mutex, held until the process ends, for `Outcome.FIRST` on
        Windows; None otherwise.
    """

    outcome: Outcome
    handle: int | None = None


def window_record() -> Path:
    r"""Return the file naming the window of the run that owns the mutex, ``%LOCALAPPDATA%\ddviz\window.json``.

    Returns
    -------
    pathlib.Path
        The file, which may not exist.
    """
    return app_data_dir() / "window.json"


def claim(
    api: Win32 | None = None,
    record: Path | None = None,
    wait: float = WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Claim:
    """Take the mutex, or hand over to the run that has it.

    Off Windows, nothing is checked and the run goes on.

    Parameters
    ----------
    api : Win32, optional
        The Win32 calls; the real ones by default.
    record : pathlib.Path, optional
        The file the first run writes its window to; `window_record` by
        default.
    wait : float
        Seconds to keep reading the file while it names no live window of
        the process it names.
    sleep, clock : callable
        Waiting and time, for tests.

    Returns
    -------
    Claim
        What to do next. For `Outcome.FRONT` the window has already been
        brought to the front.
    """
    if api is None:
        if sys.platform != "win32":
            return Claim(Outcome.FIRST)
        api = _RealWin32()
    record = record or window_record()
    handle, error = api.create_mutex(MUTEX_NAME)
    if handle is not None and error != _ERROR_ALREADY_EXISTS:
        return Claim(Outcome.FIRST, handle)
    if handle is not None:
        api.close_handle(handle)
    elif error != _ERROR_ACCESS_DENIED:
        # Neither ours nor someone else's: do not block the app on it.
        _log.error("cannot create the mutex %s (error %d)", MUTEX_NAME, error)
        return Claim(Outcome.FIRST)
    else:
        return Claim(Outcome.IN_USE)
    mine = api.session_id(api.current_pid())
    deadline = clock() + wait
    while True:
        hwnd = _live_window(api, record)
        if hwnd is not None:
            if mine is not None and api.session_id(api.window_pid(hwnd)) == mine:
                api.bring_to_front(hwnd)
                return Claim(Outcome.FRONT)
            return Claim(Outcome.IN_USE)
        if clock() >= deadline:
            return Claim(Outcome.IN_USE)
        sleep(_POLL_SECONDS)


def _live_window(api: Win32, record: Path) -> int | None:
    """Return the window the file names, when it exists and belongs to the process the file names."""
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        hwnd = int(data["hwnd"])
        pid = int(data["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not api.is_window(hwnd) or api.window_pid(hwnd) != pid:
        return None
    return hwnd


def record_window(
    hwnd: int, pid: int | None = None, record: Path | None = None
) -> None:
    """Write the window of this run to the file a second run reads.

    Parameters
    ----------
    hwnd : int
        The handle of the window.
    pid : int, optional
        The id of the process that created the window; this process by
        default.
    record : pathlib.Path, optional
        The file; `window_record` by default.
    """
    record = record or window_record()
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_name(record.name + ".tmp")
    temporary.write_text(
        json.dumps({"hwnd": hwnd, "pid": os.getpid() if pid is None else pid}),
        encoding="utf-8",
    )
    # Replace in one step: a second run never reads half a file.
    os.replace(temporary, record)


class _RealWin32:
    """The Win32 calls, through ctypes."""

    def __init__(self) -> None:
        from ctypes import wintypes

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        k, u = self._kernel32, self._user32
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = ctypes.c_void_p
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.CloseHandle.restype = wintypes.BOOL
        k.ProcessIdToSessionId.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k.ProcessIdToSessionId.restype = wintypes.BOOL
        k.GetCurrentProcessId.argtypes = []
        k.GetCurrentProcessId.restype = wintypes.DWORD
        u.IsWindow.argtypes = [ctypes.c_void_p]
        u.IsWindow.restype = wintypes.BOOL
        u.IsIconic.argtypes = [ctypes.c_void_p]
        u.IsIconic.restype = wintypes.BOOL
        u.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        u.SetForegroundWindow.restype = wintypes.BOOL
        self._dword = wintypes.DWORD

    def create_mutex(self, name: str) -> tuple[int | None, int]:
        """Create or open a named mutex (`Win32.create_mutex`)."""
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, name)
        return handle or None, ctypes.get_last_error()

    def close_handle(self, handle: int) -> None:
        """Close a handle (`Win32.close_handle`)."""
        self._kernel32.CloseHandle(handle)

    def is_window(self, hwnd: int) -> bool:
        """``IsWindow`` (`Win32.is_window`)."""
        return bool(self._user32.IsWindow(hwnd))

    def window_pid(self, hwnd: int) -> int:
        """``GetWindowThreadProcessId`` (`Win32.window_pid`)."""
        pid = self._dword(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def session_id(self, pid: int) -> int | None:
        """``ProcessIdToSessionId`` (`Win32.session_id`)."""
        session = self._dword(0)
        if not self._kernel32.ProcessIdToSessionId(pid, ctypes.byref(session)):
            return None
        return session.value

    def current_pid(self) -> int:
        """``GetCurrentProcessId`` (`Win32.current_pid`)."""
        return self._kernel32.GetCurrentProcessId()

    def bring_to_front(self, hwnd: int) -> None:
        """Restore the window when minimized, then ``SetForegroundWindow`` (`Win32.bring_to_front`)."""
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, _SW_RESTORE)
        if not self._user32.SetForegroundWindow(hwnd):
            _log.warning("cannot bring the window to the front")
