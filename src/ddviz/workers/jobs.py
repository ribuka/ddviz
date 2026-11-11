"""Windows Job Object that kills worker processes with the UI and caps their memory.

It also lists the processes in it, for the memory shown in the footer.

On other platforms every function here does nothing.
"""

from __future__ import annotations

import ctypes
import sys
import threading

_IS_WINDOWS = sys.platform == "win32"

# Win32 types, spelled with plain ctypes: ctypes.wintypes may not import off
# Windows, where this module must still import.
_HANDLE = ctypes.c_void_p
_DWORD = ctypes.c_uint32
_BOOL = ctypes.c_int

_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_ERROR_MORE_DATA = 234
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_CREATE_SUSPENDED = 0x4
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong) for name in ("r", "w", "o", "rb", "wb", "ob")
    ]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", _DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", _DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", _DWORD),
        ("SchedulingClass", _DWORD),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", _DWORD),
        ("dwMemoryLoad", _DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _kernel32() -> ctypes.WinDLL:
    """Return kernel32 with error reporting and the signatures used here."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, dword, bool_ = _HANDLE, _DWORD, _BOOL
    for name, restype, argtypes in [
        ("CreateJobObjectW", handle, [ctypes.c_void_p, ctypes.c_wchar_p]),
        ("OpenProcess", handle, [dword, bool_, dword]),
        (
            "SetInformationJobObject",
            bool_,
            [handle, ctypes.c_int, ctypes.c_void_p, dword],
        ),
        ("AssignProcessToJobObject", bool_, [handle, handle]),
        (
            "QueryInformationJobObject",
            bool_,
            [handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.c_void_p],
        ),
        ("CloseHandle", bool_, [handle]),
        ("GlobalMemoryStatusEx", bool_, [ctypes.c_void_p]),
    ]:
        function = getattr(k32, name)
        function.restype = restype
        function.argtypes = argtypes
    return k32


def physical_memory() -> int | None:
    """Return the physical memory in bytes, or None off Windows.

    Returns
    -------
    int or None
        Total physical memory.
    """
    if not _IS_WINDOWS:
        return None
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not _kernel32().GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    return status.ullTotalPhys


class WorkerJob:
    """A Job Object holding the worker processes.

    The UI process holds the only handle, so the job closes and kills every
    worker when the UI process ends, however it ends. The job caps the memory
    committed by all workers together.

    A worker starts suspended (`creationflags`) and is resumed by `adopt`
    once it is in the job, so every process it starts is in the job too: in
    development that is the real interpreter behind the venv launcher. A
    worker cannot join by itself: each venv launcher puts its child in a job
    of its own, and a process in one such job may not join a job that already
    holds a process of another (ERROR_ACCESS_DENIED).

    Parameters
    ----------
    memory_limit : int or None
        Cap on the workers' committed memory in bytes; None for no cap.
    """

    def __init__(self, memory_limit: int | None) -> None:
        self._handle = None
        # `close` waits for a listing in another thread to finish with the handle.
        self._lock = threading.Lock()
        #: The cap in force: None off Windows, where there is no job.
        self.memory_limit = memory_limit if _IS_WINDOWS else None
        if not _IS_WINDOWS:
            return
        k32 = _kernel32()
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_limit is not None:
            info.BasicLimitInformation.LimitFlags |= _JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = memory_limit
        ok = k32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            k32.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle

    @property
    def creationflags(self) -> int:
        """Flags to start a worker with: suspended, until `adopt` resumes it."""
        return _CREATE_SUSPENDED if self._handle else 0

    def adopt(self, pid: int) -> None:
        """Put a worker started with `creationflags` into the job and resume it.

        Parameters
        ----------
        pid : int
            Process id of the worker.
        """
        if not self._handle:
            return
        k32 = _kernel32()
        process = k32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA | _PROCESS_SUSPEND_RESUME,
            False,
            pid,
        )
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not k32.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
            ntdll = ctypes.WinDLL("ntdll")
            ntdll.NtResumeProcess.argtypes = [_HANDLE]
            status = ntdll.NtResumeProcess(process)
            if status != 0:
                raise OSError(f"NtResumeProcess failed: 0x{status & 0xFFFFFFFF:08x}")
        finally:
            k32.CloseHandle(process)

    def process_ids(self) -> list[int] | None:
        """Return the ids of the processes in the job, waiting and working alike.

        Returns
        -------
        list of int or None
            The ids; None off Windows, once the job is closed, or when the
            job cannot be queried.
        """
        with self._lock:
            if not self._handle:
                return None
            return _list_processes(_kernel32(), self._handle)

    def close(self) -> None:
        """Close the job, killing every worker in it."""
        with self._lock:
            if self._handle:
                _kernel32().CloseHandle(self._handle)
                self._handle = None


def _list_processes(k32: ctypes.WinDLL, job: int) -> list[int] | None:
    """Return the process ids in a job, growing the buffer until all fit.

    Parameters
    ----------
    k32 : ctypes.WinDLL
        kernel32 (`_kernel32`).
    job : int
        Handle of the job.

    Returns
    -------
    list of int or None
        The ids; None when the job cannot be queried.
    """
    capacity = 16
    while True:

        class _ProcessIdList(ctypes.Structure):
            """JOBOBJECT_BASIC_PROCESS_ID_LIST with room for `capacity` ids."""

            _fields_ = [
                ("NumberOfAssignedProcesses", _DWORD),
                ("NumberOfProcessIdsInList", _DWORD),
                ("ProcessIdList", ctypes.c_size_t * capacity),
            ]

        info = _ProcessIdList()
        ok = k32.QueryInformationJobObject(
            job,
            _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        )
        if not ok and ctypes.get_last_error() != _ERROR_MORE_DATA:
            return None
        listed = info.NumberOfProcessIdsInList
        if ok and listed >= info.NumberOfAssignedProcesses:
            return [int(pid) for pid in info.ProcessIdList[:listed]]
        # More processes than room: the job may also have grown since.
        capacity = max(capacity * 2, info.NumberOfAssignedProcesses + 8)
