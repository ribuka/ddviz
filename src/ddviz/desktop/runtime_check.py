"""Check, without a window, that the exe loads the .NET DLLs that the window needs.

``ddviz.exe --check-desktop-runtime`` (packaging/smoke.py runs it in CI)
unblocks the bundled DLLs as a normal start does (`ddviz.desktop.dll_access`),
then imports pywebview's WinForms and Edge Chromium platforms: pythonnet and
the WebView2 SDK's ``Microsoft.Web.WebView2.Core.dll`` and
``Microsoft.Web.WebView2.WinForms.dll``. It opens no window, server or
worker, writes no run log, and shows no message box: a failure goes to
stderr, so CI does not wait on a dialog.
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from typing import TextIO

from ddviz.desktop.dll_access import UnblockError, bundle_dir, unblock_bundle

#: The pywebview platforms the window imports, in order.
PLATFORMS = ("webview.platforms.winforms", "webview.platforms.edgechromium")
#: The WebView2 SDK's assemblies that must be loaded once they are imported.
ASSEMBLIES = ("Microsoft.Web.WebView2.Core", "Microsoft.Web.WebView2.WinForms")
#: The line printed on success.
OK = {"type": "desktop_runtime_ok"}


def _import(name: str) -> None:
    """Import a module (`importlib.import_module`; tests replace it)."""
    importlib.import_module(name)


def _loaded_assemblies() -> set[str]:
    """Return the names of the .NET assemblies loaded in this process."""
    import System

    return {a.GetName().Name for a in System.AppDomain.CurrentDomain.GetAssemblies()}


def check_desktop_runtime(
    out: TextIO | None = None, err: TextIO | None = None
) -> int:
    """Unblock the bundled DLLs and load the window's .NET platforms.

    Parameters
    ----------
    out : TextIO or None
        Where the success line goes; None for ``sys.stdout``.
    err : TextIO or None
        Where a failure's path and exception go; None for ``sys.stderr``.

    Returns
    -------
    int
        0 when everything loaded, 1 otherwise.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    root = bundle_dir()
    try:
        if root is not None:
            unblock_bundle(root)
        for name in PLATFORMS:
            _import(name)
        missing = [a for a in ASSEMBLIES if a not in _loaded_assemblies()]
        if missing:
            raise RuntimeError(f"not loaded: {', '.join(missing)}")
    except UnblockError as error:
        print(f"cannot unblock {error.path} ({error.action}): {error.error}", file=err)
        return 1
    except Exception:  # noqa: BLE001 - reported; the check fails with it
        print(f"cannot load the window's DLLs in {root}", file=err)
        traceback.print_exc(file=err)
        return 1
    print(json.dumps(OK, separators=(",", ":")), file=out, flush=True)
    return 0
