"""The working set (physical memory in use) of a group of processes, on Windows.

The sum is an estimate: pages that processes share count once per process.
On other platforms every function here returns None.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterable

_IS_WINDOWS = sys.platform == "win32"

_HANDLE = ctypes.c_void_p
_DWORD = ctypes.c_uint32
_BOOL = ctypes.c_int

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
# OpenProcess fails with this when no process has the id: it has ended.
_ERROR_INVALID_PARAMETER = 87


class _MemoryCounters(ctypes.Structure):
    """PROCESS_MEMORY_COUNTERS."""

    _fields_ = [
        ("cb", _DWORD),
        ("PageFaultCount", _DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _kernel32() -> ctypes.WinDLL:
    """Return kernel32 with error reporting and the signatures used here."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, restype, argtypes in [
        ("OpenProcess", _HANDLE, [_DWORD, _BOOL, _DWORD]),
        ("WaitForSingleObject", _DWORD, [_HANDLE, _DWORD]),
        ("K32GetProcessMemoryInfo", _BOOL, [_HANDLE, ctypes.c_void_p, _DWORD]),
        ("CloseHandle", _BOOL, [_HANDLE]),
    ]:
        function = getattr(k32, name)
        function.restype = restype
        function.argtypes = argtypes
    return k32


class _Gone(Exception):
    """The process has ended; it no longer counts."""


def _working_set(k32: ctypes.WinDLL, pid: int) -> int:
    """Return the working set of a running process in bytes.

    Parameters
    ----------
    k32 : ctypes.WinDLL
        kernel32 (`_kernel32`).
    pid : int
        Process id.

    Returns
    -------
    int
        The working set.

    Raises
    ------
    _Gone
        The process has ended.
    OSError
        The process could not be measured, and it may still run.
    """
    process = k32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid
    )
    if not process:
        error = ctypes.get_last_error()
        if error == _ERROR_INVALID_PARAMETER:
            raise _Gone
        raise ctypes.WinError(error)
    try:
        state = k32.WaitForSingleObject(process, 0)
        if state == _WAIT_OBJECT_0:
            raise _Gone
        if state != _WAIT_TIMEOUT:
            raise ctypes.WinError(ctypes.get_last_error())
        counters = _MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not k32.K32GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.WorkingSetSize
    finally:
        k32.CloseHandle(process)


def total_working_set(pids: Iterable[int]) -> int | None:
    """Return the summed working set of processes, each id counted once.

    A process that has ended since its id was listed is left out.

    Parameters
    ----------
    pids : iterable of int
        Process ids; a repeated id counts once.

    Returns
    -------
    int or None
        The sum in bytes; None when a process that may still run could not
        be measured, or off Windows.
    """
    if not _IS_WINDOWS:
        return None
    k32 = _kernel32()
    total = 0
    for pid in dict.fromkeys(pids):
        try:
            total += _working_set(k32, pid)
        except _Gone:
            continue
        except OSError:
            return None
    return total
