r"""Check that a copy of the exe with marked DLLs unblocks them and loads the window's DLLs.

packaging/smoke.py runs this. It copies the distribution folder into a new
folder under ``tmp\exe-smoke\`` of the repository (the original is not
changed), gives every DLL of the copy's ``_internal`` the Mark of the Web,
and runs the copy's ``ddviz.exe --check-desktop-runtime``
(`ddviz.desktop.runtime_check`). The check must print its success line; the
marks must then be gone and the DLLs' SHA-256 unchanged; and a second run,
without marks, must pass too. It covers the unblocking of the bundled DLLs
and the loading of .NET and the WebView2 SDK in the real exe, not a browser
download, Explorer passing the mark on, or a WebView2 window on screen.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import zone_mark

TIMEOUT_S = 120
#: The success line of ``--check-desktop-runtime``.
OK = {"type": "desktop_runtime_ok"}
#: DLLs that the check must find marked in the copy: pythonnet's and the WebView2 SDK's.
REQUIRED = (
    "Python.Runtime.dll",
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
)

Run = Callable[..., subprocess.CompletedProcess]


def run_check(exe: Path, run: Run = subprocess.run, timeout: float = TIMEOUT_S) -> None:
    """Run ``exe --check-desktop-runtime`` and fail unless it prints its success line.

    Parameters
    ----------
    exe : pathlib.Path
        The ddviz exe.
    run : callable
        `subprocess.run`; tests replace it.
    timeout : float
        Seconds the check may take; the exe is killed after that.

    Raises
    ------
    RuntimeError
        On a timeout, a non-zero exit, or no success line.
    """
    try:
        proc = run(
            [str(exe), "--check-desktop-runtime"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:  # run has killed the exe
        raise RuntimeError(f"{exe} --check-desktop-runtime took over {timeout}s") from error
    if proc.returncode != 0:
        raise RuntimeError(
            f"{exe} --check-desktop-runtime exited {proc.returncode}: {proc.stderr}"
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    try:
        ok = [json.loads(line) for line in lines] == [OK]
    except json.JSONDecodeError:
        ok = False
    if not ok:
        raise RuntimeError(
            f"{exe} --check-desktop-runtime printed {proc.stdout!r}, not {OK}: {proc.stderr}"
        )


def _remove(folder: Path) -> None:
    """Remove a folder, retrying while a killed exe still holds its files."""
    for attempt in range(10):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(1)


def mark_dlls(bundle: Path) -> dict[Path, str]:
    """Mark every DLL of a bundle and return their SHA-256 before the marks.

    Parameters
    ----------
    bundle : pathlib.Path
        The copy's ``_internal``.

    Returns
    -------
    dict
        The SHA-256 of each DLL.

    Raises
    ------
    RuntimeError
        When a DLL of `REQUIRED` is missing or a mark cannot be written.
    """
    dlls = zone_mark.dlls(bundle)
    names = {d.name for d in dlls}
    missing = [n for n in REQUIRED if n not in names]
    if missing:
        raise RuntimeError(f"not in {bundle}: {', '.join(missing)}")
    hashes = {d: zone_mark.sha256(d) for d in dlls}
    for dll in dlls:
        zone_mark.mark(dll)
    return hashes


def check_unblocked(hashes: dict[Path, str]) -> None:
    """Fail unless the DLLs have no mark and the same content as before.

    Parameters
    ----------
    hashes : dict
        The SHA-256 of each DLL before it was marked.

    Raises
    ------
    RuntimeError
        Naming the DLLs still marked or changed.
    """
    marked = [d for d in hashes if zone_mark.is_marked(d)]
    if marked:
        raise RuntimeError(f"still marked: {', '.join(map(str, marked))}")
    changed = [d for d, h in hashes.items() if zone_mark.sha256(d) != h]
    if changed:
        raise RuntimeError(f"changed: {', '.join(map(str, changed))}")


def check_marked_copy(folder: Path, work: Path, run: Run = subprocess.run) -> int:
    r"""Copy the distribution folder, mark its DLLs, and check that its exe unblocks and loads them.

    Parameters
    ----------
    folder : pathlib.Path
        The distribution folder (``dist\ddviz``), which is not changed.
    work : pathlib.Path
        Where the folder of this run is made (``tmp\exe-smoke``); only that
        folder is removed afterwards.
    run : callable
        `subprocess.run`; tests replace it.

    Returns
    -------
    int
        How many DLLs were marked and unblocked.

    Raises
    ------
    RuntimeError
        When marking, the checks or the unblocking fail.
    """
    work.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="run-", dir=work))
    try:
        copy = temp / folder.name
        shutil.copytree(folder, copy, symlinks=True)
        hashes = mark_dlls(copy / "_internal")
        exe = copy / "ddviz.exe"
        run_check(exe, run)
        check_unblocked(hashes)
        run_check(exe, run)
        return len(hashes)
    finally:
        _remove(temp)
