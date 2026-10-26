// Legend clicks fade series instead of hiding them, as flat-pca's plot_legend.js.
const INACTIVE_OPACITY = 0.1;
const INACTIVE_ZORDER = -1;

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

// Makes each of the traces `indices` active or inactive by `active`.
function setTracesActive(gd, indices, active) {
  return Plotly.restyle(
    gd,
    {
      opacity: active.map((on) => (on ? 1 : INACTIVE_OPACITY)),
      zorder: active.map((on) => (on ? 0 : INACTIVE_ZORDER)),
    },
    indices,
  );
}

// A click on a legend item toggles its group; a right click makes only that
// group active, or every group again when only it already is. A double click
// does nothing.
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
    const isolated = gd.data.every((trace, i) => isInactiveTrace(trace) !== group.has(i));
    const indices = gd.data.map((_, i) => i);
    setTracesActive(gd, indices, indices.map((i) => isolated || group.has(i)));
  });
}

// Returns the series from the top drawn layer down: active series before
// inactive ones (which sit behind), later series above earlier ones.
export function seriesOrder(gd, nSeries) {
  const inactive = new Set();
  gd.data.forEach((trace) => {
    if (trace.type === "scatter" && isInactiveTrace(trace)) {
      inactive.add(Number(trace.legendgroup.slice(1)));
    }
  });
  const down = [...Array(nSeries).keys()].reverse();
  return [...down.filter((s) => !inactive.has(s)), ...down.filter((s) => inactive.has(s))];
}
