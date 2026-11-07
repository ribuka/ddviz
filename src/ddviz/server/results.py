"""The results the page draws now: the overview, the zoomed view and the selection layer.

A plot first aggregates its overview (the whole data range). Zooming and
panning aggregate the view again in a worker; the overview's result is kept
so that going back to it needs no worker. Each result's files stay open
(`HoverIndex`) for hovers until a newer result replaces it; a result a worker
still reads (`Results.hold`) leaves its directory until the worker is done.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
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
        # Bumped by every new plot's result, so that a view, a resized
        # overview or a selection of an older plot is dropped. A plot that
        # fails leaves it: the views of the drawn plot stay valid.
        self.plot_id = 0
        self.selection: Selection | None = None
        self.layer: Layer | None = None
        # Directories of results that workers read, with how many read each,
        # and the bytes of the hover files of those already replaced, which
        # stay on disk until the last reader is done.
        self._held: dict[Path, int] = {}
        self._replaced: dict[Path, int] = {}

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
        self.plot_id += 1
        # Open the new result before closing the old ones, whose files are
        # memory-mapped and cannot be removed while open on Windows.
        old = (self.overview, self.view)
        self.overview, self.view = index, None
        for o in old:
            self._drop(o)
        self.clear_selection()

    def set_view(self, index: HoverIndex) -> None:
        """Make a result the zoomed view, dropping the old one."""
        old, self.view = self.view, index
        self._drop(old)

    def set_overview(self, index: HoverIndex) -> None:
        """Make a result of the same plot at another size the overview, dropping the old one."""
        old, self.overview = self.overview, index
        self._drop(old)

    def _drop(self, index: HoverIndex | None) -> None:
        """Drop a replaced result (`drop`), keeping its directory while a worker reads it."""
        if index is None or index.out not in self._held:
            drop(index)
            return
        index.close()
        self._replaced[index.out] = index.manifest.hover_bytes

    @property
    def held_bytes(self) -> int:
        """Bytes of the hover files of replaced results still on disk for their readers.

        They count toward the limit of the hover files beside the open results.
        """
        return sum(self._replaced.values())

    @contextmanager
    def hold(self, index: HoverIndex) -> Iterator[None]:
        """Keep a result's directory while a worker reads it, even when a newer result replaces it.

        Parameters
        ----------
        index : HoverIndex
            The result.
        """
        out = index.out
        self._held[out] = self._held.get(out, 0) + 1
        try:
            yield
        finally:
            self._held[out] -= 1
            if not self._held[out]:
                del self._held[out]
                if self._replaced.pop(out, None) is not None:
                    shutil.rmtree(out, ignore_errors=True)

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
