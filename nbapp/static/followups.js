/* Schedule, supplies and waste bottles. */
"use strict";
(function () {
const h = NB.h;
NB.routes.push([/^#\/followups$/, async function () {
  const [idx, loaded] = await Promise.all([NB.loadIndex(), NB.capi("GET", "/followups")]);
  let fu = loaded;
  const byId = Object.fromEntries(idx.rows.map(r => [r.id, r]));
  const box = h("div", {});
  const put = async () => {
    try { fu = await NB.capi("PUT", "/followups", { tasks: fu.tasks, supplies: fu.supplies.map(s => Object.assign({}, s, { state: s.stored || "ok" })), hash: fu.hash }); draw(); }
    catch (e) { NB.fail(e); if (e.status === 409) NB.route(); }
  };
  const saveWaste = async (waste, hash) => {
    fu = await NB.capi("PUT", "/followups/waste", { waste, hash });
    draw();
  };
  const fmt = d => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const iso = d => NB.localDate(d) + "T" + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  const shift = (task, minutes) => {              // move a task and everything that waits for it
    const moved = new Set([task.id]);
    for (let grew = true; grew;) { grew = false; for (const t of fu.tasks) if (!moved.has(t.id) && moved.has(t.after) && (t.state || "open") === "open") { moved.add(t.id); grew = true; } }
    for (const t of fu.tasks) if (moved.has(t.id) && t.start) t.start = iso(new Date(new Date(t.start).getTime() + minutes * 60000));
    put();
  };
  const addTask = () => {
    const f = { text: h("input", { type: "text", placeholder: "For example: column for Exp 19", style: "flex:2 1 240px", "aria-label": "Task" }),
      exp: h("select", { "aria-label": "Experiment" }, h("option", { value: "" }, "No experiment"), idx.rows.map(r => h("option", { value: r.id }, "Exp " + r.n))),
      start: h("input", { type: "datetime-local", "aria-label": "Start" }), minutes: h("input", { type: "number", min: 0, step: 5, value: 60, style: "width:80px", "aria-label": "Length in minutes" }),
      hands: h("input", { type: "checkbox", checked: true }), equipment: h("input", { type: "text", placeholder: "Equipment (optional)", style: "width:160px", "aria-label": "Equipment" }),
      after: h("select", { "aria-label": "Starts after" }, h("option", { value: "" }, "Not waiting for a task"), fu.tasks.filter(t => (t.state || "open") === "open").map(t => h("option", { value: t.id }, "After: " + t.text.slice(0, 40)))) };
    return h("div", { class: "row", style: "margin:8px 0 14px" }, f.text, f.exp, f.start, f.minutes, h("span", { class: "muted small" }, "min"),
      h("label", { class: "row", style: "gap:5px" }, f.hands, "needs me at the bench"), f.equipment, f.after,
      h("button", { class: "primary", onclick: () => {
        if (!f.text.value.trim()) return NB.toast("Describe the task.", true);
        const t = { id: Math.max(0, ...fu.tasks.map(x => x.id || 0)) + 1, text: f.text.value.trim(), state: "open", hands_on: f.hands.checked };
        if (f.exp.value) t.exp = f.exp.value;
        if (f.start.value) { t.start = f.start.value; t.minutes = parseFloat(f.minutes.value) || 0; }
        if (f.equipment.value.trim()) t.equipment = f.equipment.value.trim();
        if (f.after.value) t.after = parseInt(f.after.value, 10);
        fu.tasks.push(t); put();
      } }, "Add task"));
  };
  const addSupply = () => {
    const item = h("input", { type: "text", placeholder: "For example: NMR tubes", style: "flex:1 1 200px", "aria-label": "Supply" }), count = h("input", { type: "number", min: 0, placeholder: "count", style: "width:90px", "aria-label": "Count on hand" }),
      low = h("input", { type: "number", min: 0, placeholder: "follow up at", style: "width:120px", "aria-label": "Follow up at or below this count" }), note = h("input", { type: "text", placeholder: "Note (supplier, size…)", style: "flex:1 1 200px", "aria-label": "Note" });
    return h("div", { class: "row", style: "margin:8px 0 14px" }, item, count, low, note, h("button", { class: "secondary", onclick: () => {
      const name = item.value.trim();
      if (!name) return NB.toast("Name the supply.", true);
      if (fu.supplies.some(s => s.item.toLowerCase() === name.toLowerCase())) return NB.toast(name + " is already on the list. Update that line instead of adding a second one.", true);
      const s = { item: name, state: "ok", stored: "ok" };
      if (count.value !== "") s.count = parseFloat(count.value);
      if (low.value !== "") s.threshold = parseFloat(low.value);
      if (note.value.trim()) s.note = note.value.trim();
      fu.supplies.push(s); put();
    } }, "Add supply"));
  };
  const draw = () => {
    const hash = fu.hash;
    const open = fu.tasks.filter(t => (t.state || "open") === "open").sort((a, b) => String(a.start || "9999").localeCompare(String(b.start || "9999")));
    const closed = fu.tasks.filter(t => (t.state || "open") !== "open");
    const clash = id => fu.conflicts.filter(c => c.a === id || c.b === id).map(c => c.why + " as task " + (c.a === id ? c.b : c.a));
    let day = null;
    const rows = [];
    for (const t of open) {
      const d = t.start ? t.start.slice(0, 10) : "No time set";
      if (d !== day) { day = d; rows.push(h("tr", {}, h("td", { colspan: 4, style: "background:var(--paper);padding-top:12px" }, h("strong", {}, t.start ? new Date(t.start).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }) : d)))); }
      const s = t.start ? new Date(t.start) : null, e = s ? new Date(s.getTime() + (t.minutes || 0) * 60000) : null, dep = fu.tasks.find(x => x.id === t.after);
      rows.push(h("tr", {},
        h("td", { style: "white-space:nowrap;width:1%" }, h("span", { class: "muted" }, "#" + t.id + "  "), s ? fmt(s) + "–" + fmt(e) : "–"),
        h("td", {}, NB.formula(t.text), t.exp ? ["  ", NB.vial(byId[t.exp] || { id: t.exp }, "#/exp/" + t.exp)] : null,
          h("div", { class: "small" }, h("span", { class: "chip plain" }, t.hands_on ? "at the bench" : "unattended"), t.equipment ? h("span", { class: "chip plain", style: "margin-left:4px" }, t.equipment) : null,
            dep ? h("span", { class: "muted" }, "  after #" + dep.id + " " + dep.text.slice(0, 30)) : null,
            clash(t.id).map(w => h("span", { class: "chip blocking", style: "margin-left:4px" }, "clash: " + w)),
            fu.late.includes(t.id) ? h("span", { class: "chip needed", style: "margin-left:4px" }, "starts before #" + t.after + " ends") : null)),
        h("td", { style: "white-space:nowrap;width:1%" },
          h("button", { class: "quiet", onclick: () => { t.state = "done"; t.done = NB.localDate(); put(); } }, "Done"), " ",
          t.start ? [h("button", { class: "quiet", title: "Move this task and the tasks waiting for it one hour later", onclick: () => shift(t, 60) }, "+1 h"), " ",
            h("button", { class: "quiet", title: "Move this task and the tasks waiting for it one day later", onclick: () => shift(t, 1440) }, "+1 day"), " "] : null,
          h("button", { class: "x", onclick: () => { t.state = "dropped"; t.done = NB.localDate(); put(); } }, "Drop"))));
    }
    NB.put(box,
      h("h2", {}, "Schedule"),
      h("p", { class: "muted small" }, "Give a task a start and a length. Two tasks that both need you at the bench, or the same equipment, are marked when they overlap. Moving a task moves the tasks that wait for it."),
      addTask(),
      open.length ? h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, rows))) : h("p", { class: "empty" }, "No open tasks."),
      closed.length ? h("details", {}, h("summary", {}, "Finished and dropped (" + closed.length + ")"), h("ul", { class: "small" }, closed.map(t => h("li", {}, (t.done || "") + "  " + t.state + ": ", NB.formula(t.text))))) : null,
      h("h2", {}, "Supplies"),
      h("p", { class: "muted small" }, "One line per item. A count at or below its follow-up level marks the item as running low. Counts change only when you change them; planned experiments do not deduct anything."),
      addSupply(),
      fu.supplies.length ? h("div", { class: "tablewrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", { class: "num" }, "On hand"), h("th", { class: "num" }, "Follow up at"), h("th", {}, "State"), h("th", {}, ""))),
        h("tbody", {}, fu.supplies.map(s => {
          const set = (state, n) => { s.stored = state; if (n !== undefined) s.count = n; put(); };
          const step = d => { s.count = Math.max(0, (s.count || 0) + d); put(); };
          return h("tr", {}, h("td", {}, NB.formula(s.item), s.note ? h("div", { class: "muted small" }, NB.formula(s.note)) : null),
            h("td", { class: "num", style: "white-space:nowrap" }, s.count === undefined ? "–" : [h("button", { class: "quiet", "aria-label": "One fewer " + s.item, onclick: () => step(-1) }, "−1"), "  " + s.count + "  ", h("button", { class: "quiet", "aria-label": "One more " + s.item, onclick: () => step(1) }, "+1")]),
            h("td", { class: "num" }, s.threshold === undefined ? "–" : s.threshold),
            h("td", {}, h("span", { class: "chip " + (s.state === "ok" ? "good" : "needed") }, s.state === "ok" ? "fine" : s.state === "ordered" ? "ordered" : "running low")),
            h("td", { style: "white-space:nowrap" },
              s.state === "ok" ? h("button", { class: "quiet", onclick: () => set("needed") }, "Needs follow-up") : null,
              s.state === "needed" ? h("button", { class: "quiet", onclick: () => set("ordered") }, "Ordered") : null,
              s.state !== "ok" ? [" ", h("button", { class: "quiet", onclick: () => { const n = prompt("Restocked. How many are on hand now?", s.count === undefined ? "" : String(s.count)); if (n === null) return; set("ok", n.trim() === "" ? s.count : parseFloat(n)); } }, "Restocked")] : null));
        })))) : h("p", { class: "empty" }, "No supplies listed yet."),
      NB.wasteSection(fu, waste => saveWaste(waste, hash)));
  };
  draw();
  NB.setView(NB.pageHead({ title: "Schedule and supplies" }), box);
}]);
})();
