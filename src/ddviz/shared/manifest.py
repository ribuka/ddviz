"""The manifest a task writes last into its output directory."""

from __future__ import annotations

import json
import os
from pathlib import Path

MANIFEST = "manifest.json"
# File of a plot task holding the PNG of every panel and series one after
# another; the manifest gives the offset and length of each.
IMAGES = "images.bin"


def write_manifest(out: Path, manifest: dict) -> None:
    """Write a manifest atomically; its presence marks the result complete.

    Parameters
    ----------
    out : pathlib.Path
        The task's output directory.
    manifest : dict
        JSON-ready description of the result.
    """
    tmp = out / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(manifest), encoding="utf-8")
    os.replace(tmp, out / MANIFEST)


def read_manifest(out: Path) -> dict:
    """Read the manifest of a task.

    Parameters
    ----------
    out : pathlib.Path
        The task's output directory.

    Returns
    -------
    dict
        The manifest.
    """
    return json.loads((out / MANIFEST).read_text(encoding="utf-8"))
