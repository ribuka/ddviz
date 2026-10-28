r"""Build the ddviz folder for distribution: ``dist\ddviz``.

Run from the repository root with ``uv run --group build packaging/build.py``.
It fetches the WebView2 fixed-version runtime once (into
``packaging\webview2``, not committed), builds the exe with PyInstaller
(onedir), and copies the runtime and ``config`` next to the exe.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist" / "ddviz"

# The fixed-version runtime, from Microsoft's download page
# (https://developer.microsoft.com/microsoft-edge/webview2/, "Fixed Version").
WEBVIEW2_VERSION = "156.0.4314.50"
WEBVIEW2_NAME = f"Microsoft.WebView2.FixedVersionRuntime.{WEBVIEW2_VERSION}.x64"
WEBVIEW2_URL = (
    "https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/"
    f"bd9305d7-a7d7-44fe-b8bf-aefad5d6cdb5/{WEBVIEW2_NAME}.cab"
)


def _check_signature(path: Path) -> None:
    """Fail unless the file carries a valid Authenticode signature of Microsoft."""
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
        '"$($s.Status)|$($s.SignerCertificate.Subject)"'
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status, _, subject = out.partition("|")
    if status != "Valid" or "O=Microsoft Corporation" not in subject:
        raise RuntimeError(f"bad signature on {path}: {out}")


def fetch_webview2() -> Path:
    """Download, verify and expand the WebView2 runtime unless already there.

    Returns
    -------
    pathlib.Path
        The runtime folder.
    """
    base = PACKAGING / "webview2"
    runtime = base / WEBVIEW2_NAME
    if runtime.is_dir():
        return runtime
    base.mkdir(parents=True, exist_ok=True)
    cab = base / f"{WEBVIEW2_NAME}.cab"
    print(f"downloading {WEBVIEW2_URL}", flush=True)
    urllib.request.urlretrieve(WEBVIEW2_URL, cab)
    _check_signature(cab)
    subprocess.run(["expand.exe", str(cab), "-F:*", str(base)], check=True)
    cab.unlink()
    return runtime


def main() -> int:
    r"""Build ``dist\ddviz``.

    Returns
    -------
    int
        Exit code.
    """
    runtime = fetch_webview2()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build"),
            str(PACKAGING / "ddviz.spec"),
        ],
        check=True,
    )
    shutil.copytree(runtime, DIST / "webview2")
    shutil.copytree(ROOT / "config", DIST / "config")
    print(f"built {DIST}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
