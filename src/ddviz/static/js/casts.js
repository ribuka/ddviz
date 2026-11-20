// After Load, tells once which columns the files of a folder hold with
// different types, and the type all are read as (`GET /api/source`). The
// join dialog (joindialog.js) shows the same of the table to join.

// The sentence over the list of `casts` of `files` files.
export function castsText(files, casts) {
  return `${files.toLocaleString()} 個のファイルで型が違う ${casts.length.toLocaleString()} 列を、共通の型に揃えて読みます。`;
}

// The rows of the list: the column, its types in the files and the type read.
export function castRows(casts) {
  return casts.map((cast) => {
    const row = document.createElement("tr");
    for (const text of [cast.name, cast.dtypes.join(", "), cast.dtype]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.append(cell);
    }
    return row;
  });
}

// Opens `dialog` with the columns cast of `found`, the answer of
// `GET /api/source`; nothing when none were.
export function showCasts(dialog, found) {
  if (!found.casts.length) return;
  dialog.querySelector(".casts-text").textContent = castsText(found.files, found.casts);
  dialog.querySelector("tbody").replaceChildren(...castRows(found.casts));
  dialog.showModal();
}
