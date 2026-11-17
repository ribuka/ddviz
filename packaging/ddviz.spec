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
# Shown by the bootloader before Python loads, until the window shows
# (ddviz.desktop.splash). The image is a plain #f3f3f3 rectangle, 360 x 100
# px, that build.py writes at this fixed path before running PyInstaller.
# The text is in Tk's default font (Segoe UI on Windows): a family with a
# space would need Tcl braces, as PyInstaller does not quote it. Its origin is
# its lower left corner; its size is in pixels (negative), like the image's,
# so that it stays inside at any display scale.
splash = Splash(
    str(root / "build" / "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(24, 62),
    text_size=-20,
    text_color="#1f1f1f",
    text_default="Starting ddviz…",  # an ellipsis, U+2026
    always_on_top=False,
)
exe = EXE(
    pyz,
    a.scripts,
    splash,
    [],
    exclude_binaries=True,
    name="ddviz",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, splash.binaries, name="ddviz", upx=False)
