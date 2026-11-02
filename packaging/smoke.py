r"""Check that the built exe can run a worker task: ``dist\ddviz\ddviz.exe``.

Run from the repository root with ``uv run packaging/smoke.py`` after
``packaging/build.py``, or ``uv run packaging/smoke.py <exe>`` for an exe
elsewhere (an unzipped release). It writes a small Parquet file, starts
``ddviz.exe --worker`` and has it count the non-null values (polars and
pyarrow, inside the exe), then checks the counts. The window is not opened:
a CI runner has no desktop to show it on.
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
    with tempfile.TemporaryDirectory(prefix="ddviz-smoke-") as tmp:
        data = Path(tmp) / "data.parquet"
        pq.write_table(pa.table({"x": [1.0, None, 3.0], "g": ["a", "b", None]}), data)
        out = Path(tmp) / "out"
        task = {"kind": "nonnull", "paths": [str(data)], "names": ["x", "g"]}
        messages = run_worker(exe, {**task, "out": str(out)})
        kinds = [m["type"] for m in messages]
        if kinds[0] != "ready" or kinds[-1] != "done":
            raise RuntimeError(f"unexpected messages: {messages}")
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if manifest["rows"] != 3 or manifest["counts"] != [2, 2]:
        raise RuntimeError(f"unexpected result: {manifest}")
    print(f"ok: {exe} ran a nonnull task", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
