"""The manifest a task writes last into its output directory.

Most tasks' manifests are plain dicts that the UI server hands on to the
page; those of a plot and of a selection, which the server reads itself,
have types (`PlotManifest`, `SelectionManifest`).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ddviz.shared.keys import BinGrid
from ddviz.shared.layout import AxisGrid, GridLayout
from ddviz.shared.scatter import Boxes, ScatterSpec, Selection, Smooths, Spread

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


@dataclass(frozen=True)
class HoverColumn:
    """A hover column of a plot task's result.

    Parameters
    ----------
    name : str
        The column.
    file : str
        The ``.npy`` file in the task's directory holding the column's value
        of each bin's representative row.
    labels : list or None
        The text of each code, for a non-numeric column stored as codes.
    """

    name: str
    file: str
    labels: list | None


@dataclass(frozen=True)
class PlotManifest:
    """Manifest of a plot task: what it drew and what the overview found.

    Parameters
    ----------
    spec : ScatterSpec
        The task's spec.
    grid : BinGrid
        Key space of the bins.
    layout : GridLayout
        Panels in the figure.
    axes : AxisGrid
        Facet cell and pair of axis columns of each panel.
    x_ranges, y_ranges : list of list of float
        Data range of each x and each y column the bins cover.
    levels : dict
        Levels of the color, row and col roles as drawn
        (`ddviz.compute.aggregate.Aggregation.levels`).
    all_levels : dict
        Levels of the roles over every row
        (`ddviz.compute.aggregate.Aggregation.all_levels`).
    cuts : dict
        Cuts of each binned role (`ddviz.compute.cuts`).
    color_range : list of float or None
        For a gradient, the finite minimum and maximum of the color column.
    colors : list of str
        Color of each series.
    columns : list of HoverColumn
        The hover columns.
    images : list
        ``[offset, length]`` of each series' PNG in the images file
        (`IMAGES`), or None for a series without bins.
    rows : int
        Number of rows drawn.
    hover_files : bool
        Whether the hover files were written; not when even the axis columns
        passed ``spec.hover_bytes``.
    hover_dropped : list of str
        Hover columns of the spec left out to keep within ``spec.hover_bytes``.
    hover_bytes : int
        Bytes of the hover files written.
    axis_levels : dict
        Levels of each categorical axis column
        (`ddviz.compute.aggregate.Aggregation.axis_levels`).
    spreads : list of Spread
        How the points spread in the bands of the categorical axes
        (`ddviz.compute.aggregate.Aggregation.spreads`).
    boxes : list of Boxes
        Box plots of the pairs of a categorical x and a numeric y
        (`ddviz.compute.aggregate.Aggregation.boxes`).
    smooths : list of Smooths
        Smoothing lines of the pairs of a numeric x and a numeric y
        (`ddviz.compute.aggregate.Aggregation.smooths`).
    """

    spec: ScatterSpec
    grid: BinGrid
    layout: GridLayout
    axes: AxisGrid
    x_ranges: list[list[float]]
    y_ranges: list[list[float]]
    levels: dict[str, list]
    all_levels: dict[str, list]
    cuts: dict[str, dict]
    color_range: list[float] | None
    colors: list[str]
    columns: list[HoverColumn]
    images: list[list[int] | None]
    rows: int
    hover_files: bool = True
    hover_dropped: list[str] = field(default_factory=list)
    hover_bytes: int = 0
    axis_levels: dict[str, list[str]] = field(default_factory=dict)
    spreads: list[Spread] = field(default_factory=list)
    boxes: list[Boxes] = field(default_factory=list)
    smooths: list[Smooths] = field(default_factory=list)

    def write(self, out: Path) -> None:
        """Write the manifest into a task's directory (`write_manifest`)."""
        write_manifest(out, {"kind": "plot", **asdict(self)})

    @classmethod
    def read(cls, out: Path) -> PlotManifest:
        """Read the manifest of a plot task.

        Parameters
        ----------
        out : pathlib.Path
            The task's output directory.

        Returns
        -------
        PlotManifest
            The manifest.
        """
        data = read_manifest(out)
        color_range = data["color_range"]
        return cls(
            spec=ScatterSpec.from_dict(data["spec"]),
            grid=BinGrid(**data["grid"]),
            layout=GridLayout(**data["layout"]),
            axes=AxisGrid(**data["axes"]),
            x_ranges=[list(r) for r in data["x_ranges"]],
            y_ranges=[list(r) for r in data["y_ranges"]],
            levels=data["levels"],
            all_levels=data["all_levels"],
            cuts=data["cuts"],
            color_range=None if color_range is None else list(color_range),
            colors=data["colors"],
            columns=[HoverColumn(**c) for c in data["columns"]],
            images=data["images"],
            rows=data["rows"],
            hover_files=data["hover_files"],
            hover_dropped=data["hover_dropped"],
            hover_bytes=data["hover_bytes"],
            axis_levels=data["axis_levels"],
            spreads=[Spread(**k) for k in data["spreads"]],
            boxes=[Boxes(**b) for b in data["boxes"]],
            smooths=[Smooths(**k) for k in data["smooths"]],
        )


@dataclass(frozen=True)
class SelectionManifest:
    """Manifest of a selection task: the layer of the selected rows over a result.

    Parameters
    ----------
    selection : Selection
        The selected rows.
    grid : BinGrid
        Key space of the bins, the result's.
    images : list
        ``[offset, length]`` of each series' PNG in the images file, or None.
    rows : int
        Number of selected rows; a row in several panels counts once.
    """

    selection: Selection
    grid: BinGrid
    images: list[list[int] | None]
    rows: int

    def write(self, out: Path) -> None:
        """Write the manifest into a task's directory (`write_manifest`)."""
        write_manifest(out, {"kind": "selection", **asdict(self)})

    @classmethod
    def read(cls, out: Path) -> SelectionManifest:
        """Read the manifest of a selection task.

        Parameters
        ----------
        out : pathlib.Path
            The task's output directory.

        Returns
        -------
        SelectionManifest
            The manifest.
        """
        data = read_manifest(out)
        return cls(
            selection=Selection(**data["selection"]),
            grid=BinGrid(**data["grid"]),
            images=data["images"],
            rows=data["rows"],
        )
