# PyInstaller spec of ddviz: a onedir build, run by packaging/build.py.
# The WebView2 runtime and config/ are copied next to the exe by build.py.
from pathlib import Path

root = Path(SPECPATH).parent
src = root / "src"

a = Analysis(
    [str(src / "ddviz" / "__main__.py")],
    pathex=[str(src)],
    datas=[(str(src / "ddviz" / "static"), "ddviz/static")],
    # The worker imports these inside functions, after the protocol starts.
    hiddenimports=["ddviz.workers.worker", "ddviz.compute.task"],
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
