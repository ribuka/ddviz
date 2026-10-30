// After Load, tells once which columns the files of a folder hold with
// different types, and the type all are read as (`GET /api/source`).
export async function showCasts(dialog) {
  const response = await fetch("/api/source");
  if (!response.ok) return;
  const found = await response.json();
  if (!found.casts.length) return;
  dialog.querySelector(".casts-text").textContent =
    `${found.files.toLocaleString()} 個のファイルで型が違う ${found.casts.length.toLocaleString()} 列を、共通の型に揃えて読みます。`;
  const rows = found.casts.map((cast) => {
    const row = document.createElement("tr");
    for (const text of [cast.name, cast.dtypes.join(", "), cast.dtype]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.append(cell);
    }
    return row;
  });
  dialog.querySelector("tbody").replaceChildren(...rows);
  dialog.showModal();
}
