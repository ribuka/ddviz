// How the page asks the server to draw a graph: the settings of a plot
// request that are not the graph's roles, its size, the filter or the axes.

import { DEFAULT_SMOOTHING } from "./smoothmenu.js";

// Returns a copy of an object of level names as one with a prototype, for
// JSON: a level "__proto__" stays a key of its own (a spread defines it).
function plain(object) {
  return { ...object };
}

// How the page asks the server to draw a graph (`ddviz.server.plotoptions`
// and `ddviz.server.models.PlotRequest`), kept while the page is open.
export class PlotOptions {
  // How a numeric color column is cut into intervals ({n, by}), or null for a
  // gradient (`ddviz.server.plotoptions.parse_color_bins`); back to null for
  // another color column.
  colorBins = null;
  // How the smoothing lines are fitted (`ddviz.server.plotoptions.parse_smoothing`),
  // picked in the menu of their element icon; kept for every graph.
  smoothing = DEFAULT_SMOOTHING;
  // Size in pixels of the markers of every series
  // (`ddviz.server.plotoptions.parse_shape_size`), picked in the menu of the
  // points' element icon or of the legend's color markers; kept for every
  // graph. Null for the default: larger for the symbol's shapes than for the
  // circles of the points.
  shapeSize = null;
  // Width in pixels of the lines joining the points of every series
  // (`ddviz.server.plotoptions.parse_line_width`), picked in the menu of the
  // lines' element icon; kept for every graph, with the lines on or off.
  lineWidth = 2;
  // How the lines treat the rows of one X: "raw", "mean" or "median"
  // (`ddviz.server.plotoptions.parse_line_aggregation`), picked in the same
  // menu; kept for every graph, with the lines on or off.
  lineAggregation = "raw";
  // Whether the Color, Symbol, Group Y (row), Group X (col) and Wrap zones
  // draw the rows of a null or NaN value (`ddviz.server.models.ShowNullRows`),
  // set in the zones' menu (zonemenu.js, which changes this object) or in the
  // Wrap zone's form (wrapmenu.js); kept whatever column the zone holds, true
  // after a reload. A failed plot turns it back (`saved`).
  showNullRows = { color: true, symbol: true, row: true, col: true, wrap: true };
  // Whether a categorical column on the Color or the Symbol zone keeps its
  // levels over every row, those the filter leaves without rows staying in
  // the legend (`ddviz.server.models.PlotRequest.keep_unfiltered_color_levels`,
  // `keep_unfiltered_symbol_levels`), set in each zone's menu (zonemenu.js,
  // which changes this object); kept whatever column the zone holds, off
  // after a reload. Off, the levels are those of the filter's rows.
  keepLevels = { color: false, symbol: false };
  // Wrapped panels to a row, or null to make them closest to square
  // (`ddviz.server.plotoptions.parse_wrap_cols`); back to null for another
  // wrap column. The user sets it in the Wrap zone's form (wrapmenu.js).
  wrapCols = null;
  // The number to a row with none set, of the latest result for the wrap
  // column (`wrap_auto_cols` of its meta), or null without one.
  wrapAuto = null;
  // Sizes of the shapes of single symbol levels, by symbol column and level
  // name (`ddviz.server.plotoptions.parse_shape_sizes`), picked in the menu of
  // the symbol legend's markers; kept for every graph, dropped when the size
  // of every series is picked.
  #levelSizes = new Map();
  // Shapes of single symbol levels, by level name, of the symbol column
  // `column` (`ddviz.server.plotoptions.parse_level_shapes`), picked in the
  // panel of the menu of the symbol legend's markers. They stay while the
  // symbol column does, as the colors picked for the color levels: a graph
  // of another symbol column drops them.
  #levelShapes = { column: undefined, shapes: Object.create(null) };

  // Returns the fields of the request body of `POST /api/plot` for the
  // graph `encoding` that these settings set; the caller adds the graph,
  // its size, the filter and the axes.
  request(encoding) {
    // Another symbol column drops the shapes picked once its result is drawn.
    const shapes = encoding.symbol === this.#levelShapes.column ? this.pickedShapes(encoding.symbol) : null;
    return {
      color_bins: this.colorBins,
      wrap_cols: this.wrapCols,
      smooth: this.smoothing,
      shape_size: this.shapeSize,
      line_width: this.lineWidth,
      line_aggregation: this.lineAggregation,
      shape_sizes: this.#levelSizes.get(encoding.symbol) || null,
      level_shapes: shapes,
      show_null_rows: { ...this.showNullRows },
      keep_unfiltered_color_levels: this.keepLevels.color,
      keep_unfiltered_symbol_levels: this.keepLevels.symbol,
    };
  }

