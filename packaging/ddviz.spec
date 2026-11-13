# PyInstaller spec of ddviz: a onedir build, run by packaging/build.py.
# The WebView2 runtime and config/ are copied next to the exe by build.py.
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
src = root / "src"

a = Analysis(
    [str(src / "ddviz" / "__main__.py")],
    pathex=[str(src)],
    # The package's metadata: the app menu's Version reads it.
    datas=[(str(src / "ddviz" / "static"), "ddviz/static"), *copy_metadata("ddviz")],
    # The worker imports these inside functions, after the protocol starts.
    hiddenimports=["ddviz.workers.worker", "ddviz.compute.tasks.run"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ddviz",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ddviz", upx=False)
