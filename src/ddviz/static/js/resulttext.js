// Texts of a drawn result (its meta): the rows of the status line and the
// size of the markers.

// Returns the status of a result: its rows, and whether the filter left rows out.
export function rowsText(meta, where = "") {
  const filtered = meta.filters.length ? "（フィルタ後）" : "";
  // Box plots without points draw only their outliers as points; smoothing
  // lines without points draw none.
  let drawn = "";
  if (meta.panels.every((p) => !p.points)) {
    drawn = meta.panels.some((p) => p.boxes.length) ? "（外れ値）" : "（点は描いていない）";
  }
  return `${where}${meta.rows.toLocaleString()} 行${drawn}${filtered}`;
}

// Returns the text of the size of a result's markers (its meta), for the
// points' icon: a range when symbol levels have sizes of their own.
export function markerSizeText(meta) {
  const sizes = meta.symbol?.sizes.length ? meta.symbol.sizes : [meta.marker_size];
  const lo = Math.min(...sizes);
  const hi = Math.max(...sizes);
  return lo === hi ? `${lo} px` : `${lo}〜${hi} px`;
}
