// Returns the layout key of a plotly axis id: "x2" -> "xaxis2", "y" -> "yaxis".
export function axisKey(id) {
  return id.replace(/^([xy])/, "$1axis");
}
