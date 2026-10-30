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
from dataclasses import dataclass

import numpy as np
import polars as pl

from ddviz.shared.scatter import Smoothing

# Bins along x of each line.
SMOOTH_BINS = 128
# Range of log10 of the penalty searched by generalized cross-validation,
# with x scaled to [0, 1] and weights to a mean of 1.
_GCV_LOG_RANGE = (-12.0, 4.0)
_GCV_GRID = 81
# Penalties of the fine grid, over a step of the coarse grid on each side.
_GCV_FINE = 41
# Points of a spline closer than this, with x scaled to [0, 1], make one.
_MERGE = 1e-4

CELL = "__cell"
SERIES = "__series"
BIN = "__xbin"
_N = "__n"
_SX = "__sx"
_SY = "__sy"


@dataclass(frozen=True)
class _Bands:
    """The banded matrices of Reinsch's smoothing spline at weighted knots.

    The spline through the values ``g`` at the strictly increasing knots
    has the second derivatives ``gamma`` at the inner knots, with
    ``Q.T g = R gamma``. For a penalty ``lam``, ``gamma`` solves
    ``(R + lam Q.T W^-1 Q) gamma = Q.T y`` and ``g = y - lam W^-1 Q gamma``.
    ``R`` and ``T = Q.T W^-1 Q`` are symmetric with 3 and 5 bands; the
    columns of ``Q`` are ``q0``, ``q1``, ``q2`` on rows ``k``, ``k + 1``,
    ``k + 2``.
    """

    q0: np.ndarray
    q1: np.ndarray
    q2: np.ndarray
    r: tuple[np.ndarray, np.ndarray]
    t: tuple[np.ndarray, np.ndarray, np.ndarray]
    v: np.ndarray
    qty: np.ndarray


def _bands(x: np.ndarray, w: np.ndarray, y: np.ndarray) -> _Bands:
    """Return the banded matrices of the smoothing splines of y at weighted knots x."""
    h = np.diff(x)
    q0, q2 = 1 / h[:-1], 1 / h[1:]
    q1 = -q0 - q2
    v = 1 / w
    t0 = q0**2 * v[:-2] + q1**2 * v[1:-1] + q2**2 * v[2:]
    t1 = q1[:-1] * q0[1:] * v[1:-2] + q2[:-1] * q1[1:] * v[2:-1]
    t2 = q2[:-2] * q0[2:] * v[2:-2]
    # The differences of the slopes keep a straight line's at about 0, as
    # Q.T y summed term by term would not for knots close together.
    slopes = np.diff(y) / h
    return _Bands(
        q0,
        q1,
        q2,
        ((h[:-1] + h[1:]) / 3, h[1:-1] / 6),
        (t0, t1, t2),
        v,
        np.diff(slopes),
    )


