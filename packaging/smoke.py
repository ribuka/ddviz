r"""Check that the built exe can run a worker task: ``dist\ddviz\ddviz.exe``.

Run from the repository root with ``uv run packaging/smoke.py`` after
``packaging/build.py``, or ``uv run packaging/smoke.py <exe>`` for an exe
elsewhere (an unzipped release). It checks that the notices of the WebView2
SDK are next to the exe and that no WebView2 Runtime is. It then writes a small Parquet file, starts
``ddviz.exe --worker`` and has it count the non-null values (polars and
pyarrow, inside the exe), then checks the counts. It also has workers write
the index of a column's levels and search it (the filter card's candidates,
`ddviz.compute.levelindex`), and checks what they found. The window is not
opened: a CI runner has no desktop to show it on.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "ddviz" / "ddviz.exe"
TIMEOUT_S = 120
NOTICES = ("LICENSE-WebView2-SDK.txt", "NOTICE.txt")


def run_worker(exe: Path, task: dict) -> list[dict]:
    """Run one task in ``exe --worker`` and return its protocol messages.

    Parameters
    ----------
    exe : pathlib.Path
        The ddviz exe.
    task : dict
        The task with its ``"kind"`` and ``"out"``.

    Returns
    -------
    list of dict
        The messages the worker wrote to stdout, in order.
    """
    proc = subprocess.run(
        [str(exe), "--worker"],
        input=json.dumps(task) + "\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"worker exited {proc.returncode}: {proc.stderr}")
    return [json.loads(line) for line in proc.stdout.splitlines() if line]


def run_task(exe: Path, task: dict, out: Path) -> dict:
    """Run one task in ``exe --worker`` and return its manifest.

    Parameters
    ----------
    exe : pathlib.Path
        The ddviz exe.
    task : dict
        The task with its ``"kind"``.
    out : pathlib.Path
        Directory the task writes into.

    Returns
    -------
    dict
        The manifest the task wrote.
    """
    messages = run_worker(exe, {**task, "out": str(out)})
    kinds = [m["type"] for m in messages]
    if kinds[0] != "ready" or kinds[-1] != "done":
        raise RuntimeError(f"unexpected messages: {messages}")
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def check_levels(exe: Path, tmp: Path) -> None:
    """Fail unless workers write the index of a column's levels and find the levels of a search.

    Parameters
    ----------
    exe : pathlib.Path
        The ddviz exe.
    tmp : pathlib.Path
        An empty directory to write into.
    """
    data = tmp / "levels.parquet"
    values = ["ID10", "ID2", "abc", "ABC-1", "ID2", None, "ID10", "ID10"]
    pq.write_table(pa.table({"g": values}), data)
    index = tmp / "index.parquet"
    task = {"kind": "level_index", "parts": [str(data)], "column": "g", "index": str(index)}
    built = run_task(exe, task, tmp / "index")
    if built["index"] != str(index) or built["n_levels"] != 4 or not index.is_file():
        raise RuntimeError(f"unexpected index: {built}")
    task = {"kind": "level_search", "index": str(index), "query": "id", "order": "count"}
    found = run_task(exe, task, tmp / "search")
    expected = {"levels": [["ID10", 3], ["ID2", 2]], "truncated": False, "n_levels": 4}
    if {k: found[k] for k in expected} != expected:
        raise RuntimeError(f"unexpected search: {found}")


def check_layout(folder: Path) -> None:
    """Fail unless the folder has the notices and no bundled WebView2 Runtime.

    Parameters
    ----------
    folder : pathlib.Path
        The folder of the exe.
    """
    for name in NOTICES:
        path = folder / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty: {path}")
    if (folder / "webview2").exists():
        raise RuntimeError(f"a WebView2 Runtime is bundled: {folder / 'webview2'}")


def main(argv: list[str]) -> int:
    """Run the check.

    Parameters
    ----------
    argv : list of str
        The command line arguments: the exe, or none for ``dist``.

    Returns
    -------
    int
        Exit code.
    """
    exe = Path(argv[0]).resolve() if argv else EXE
    check_layout(exe.parent)
    with tempfile.TemporaryDirectory(prefix="ddviz-smoke-") as tmp:
        data = Path(tmp) / "data.parquet"
        pq.write_table(pa.table({"x": [1.0, None, 3.0], "g": ["a", "b", None]}), data)
        task = {
            "kind": "nonnull",
            "paths": [str(data)],
            "names": ["x", "g"],
            "generated": [],
        }
        manifest = run_task(exe, task, Path(tmp) / "out")
        if manifest["rows"] != 3 or manifest["counts"] != [2, 2]:
            raise RuntimeError(f"unexpected result: {manifest}")
        check_levels(exe, Path(tmp))
    print(f"ok: {exe} ran a nonnull task and the tasks of the levels", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
