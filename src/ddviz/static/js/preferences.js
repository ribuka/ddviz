// The Preferences dialog (… → Edit → Preferences…; docs/spec.md,
// "Preferences"): every setting of the TOML files in four groups, with when
// each takes effect, saved into config/settings.local.toml.
//
// A plain script without imports, as titlebar.js: the desktop embeds both in
// its chooser, which the UI server does not serve, and the graph's page loads
// them. It only defines `window.ddvizPreferences`; titlebar.js opens it with
// what reaches the window (`ddviz.desktop.window._Api`):
//
//   open({ state, save, apply }) shows the dialog and resolves once it is
//   closed. `state` is `{ groups, items, values }` of
//   `ddviz.server.preferences.Preferences.state`; `save(changes)` saves the
//   values changed by key and resolves to `{ values }` or `{ error }`;
//   `apply(values, changed)`, on the graph's page only, redraws what takes a
//   value at once and rejects when it could not.
//
// Apply or Enter checks every input, then saves the changed ones and applies
// them; it closes on success. Escape, Cancel and a press outside the dialog
// close it and drop the edits. Nothing is previewed while typing.
(() => {
  const TITLE = "設定";
  const APPLY = "適用";
  const CANCEL = "キャンセル";
  const SAVE_FAILED = "設定を保存できませんでした：";
  // After a save whose redraw failed: the file is saved, the page is not.
  const APPLIED_PARTLY = "設定は保存しました。ただし表示を更新できませんでした：";
  const RETRY = "もう一度「適用」を押すと、表示の更新をやり直します。";
  const INTEGER = /^\d+$/;
  const DECIMAL = /^(\d+(\.\d*)?|\.\d+)$/;

  // A value from 0 to 1 as its percentage, without the float's noise
  // (0.07 is "7", 0.123 is "12.3").
  function percentText(value) {
    return String(Number((value * 100).toPrecision(12)));
  }

  // The text an item's input shows for `value`.
  function textOf(item, value) {
    return item.input === "percent" ? percentText(value) : String(value);
  }

  // Reads the text of an item's input, without the blanks around it:
  // `{ value }` (a percentage divided by 100) or `{ error }`. Nothing is
  // rounded or moved into the range.
  function parse(item, text) {
    const t = text.trim();
    const n = Number(t);
    if (item.input === "choice") {
      if (!INTEGER.test(t) || !item.choices.includes(n)) return { error: `${item.choices.join(" か ")} を選んでください` };
      return { value: n };
    }
    if (item.input === "percent") {
      if (!INTEGER.test(t) || n > 100) return { error: "0 以上 100 以下の整数（%）を入力してください" };
      return { value: n / 100 };
    }
    if (item.input === "integer") {
      if (!INTEGER.test(t) || n < 1 || !Number.isSafeInteger(n)) return { error: "1 以上の整数を入力してください" };
      return { value: n };
    }
    const low = item.minimum;
    const wrong = !DECIMAL.test(t) || !Number.isFinite(n) || (item.above_minimum ? n <= low : n < low);
    if (wrong) {
      return { error: item.above_minimum ? `${low} より大きい数値を入力してください` : `${low} 以上の数値を入力してください` };
    }
    return { value: n };
  }

  function element(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // The inputs of an item; `field.text` is the one read (a select for a
  // choice), `field.slider` the percentage's slider kept beside it.
  function itemRow(item, value, index) {
    const row = element("div", "prefs-item");
    row.dataset.key = item.key;
    const id = `prefs-input-${index}`;
    const label = element("label", "prefs-label", item.label);
    label.htmlFor = id;
    const inputs = element("div", "prefs-inputs");
    let text;
    if (item.input === "choice") {
      text = element("select", "prefs-text prefs-choice");
      for (const choice of item.choices) text.append(new Option(String(choice), String(choice)));
    } else {
      text = element("input", "prefs-text");
      text.type = "text";
      text.inputMode = item.input === "integer" ? "numeric" : "decimal";
      text.autocomplete = "off";
    }
    text.id = id;
    text.value = textOf(item, value);
    let slider = null;
    if (item.input === "percent") {
      slider = element("input", "prefs-slider");
      slider.type = "range";
      slider.min = "0";
      slider.max = "100";
      slider.step = "1";
      slider.value = text.value;
      slider.setAttribute("aria-label", `${item.label}（スライダー）`);
      slider.addEventListener("input", () => {
        text.value = slider.value;
      });
      text.addEventListener("input", () => {
        const read = parse(item, text.value);
        if (!read.error) slider.value = String(read.value * 100);
      });
      inputs.append(slider);
    }
    inputs.append(text);
    if (item.unit) inputs.append(element("span", "prefs-unit", item.unit));
    const timing = element("p", "prefs-timing", item.timing);
    const error = element("p", "prefs-error");
    error.id = `${id}-error`;
    error.setAttribute("role", "alert");
    text.setAttribute("aria-describedby", error.id);
    row.append(label, inputs, timing);
    if (item.note) row.append(element("p", "prefs-note", item.note));
    row.append(error);
    return { item, row, text, slider, error, value, shown: text.value };
  }

  let opened = null;

  function open({ state, save, apply }) {
    if (opened) return opened;
    opened = new Promise((resolve) => {
      const backdrop = element("div", "prefs-backdrop");
      const box = element("div", "prefs-dialog");
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.setAttribute("aria-labelledby", "prefs-title");
      const heading = element("h2", "prefs-title", TITLE);
      heading.id = "prefs-title";
      const body = element("div", "prefs-body");
      const fields = [];
      for (const group of state.groups) {
        const section = element("section", "prefs-group");
        section.append(element("h3", "prefs-group-title", group));
        for (const item of state.items.filter((i) => i.group === group)) {
          const field = itemRow(item, state.values[item.key], fields.length);
          fields.push(field);
          section.append(field.row);
        }
        body.append(section);
      }
      const message = element("p", "prefs-message");
      message.setAttribute("role", "alert");
      const buttons = element("div", "prefs-buttons");
      const applyButton = element("button", "prefs-apply", APPLY);
      applyButton.type = "button";
      const cancelButton = element("button", "prefs-cancel", CANCEL);
      cancelButton.type = "button";
      buttons.append(applyButton, cancelButton);
      box.append(heading, body, message, buttons);
      backdrop.append(box);
      document.body.append(backdrop);

      let saving = false;
      // Keys saved whose redraw failed, applied again by the next Apply.
      let unapplied = [];

      function setSaving(on) {
        saving = on;
        applyButton.disabled = on;
        cancelButton.disabled = on;
        box.setAttribute("aria-busy", String(on));
      }

      // The changed values by key, or null when an input is wrong; the
      // first wrong input takes the focus.
      function changes() {
        const found = {};
        let first = null;
        for (const field of fields) {
          field.error.textContent = "";
          field.row.classList.remove("invalid");
          field.text.removeAttribute("aria-invalid");
          if (field.text.value.trim() === field.shown) continue;
          const read = parse(field.item, field.text.value);
          if (read.error) {
            field.error.textContent = read.error;
            field.row.classList.add("invalid");
            field.text.setAttribute("aria-invalid", "true");
            first ??= field;
          } else if (read.value !== field.value) {
            found[field.item.key] = read.value;
          }
        }
        if (first) {
          first.text.focus();
          return null;
        }
        return found;
      }

      async function commit() {
        if (saving) return;
        message.textContent = "";
        const changed = changes();
        if (changed === null) return;
        const keys = Object.keys(changed);
        if (keys.length === 0 && unapplied.length === 0) {
          close();
          return;
        }
        setSaving(true);
        let values = null;
        // The keys whose value in effect the save changed: those edited, and
        // others that the save read again from the local file.
        let saved = [];
        if (keys.length > 0) {
          let result;
          try {
            result = await save(changed);
          } catch (error) {
            result = { error: `${SAVE_FAILED}${error?.message ?? error}` };
          }
          if (result.error) {
            message.textContent = result.error;
            setSaving(false);
            return;
          }
          values = result.values;
          for (const field of fields) {
            if (values[field.item.key] !== field.value) saved.push(field.item.key);
            field.value = values[field.item.key];
            field.shown = textOf(field.item, field.value);
          }
        } else {
          values = Object.fromEntries(fields.map((f) => [f.item.key, f.value]));
        }
        const toApply = [...new Set([...unapplied, ...keys, ...saved])];
        try {
          await apply?.(values, toApply);
        } catch (error) {
          unapplied = toApply;
          message.textContent = `${APPLIED_PARTLY}${error?.message ?? error}　${RETRY}`;
          setSaving(false);
          applyButton.focus();
          return;
        }
        close();
      }

      function cancel() {
        if (!saving) close();
      }

      function focusable() {
        return Array.from(box.querySelectorAll("input, select, button")).filter((e) => !e.disabled);
      }

      const keys = (event) => {
        if (event.key === "Escape") {
          cancel();
        } else if (event.key === "Enter") {
          // The Enter that commits an IME conversion does nothing; one on a
          // button presses it.
          if (event.isComposing || event.keyCode === 229) return;
          if (event.target instanceof HTMLButtonElement) return;
          commit();
        } else if (event.key === "Tab") {
          const list = focusable();
          if (list.length === 0) return;
          const at = list.indexOf(document.activeElement);
          const step = event.shiftKey ? -1 : 1;
          list[(at + step + list.length) % list.length].focus();
        } else {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
      };
      document.addEventListener("keydown", keys, true);
      applyButton.addEventListener("click", commit);
      cancelButton.addEventListener("click", cancel);
      backdrop.addEventListener("pointerdown", (event) => {
        if (event.target === backdrop) cancel();
      });
      (fields[0]?.slider ?? fields[0]?.text ?? applyButton).focus();

      function close() {
        document.removeEventListener("keydown", keys, true);
        backdrop.remove();
        opened = null;
        resolve();
      }
    });
    return opened;
  }

  window.ddvizPreferences = { open, parse, percentText };
})();