def _splines(
    b: _Bands, y: np.ndarray, lams: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return the fitted values of the smoothing spline of each penalty, and the trace of each hat matrix.

    Factors ``M = R + lam T = L D L.T`` (L unit lower, 2 bands) for all the
    penalties at once, one knot after another. The trace of the hat matrix
    ``A`` is ``n - lam tr(M^-1 T)``, from the central 5 bands of ``M^-1``
    (Hutchinson and de Hoog, 1985). No LAPACK: on Windows, OpenBLAS's
    threads made each `numpy.linalg.solve` of a 128-square matrix take
    about 0.2s.
    """
    m = b.qty.size
    lam = lams[:, None]
    a0 = b.r[0] + lam * b.t[0]
    a1 = b.r[1] + lam * b.t[1]
    a2 = lam * b.t[2]
    shape = (lams.size, m)
    d, l1, l2 = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    for k in range(m):
        d[:, k] = a0[:, k]
        if k >= 1:
            d[:, k] -= l1[:, k - 1] ** 2 * d[:, k - 1]
        if k >= 2:
            d[:, k] -= l2[:, k - 2] ** 2 * d[:, k - 2]
        if k + 1 < m:
            l1[:, k] = a1[:, k]
            if k >= 1:
                l1[:, k] -= l1[:, k - 1] * d[:, k - 1] * l2[:, k - 1]
            l1[:, k] /= d[:, k]
        if k + 2 < m:
            l2[:, k] = a2[:, k] / d[:, k]
    z = np.zeros(shape)
    for k in range(m):
        z[:, k] = b.qty[k]
        if k >= 1:
            z[:, k] -= l1[:, k - 1] * z[:, k - 1]
        if k >= 2:
            z[:, k] -= l2[:, k - 2] * z[:, k - 2]
    z /= d
    gamma = np.zeros((lams.size, m + 2))
    # Central bands of M^-1, padded with zeros past the last knot.
    b0, b1, b2 = (
        np.zeros((lams.size, m + 2)),
        np.zeros((lams.size, m + 2)),
        np.zeros((lams.size, m + 2)),
    )
    for k in range(m - 1, -1, -1):
        gamma[:, k] = z[:, k] - l1[:, k] * gamma[:, k + 1] - l2[:, k] * gamma[:, k + 2]
        b1[:, k] = -(l1[:, k] * b0[:, k + 1] + l2[:, k] * b1[:, k + 1])
        b2[:, k] = -(l1[:, k] * b1[:, k + 1] + l2[:, k] * b0[:, k + 2])
        b0[:, k] = 1 / d[:, k] - l1[:, k] * b1[:, k] - l2[:, k] * b2[:, k]
    gamma = gamma[:, :m]
    q_gamma = np.zeros((lams.size, m + 2))
    q_gamma[:, :m] += b.q0 * gamma
    q_gamma[:, 1 : m + 1] += b.q1 * gamma
    q_gamma[:, 2:] += b.q2 * gamma
    fitted = y - lam * b.v * q_gamma
    t0, t1, t2 = b.t
    trace = (
        (b0[:, :m] * t0).sum(axis=1)
        + 2 * (b1[:, : m - 1] * t1).sum(axis=1)
        + 2 * (b2[:, : max(m - 2, 0)] * t2).sum(axis=1)
    )
    return fitted, y.size - lams * trace


def _gcv_lambda(b: _Bands, y: np.ndarray, w: np.ndarray) -> float | None:
    """Return the penalty with the least GCV score, ``n * RSS / (n - tr A)^2`` with the residuals weighted: the best of a coarse grid, then of a fine one around it.

    A penalty whose factorization lost its precision (a score that is not
    finite) is never the best; None when no penalty has a finite score.
    """
    n = y.size

    def best(log_lams: np.ndarray) -> float | None:
        fitted, trace = _splines(b, y, 10.0**log_lams)
        rss = ((y - fitted) ** 2 * w).sum(axis=1)
        scores = n * rss / (n - trace) ** 2
        finite = np.isfinite(scores)
        if not finite.any():
            return None
        return float(log_lams[finite][np.argmin(scores[finite])])

    coarse = np.linspace(*_GCV_LOG_RANGE, _GCV_GRID)
    step = coarse[1] - coarse[0]
    middle = best(coarse)
    if middle is None:
        return None
    return 10 ** best(np.linspace(middle - step, middle + step, _GCV_FINE))


def _line(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Return the weighted least-squares line's values at x."""
    mx, my = w @ x / w.sum(), w @ y / w.sum()
    sxx = w @ (x - mx) ** 2
    slope = 0.0 if sxx <= 0 else float(w @ ((x - mx) * (y - my)) / sxx)
    return my + slope * (x - mx)


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
    # Points closer than `_MERGE` make one, their weighted mean, which the
    # line's value there stands for (under half a pixel of a 4K-wide panel):
    # the factorization of the splines lost its precision (gave NaN) for
    # points 1e-6 of the range apart with weights 1 to 1e8, but not once for
    # points 1e-4 apart.
    group = np.r_[0, np.cumsum(np.diff(xs) >= _MERGE)]
    if group[-1] + 1 == xs.size:
        return _spline(xs, y, w, smoothing)
    sw = np.bincount(group, w)
    merged = np.bincount(group, w * xs) / sw, np.bincount(group, w * y) / sw
    return _spline(*merged, sw, smoothing)[group]


def _spline(
    x: np.ndarray, y: np.ndarray, w: np.ndarray, smoothing: Smoothing
) -> np.ndarray:
    """Return the values of a smoothing spline (``"gcv"`` or ``"csaps"``) at weighted points x in [0, 1]; with fewer than three points, y itself."""
    if x.size < 3:
        return y.astype(float)
    ws = w / w.mean()
    bands = _bands(x, ws, y)
    if smoothing.method == "gcv":
        lam = _gcv_lambda(bands, y, ws)
    else:
        p = _csaps_p(ws, x) if smoothing.p is None else smoothing.p
        lam = None if p <= 0 else (1 - p) / p
    fitted = None if lam is None else _splines(bands, y, np.array([lam]))[0][0]
    # p = 0, or a factorization that lost its precision: the weighted
    # least-squares line, which an infinite penalty tends to.
    if fitted is None or not np.isfinite(fitted).all():
        return _line(x, y, ws)
    return fitted


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
