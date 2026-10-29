"""The results the page draws now: the overview, the zoomed view and the selection layer.

A plot first aggregates its overview (the whole data range). Zooming and
panning aggregate the view again in a worker; the overview's result is kept
so that going back to it needs no worker. Each result's files stay open
(`HoverIndex`) for hovers until a newer result replaces it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ddviz.server.hover import HoverIndex
from ddviz.shared.scatter import ScatterSpec, Selection


@dataclass(frozen=True)
class Layer:
    """The selected rows aggregated over a drawn result.

    Parameters
    ----------
    out : pathlib.Path
        Directory of the selection task's result.
    spec : ScatterSpec
        The task's spec; the table reads the selected rows with it.
    images : list
        Where each series' PNG lies in the images file.
    rows : int
        Number of selected rows.
    """

    out: Path
    spec: ScatterSpec
    images: list
    rows: int


def drop(index: HoverIndex | None) -> None:
    """Close a result's hover files and remove its directory."""
    if index is not None:
        index.close()
        shutil.rmtree(index.out, ignore_errors=True)


class Results:
    """The drawn results and the selection over them."""

    def __init__(self) -> None:
        self.overview: HoverIndex | None = None
        self.view: HoverIndex | None = None
        # Bumped by every new plot, so that a view or a resized overview of
        # an older plot is dropped.
        self.plot_id = 0
        self.selection: Selection | None = None
        self.layer: Layer | None = None

    def opened(self, task: int) -> HoverIndex | None:
        """Return the open result (the overview or the view) of a task, if any."""
        return next(
            (
                i
                for i in (self.view, self.overview)
                if i is not None and i.out.name == str(task)
            ),
            None,
        )

    def set_plot(self, index: HoverIndex) -> None:
        """Make a new plot's result the overview, dropping the old results and the selection."""
        # Open the new result before closing the old ones, whose files are
        # memory-mapped and cannot be removed while open on Windows.
        old = (self.overview, self.view)
        self.overview, self.view = index, None
        for o in old:
            drop(o)
        self.clear_selection()

    def set_view(self, index: HoverIndex) -> None:
        """Make a result the zoomed view, dropping the old one."""
        old, self.view = self.view, index
        drop(old)

    def set_overview(self, index: HoverIndex) -> None:
        """Make a result of the same plot at another size the overview, dropping the old one."""
        old, self.overview = self.overview, index
        drop(old)

    def set_layer(self, layer: Layer, selection: Selection) -> None:
        """Keep a selection and its layer, removing the old layer."""
        old, self.layer = self.layer, layer
        self.selection = selection
        if old is not None:
            shutil.rmtree(old.out, ignore_errors=True)

    def clear_selection(self) -> None:
        """Forget the selection and remove its layer."""
        self.selection = None
        if self.layer is not None:
            shutil.rmtree(self.layer.out, ignore_errors=True)
        self.layer = None

    def close(self) -> None:
        """Close the hover files of the results."""
        for index in (self.overview, self.view):
            if index is not None:
                index.close()
