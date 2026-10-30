"""Smoothing lines of a scatter plot, fitted to the rows binned along x.

The rows of each line (a facet cell and series of a pair of numeric axis
columns) are binned into `SMOOTH_BINS` bins along x over the overview's
range; each bin is its rows' mean x and mean y, weighted by its rows. The
means are strictly increasing in x, as the splines need, and few: the fits
run in numpy on at most `SMOOTH_BINS` points, whatever the rows.

Three methods (`ddviz.shared.scatter.Smoothing`):

- ``"gcv"``: the cubic smoothing spline whose penalty generalized
  cross-validation picks, as `scipy.interpolate.make_smoothing_spline` with
  ``lam=None``, but with the residuals weighted (scipy leaves them
  unweighted, so that a bin of few rows would weigh as much as one of
  many).
- ``"csaps"``: the cubic smoothing spline of a smoothing parameter ``p``
  from 0 (the least-squares line) to 1 (the interpolating spline), as the
  ``csaps`` package; None picks it from the data, as ``csaps`` does.
- ``"lowess"``: locally weighted linear regression over the nearest
  ``frac`` of the rows (tricube weights), without robustness iterations
  (statsmodels' ``lowess`` with ``it=0``, which takes no weights).

The splines are fitted with x scaled to [0, 1] and the weights to a mean
of 1, so that a ``p`` means the same whatever the units and the rows.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from ddviz.shared.scatter import Smoothing

# Bins along x of each line.
SMOOTH_BINS = 128
# Range of log10 of the penalty searched by generalized cross-validation,
# with x scaled to [0, 1] and weights to a mean of 1.
_GCV_LOG_RANGE = (-12.0, 4.0)
_GCV_GRID = 65

CELL = "__cell"
SERIES = "__series"
BIN = "__xbin"
_N = "__n"
_SX = "__sx"
_SY = "__sy"


def _basis(x: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the Demmler-Reinsch basis of the smoothing splines at weighted knots.

    With ``K`` the matrix of the roughness penalty (``g @ K @ g`` is the
    integral of the squared second derivative of the natural cubic spline
    through the values ``g`` at the strictly increasing knots ``x``) and
    ``W`` the diagonal of the weights, the eigenvectors ``U`` and eigenvalues
    ``d`` of ``W^-1/2 K W^-1/2`` make the spline of any penalty ``lam``:
    ``W^1/2 g = U diag(1 / (1 + lam d)) U.T W^1/2 y``.

    Only `numpy.linalg.eigh` and products: on Windows, OpenBLAS's threads
    made each `numpy.linalg.solve` of a 128-square matrix take about 0.2s,
    against 0.1ms with one thread, while ``eigh`` took 2.6ms.
    """
    h = np.diff(x)
    n = x.size
    q = np.zeros((n, n - 2))
    r = np.zeros((n - 2, n - 2))
    for k in range(n - 2):
        q[k, k] = 1 / h[k]
        q[k + 1, k] = -1 / h[k] - 1 / h[k + 1]
        q[k + 2, k] = 1 / h[k + 1]
        r[k, k] = (h[k] + h[k + 1]) / 3
        if k + 1 < n - 2:
            r[k, k + 1] = r[k + 1, k] = h[k + 1] / 6
    # K = Q R^-1 Q.T, with R^-1 from its eigenvectors (R is positive definite).
    e, v = np.linalg.eigh(r)
    qv = (q / np.sqrt(w)[:, None]) @ v / np.sqrt(e)
    d, u = np.linalg.eigh(qv @ qv.T)
    # The straight lines have no roughness: the two smallest eigenvalues
    # (eigh sorts them) are 0, which rounding would leave a little off.
    d[:2] = 0.0
    return d, u


def _shrink(d: np.ndarray, lam: float) -> np.ndarray:
    """Return the factor ``1 / (1 + lam d)`` of each eigenvector; an infinite penalty keeps only the straight lines."""
    if math.isinf(lam):
        return (d == 0).astype(float)
    return 1 / (1 + lam * d)


def _gcv_lambda(d: np.ndarray, z: np.ndarray) -> float:
    """Return the penalty with the least GCV score: the best of a grid, refined by golden-section search.

    The score is ``n * RSS / (n - tr A)^2`` with the residuals weighted
    (``RSS = sum((lam d / (1 + lam d))^2 z^2)``, ``z = U.T W^1/2 y``), and
    ``tr A = sum(1 / (1 + lam d))``.
    """
    n = d.size

    def score(log_lam: np.ndarray) -> np.ndarray:
        shrink = 1 / (1 + np.multiply.outer(10.0**log_lam, d))
        rss = ((1 - shrink) ** 2 * z**2).sum(axis=-1)
        return n * rss / (n - shrink.sum(axis=-1)) ** 2

    grid = np.linspace(*_GCV_LOG_RANGE, _GCV_GRID)
    best = int(np.argmin(score(grid)))
    lo = grid[max(best - 1, 0)]
    hi = grid[min(best + 1, grid.size - 1)]
    ratio = (math.sqrt(5) - 1) / 2
    for _ in range(40):
        a = hi - ratio * (hi - lo)
        b = lo + ratio * (hi - lo)
        if score(np.array(a)) < score(np.array(b)):
            hi = b
        else:
            lo = a
    return 10 ** ((lo + hi) / 2)


