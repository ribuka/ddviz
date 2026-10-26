"""Packing of panel, series and pixel bin into one int64 aggregation key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

import numpy as np

T = TypeVar("T")


@dataclass(frozen=True)
class BinGrid:
    """The space of aggregation keys: panels x series x height x width bins.

    A key is ``((panel * n_series + series) * height + by) * width + bx``, so
    the keys of one panel and series are contiguous and a dense array of all
    keys reshapes to ``(n_panels, n_series, height, width)``. ``by`` counts
    from the bottom of the plot area.

    Parameters
    ----------
    n_panels, n_series : int
        Numbers of facet panels and of series.
    width, height : int
        Bins of one panel along x and y.
    """

    n_panels: int
    n_series: int
    width: int
    height: int

    @property
    def size(self) -> int:
        """Number of possible keys."""
        return self.n_panels * self.n_series * self.height * self.width

    def pack(self, panel: T, series: T, by: T, bx: T) -> T:
        """Return the key of bins; works on ints, numpy arrays or polars Int64 expressions.

        Parameters
        ----------
        panel, series, by, bx : int, numpy.ndarray or polars.Expr
            Panel, series and bin indices.

        Returns
        -------
        int, numpy.ndarray or polars.Expr
            The keys.
        """
        return ((panel * self.n_series + series) * self.height + by) * self.width + bx

    def unpack(
        self, keys: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Split keys into their panel, series, by and bx.

        Parameters
        ----------
        keys : numpy.ndarray
            Keys made by `pack`.

        Returns
        -------
        tuple of numpy.ndarray
            Panel, series, by and bx of each key.
        """
        rest, bx = np.divmod(keys, self.width)
        rest, by = np.divmod(rest, self.height)
        panel, series = np.divmod(rest, self.n_series)
        return panel, series, by, bx
