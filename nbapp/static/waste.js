/* Waste bottle forms and log. */
"use strict";
(function () {
const h = NB.h;
const route = "/followups/waste";
const label = (text, control) => h("label", {}, h("span", {}, text), control);
const bottleState = (bottle, status) => bottle.state === "picked-up" ? "picked up" : status.nearly_full ? "nearly full" : bottle.state;
NB.wasteVolume = (bottle, status) => status.total_mL + (bottle.capacity_mL ? " / " + bottle.capacity_mL : "") + " mL logged";

function openDialog(title, fields, button, save) {
  const message = h("p", { class: "small", role: "alert", hidden: true });
  const submit = h("button", { type: "submit", class: "primary" }, button);
  const cancel = h("button", { type: "button", onclick: () => dialog.close() }, "Cancel");
  const dialog = h("dialog", { class: "waste-dialog noprint", "aria-labelledby": "waste-dialog-title" },
    h("h2", { id: "waste-dialog-title" }, title),
    h("form", { onsubmit: async e => {
      e.preventDefault();
      submit.disabled = cancel.disabled = true;
      message.hidden = true;
      try { await save(); dialog.close(); }
      catch (error) { message.textContent = error.message; message.hidden = false; }
      finally { submit.disabled = cancel.disabled = false; }
    } }, fields, message, h("div", { class: "row" }, submit, cancel)));
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.addEventListener("cancel", e => { if (submit.disabled) e.preventDefault(); });
  document.getElementById("view").append(dialog);
  dialog.showModal();
}

function addBottle(fu, save) {
  const name = h("input", { required: true, autofocus: true });
  const stream = h("input", { list: "waste-streams", required: true });
  const location = h("input", {});
  const opened = h("input", { type: "date", required: true, value: NB.localDate() });
  const capacity = h("input", { type: "number", min: 0, step: "any" });
  openDialog("Add a waste bottle", [label("Bottle label", name), label("Stream", stream),
    h("datalist", { id: "waste-streams" }, fu.waste_streams.map(s => h("option", { value: s }, s))),
    label("Location", location), label("Date opened", opened), label("Capacity (mL, optional)", capacity)], "Add bottle", () => {
    const used = new Set(fu.waste.map(b => String(b.id)));
    let id = 1;
    while (used.has(String(id))) id++;
    return save([...fu.waste, { id, label: name.value.trim(), stream: stream.value.trim(), location: location.value.trim(),
      opened: opened.value, capacity_mL: capacity.value === "" ? null : capacity.valueAsNumber, state: "open", entries: [] }]);
  });
}

function addEntry(fu, choices, record, save) {
  const select = h("select", { required: true, autofocus: true },
    choices.length > 1 ? h("option", { value: "" }, "Choose a bottle") : null,
    choices.map(b => h("option", { value: b.id }, [b.label, b.location].filter(Boolean).join(" · "))));
  const date = h("input", { type: "date", required: true, value: NB.localDate() });
  const exp = h("input", { value: record ? record.id : "" });
  const names = (record && record.materials || []).filter(m => m && m.name && !/^P/i.test(m.id || "")).map(m => m.name);
  const contents = h("textarea", { rows: 2, required: true });
  contents.value = Array.from(new Set(names)).join(", ");
  const volume = h("input", { type: "number", min: 0, step: "any", required: true });
  const by = h("input", { value: NB.state.user, required: true });
  openDialog("Log waste", [label("Bottle", select), label("Date", date), label("Experiment", exp), label("Contents", contents),
    label("Volume (mL)", volume), label("Logged by", by)], "Save entry", () => {
    const entry = { date: date.value, exp: exp.value.trim(), contents: contents.value.trim(), volume_mL: volume.valueAsNumber, by: by.value.trim() };
    return save(fu.waste.map(b => String(b.id) === select.value ? { ...b, entries: [...(b.entries || []), entry] } : b));
  });
}

NB.wasteEntryControl = function (record) {
  return h("button", { class: "noprint", onclick: async e => {
    const button = e.currentTarget;
    button.disabled = true;
    try {
      const fu = await NB.capi("GET", route);
      if (!button.isConnected) return;
      const choices = fu.waste.filter(b => b.state === "open");
      if (choices.length) addEntry(fu, choices, record, async waste => {
        await NB.capi("PUT", route, { waste, hash: fu.hash });
        NB.toast("Waste entry saved.");
      });
      else NB.toast("Add an open waste bottle first.", false, { label: "Schedule and supplies", run: () => { location.hash = "#/followups"; } });
    } catch (error) { NB.fail(error); }
    finally { button.disabled = false; }
  } }, "Log waste");
};

NB.wasteSection = function (fu, save) {
  const columns = ["Bottle", "Stream", "Volume", "State", "Log"];
  const rows = fu.waste.map(b => {
    const status = fu.waste_status[String(b.id)];
    const changeState = state => save(fu.waste.map(item => item === b ? { ...item, state } : item)).catch(NB.fail);
    const csv = "/api/case/" + encodeURIComponent(NB.state.case) + route + "?format=csv&id=" + encodeURIComponent(b.id);
    const entries = b.entries || [];
    return h("tr", {},
      h("td", {}, h("strong", {}, NB.formula(b.label)), h("div", { class: "small muted" }, b.location),
        b.opened ? h("div", { class: "small muted" }, "Opened " + b.opened) : null),
      h("td", {}, NB.formula(b.stream)), h("td", { class: "num" }, NB.wasteVolume(b, status)),
      h("td", {}, h("span", { class: "chip " + (b.state === "full" || status.nearly_full ? "needed" : "plain") }, bottleState(b, status))),
      h("td", {}, h("div", { class: "row" },
        h("button", { class: "quiet", onclick: () => addEntry(fu, [b], null, save) }, "Add entry"),
        b.state === "open" ? h("button", { class: "quiet", onclick: () => changeState("full") }, "Mark full") : null,
        b.state !== "picked-up" ? h("button", { class: "quiet", onclick: () => changeState("picked-up") }, "Mark picked up") : null,
        h("a", { href: csv, "aria-label": "Download CSV for " + b.label }, "CSV")),
        entries.length ? h("details", {}, h("summary", {}, "Entries (" + entries.length + ")"), h("ul", { class: "small" },
          entries.map(entry => h("li", {}, NB.formula([entry.date, entry.exp, entry.contents, entry.volume_mL + " mL", entry.by].filter(Boolean).join(" · ")))))) : null));
  });
  return h("section", {}, h("h2", {}, "Waste bottles"),
    h("p", { class: "muted small" }, "Researcher reminder only, at " + (fu.waste_reminder_fraction * 100).toLocaleString() + "% of capacity."),
    h("p", {}, h("button", { class: "secondary", onclick: () => addBottle(fu, save) }, "Add bottle")),
    rows.length ? h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, columns.map(c => h("th", { scope: "col", class: c === "Volume" ? "num" : null }, c)))), h("tbody", {}, rows)))
      : h("p", { class: "empty" }, "No waste bottles yet."));
};
})();
