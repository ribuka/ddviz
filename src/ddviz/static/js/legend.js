// Legend clicks fade series instead of hiding them, as flat-pca's plot_legend.js.
// Each series has one empty scatter trace that carries its legend item; its
// opacity is the series' state, which the image layers (layers.js) and the
// hover follow.
export const INACTIVE_OPACITY = 0.1;

// Returns whether a trace is made inactive from its legend.
export function isInactiveTrace(trace) {
  return trace?.opacity === INACTIVE_OPACITY;
}

// Returns the indices of the traces in the legend group of trace `index`.
function legendGroupIndices(gd, index) {
  const group = gd.data[index].legendgroup;
  if (!group) {
    return [index];
  }
  return gd.data.flatMap((trace, i) => (trace.legendgroup === group ? [i] : []));
}

// Makes each of the traces `indices` active or inactive by `active`. Only the
// opacity changes, which plotly restyles without drawing the figure again.
function setTracesActive(gd, indices, active) {
  return Plotly.restyle(gd, { opacity: active.map((on) => (on ? 1 : INACTIVE_OPACITY)) }, indices);
}

// Returns `data` (new traces of the same series) with the active state of
// each legend group taken from the drawn traces.
export function withLegendState(gd, data) {
  const inactive = new Set(
    (gd.data ?? [])
      .filter((trace) => trace.legendgroup && isInactiveTrace(trace))
      .map((trace) => trace.legendgroup),
  );
  return data.map((trace) => (inactive.has(trace.legendgroup) ? { ...trace, opacity: INACTIVE_OPACITY } : trace));
}

// A click on a legend item toggles its group; a right click makes only that
// group active, or every group again when only it already is. A double click
// does nothing. Call after each `Plotly.newPlot`, which drops plotly's handlers;
// the right click listener on the element is added only once.
export function attachLegendOpacity(gd) {
  gd.on("plotly_legendclick", (event) => {
    if (event.event?.button === 2) {
      return false;
    }
    const indices = legendGroupIndices(gd, event.curveNumber);
    const active = indices.some((index) => isInactiveTrace(gd.data[index]));
    setTracesActive(gd, indices, indices.map(() => active));
    return false;
  });
  gd.on("plotly_legenddoubleclick", () => false);
  if (gd.dataset.legendAttached) return;
  gd.dataset.legendAttached = "1";
  gd.addEventListener("contextmenu", (event) => {
    const toggle = event.target.closest?.(".legendtoggle");
    if (!toggle) {
      return;
    }
    event.preventDefault();
    const index = toggle.parentNode.__data__?.[0]?.trace?.index;
    if (index === undefined) {
      return;
    }
    const group = new Set(legendGroupIndices(gd, index));
    // Only series traces; the empty traces that keep the panels' axes have no group.
    const indices = gd.data.flatMap((trace, i) => (trace.legendgroup ? [i] : []));
    const isolated = indices.every((i) => isInactiveTrace(gd.data[i]) !== group.has(i));
    setTracesActive(gd, indices, indices.map((i) => isolated || group.has(i)));
  });
}

// Returns the set of inactive series.
export function inactiveSeries(gd) {
  const inactive = new Set();
  (gd.data ?? []).forEach((trace) => {
    if (trace.legendgroup && isInactiveTrace(trace)) {
      inactive.add(Number(trace.legendgroup.slice(1)));
    }
  });
  return inactive;
}

// Returns the series from the top drawn layer down: active series before
// inactive ones (which sit behind), later series above earlier ones.
export function seriesOrder(gd, nSeries) {
  const inactive = inactiveSeries(gd);
  const down = [...Array(nSeries).keys()].reverse();
  return [...down.filter((s) => !inactive.has(s)), ...down.filter((s) => inactive.has(s))];
}