def _csaps_p(w: np.ndarray, x: np.ndarray) -> float:
    """Return the smoothing parameter ``csaps`` picks when none is given: ``1 / (1 + tr R / tr(Q.T W^-1 Q))``."""
    h = np.diff(x)
    trace_r = float(np.sum(h[:-1] + h[1:]) / 3)
    columns = np.stack([1 / h[:-1], -1 / h[:-1] - 1 / h[1:], 1 / h[1:]])
    inv = np.stack([1 / w[:-2], 1 / w[1:-1], 1 / w[2:]])
    trace_qwq = float(np.sum(columns**2 * inv))
    return 1 / (1 + trace_r / trace_qwq)


def _lowess(x: np.ndarray, y: np.ndarray, w: np.ndarray, frac: float) -> np.ndarray:
    """Return the fitted values of weighted lowess (local linear, tricube).

    Each fit reaches the nearest points that hold ``frac`` of the weight
    (rounded down, as statsmodels rounds ``frac`` of the points), the
    farthest of them at weight 0: a point of weight ``n`` stands for ``n``
    rows at its x.
    """
    fitted = np.empty_like(y)
    reach_weight = max(math.floor(frac * w.sum() + 1e-10), 1)
    for i, x0 in enumerate(x):
        distance = np.abs(x - x0)
        order = np.argsort(distance, kind="stable")
        reach = np.searchsorted(np.cumsum(w[order]), reach_weight)
        radius = distance[order[min(reach, x.size - 1)]]
        if radius == 0:
            radius = float(np.min(distance[distance > 0], initial=1.0))
        u = np.clip(distance / radius, 0, 1)
        local = w * (1 - u**3) ** 3
        sw = local.sum()
        mx = local @ x / sw
        my = local @ y / sw
        sxx = local @ (x - mx) ** 2
        slope = 0.0 if sxx <= 0 else float(local @ ((x - mx) * (y - my)) / sxx)
        fitted[i] = my + slope * (x0 - mx)
    return fitted


def fit(
    x: np.ndarray, y: np.ndarray, w: np.ndarray, smoothing: Smoothing
) -> np.ndarray:
    """Return the smoothing line's values at weighted points.

    Parameters
    ----------
    x : numpy.ndarray
        Strictly increasing positions.
    y : numpy.ndarray
        Values at them.
    w : numpy.ndarray
        Positive weight of each point (its rows).
    smoothing : Smoothing
        The method and its parameter.

    Returns
    -------
    numpy.ndarray
        The line's value at each x; with fewer than three points, y
        itself.
    """
    if x.size < 3:
        return y.astype(float)
    if smoothing.method == "lowess":
        return _lowess(x, y, w, smoothing.frac)
    xs = (x - x[0]) / (x[-1] - x[0])
    ws = w / w.mean()
    d, u = _basis(xs, ws)
    root = np.sqrt(ws)
    z = u.T @ (root * y)
    if smoothing.method == "gcv":
        lam = _gcv_lambda(d, z)
    else:
        p = _csaps_p(ws, xs) if smoothing.p is None else smoothing.p
        lam = math.inf if p <= 0 else (1 - p) / p
    return u @ (_shrink(d, lam) * z) / root


def bin_query(
    frame: pl.LazyFrame,
    x: pl.Expr,
    y: pl.Expr,
    cell: pl.Expr,
    series: pl.Expr,
    bounds: tuple[float, float],
) -> pl.LazyFrame:
    """Return the query of each line's bins: the rows, the sum of x and the sum of y of each.

    Parameters
    ----------
    frame : polars.LazyFrame
        The rows drawn by the lines, x and y finite.
    x, y : polars.Expr
        The rows' x and y.
    cell, series : polars.Expr
        Each row's facet cell and series.
    bounds : tuple of float
        Range of x cut into `SMOOTH_BINS` bins.

    Returns
    -------
    polars.LazyFrame
        One row per non-empty bin of each line.
    """
    lo, hi = bounds
    scaled = (x - lo) * (SMOOTH_BINS / (hi - lo))
    xbin = scaled.floor().clip(0, SMOOTH_BINS - 1).cast(pl.Int64)
    return (
        frame.select(
            cell.alias(CELL),
            series.alias(SERIES),
            xbin.alias(BIN),
            x.alias("x"),
            y.alias("y"),
        )
        .group_by(CELL, SERIES, BIN)
        .agg(
            pl.len().alias(_N),
            pl.col("x").sum().alias(_SX),
            pl.col("y").sum().alias(_SY),
        )
    )


def fit_lines(
    bins: pl.DataFrame, smoothing: Smoothing
) -> list[tuple[int, int, list, list]]:
    """Return the smoothing line of each facet cell and series from its bins.

    Parameters
    ----------
    bins : polars.DataFrame
        What `bin_query` collects.
    smoothing : Smoothing
        The method and its parameter.

    Returns
    -------
    list of tuple
        ``(cell, series, xs, ys)`` per line of at least two bins, in the order
        of the cells and the series; xs are the bins' mean x, ys the line's
        values at them.
    """
    lines = []
    ordered = bins.sort(CELL, SERIES, BIN)
    for (cell, series), part in ordered.group_by(CELL, SERIES, maintain_order=True):
        n = part[_N].to_numpy().astype(float)
        if n.size < 2:
            continue
        xs = part[_SX].to_numpy() / n
        ys = part[_SY].to_numpy() / n
        line = fit(xs, ys, n, smoothing)
        lines.append((int(cell), int(series), xs.tolist(), line.tolist()))
    return lines