  // Returns the shapes picked for the levels of a symbol column, or null for
  // none; the shapes of another column are dropped.
  pickedShapes(column) {
    if (column !== this.#levelShapes.column) {
      this.#levelShapes.column = column;
      this.#levelShapes.shapes = Object.create(null);
    }
    return Object.keys(this.#levelShapes.shapes).length ? this.#levelShapes.shapes : null;
  }

  // Sets the size of the markers of every series, dropping the sizes of
  // single symbol levels.
  setShapeSize(size) {
    this.shapeSize = size;
    this.#levelSizes.clear();
  }

  // Sets the size of the shapes of a symbol level.
  setLevelSize(column, level, size) {
    // Level names come from the data: no prototype, so that "__proto__" is a
    // name like the others.
    const sizes = this.#levelSizes.get(column) ?? Object.create(null);
    sizes[level] = size;
    this.#levelSizes.set(column, sizes);
  }

  // Sets the shape of a symbol level, or the shape of its place again (null).
  setLevelShape(column, level, shape) {
    this.pickedShapes(column);
    if (shape === null) delete this.#levelShapes.shapes[level];
    else this.#levelShapes.shapes[level] = shape;
  }

  // Returns the size of every series' markers drawn in the result `meta`
  // (or null), checked in the menus of the size of every series; null while
  // symbol levels have sizes of their own, of any symbol column, so that
  // picking any size, that one too, drops them.
  sharedSize(meta) {
    return meta && this.#levelSizes.size === 0 ? meta.marker_size : null;
  }

  // Returns the settings derived from the graph, which a failed plot rolls
  // back with it (`Builder`'s save).
  saved() {
    return {
      colorBins: this.colorBins,
      wrapCols: this.wrapCols,
      keepLevels: { ...this.keepLevels },
      showNullRows: { ...this.showNullRows },
    };
  }

  // Returns every setting as JSON values, for the drawing settings of undo
  // and redo (`history.js`): the shapes picked only while `symbol` (the
  // Symbol zone's column, stashed or not) is their column, as a request
  // takes them; the number to a row with none set is the result's.
  settings(symbol) {
    const shapes = this.#levelShapes;
    const picked = symbol !== null && shapes.column === symbol && Object.keys(shapes.shapes).length;
    return {
      colorBins: structuredClone(this.colorBins),
      smoothing: structuredClone(this.smoothing),
      shapeSize: this.shapeSize,
      lineWidth: this.lineWidth,
      lineAggregation: this.lineAggregation,
      showNullRows: { ...this.showNullRows },
      keepLevels: { ...this.keepLevels },
      wrapCols: this.wrapCols,
      levelSizes: [...this.#levelSizes].map(([column, sizes]) => [column, plain(sizes)]),
      levelShapes: picked ? { column: symbol, shapes: plain(shapes.shapes) } : null,
    };
  }

  // Sets every setting from `state` (`settings`).
  applySettings(state) {
    this.colorBins = structuredClone(state.colorBins);
    this.smoothing = structuredClone(state.smoothing);
    this.shapeSize = state.shapeSize;
    this.lineWidth = state.lineWidth;
    this.lineAggregation = state.lineAggregation;
    // In place: the zones' menu holds the object (zonemenu.js).
    Object.assign(this.showNullRows, state.showNullRows);
    Object.assign(this.keepLevels, state.keepLevels);
    this.wrapCols = state.wrapCols;
    this.#levelSizes = new Map(state.levelSizes.map(([column, sizes]) => [column, Object.assign(Object.create(null), sizes)]));
    const shapes = state.levelShapes;
    this.#levelShapes = shapes
      ? { column: shapes.column, shapes: Object.assign(Object.create(null), shapes.shapes) }
      : { column: undefined, shapes: Object.create(null) };
  }

  // Sets back the settings `saved` returned, from `state` (`Builder`'s load).
  load(state) {
    ({ colorBins: this.colorBins, wrapCols: this.wrapCols } = state);
    // In place: the zones' menu holds the objects (zonemenu.js).
    Object.assign(this.showNullRows, state.showNullRows);
    Object.assign(this.keepLevels, state.keepLevels);
  }
}
