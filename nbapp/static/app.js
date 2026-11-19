/* Notebook app: core, navigation, dashboard, experiment index, flags, inventory, change log. */
"use strict";
const NB = {
  token: document.querySelector('meta[name="nb-token"]').content,
  state: { root: "", cases: [], case: null, user: "", elements: {}, index: null, inventory: false, inventory_dir: "inventory" },
  routes: [],
  routeSeq: 0,          // raised on every navigation, so a slow page that finishes late cannot draw over a newer one
};
class StaleRead extends Error {}
NB.StaleRead = StaleRead;

NB.localDate = function (date = new Date()) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return date.getFullYear() + "-" + month + "-" + day;
};

/* ---------- small helpers */
NB.h = function (tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "value") el.value = v;
    else if (k === "checked" || k === "disabled" || k === "selected") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
};
const h = NB.h;
NB.put = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false));   // never prints "null"

NB.api = async function (method, path, body, always) {
  const seq = NB.routeSeq, opt = { method, headers: { "X-NB-Token": NB.token } };
  if (body instanceof Blob) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch(path, opt); }
  catch (e) { throw new Error("The notebook app is not answering. Check that its window is still running, then reload."); }
  const data = (res.headers.get("Content-Type") || "").includes("json") ? await res.json() : await res.text();
  if (method === "GET" && !always && seq !== NB.routeSeq) throw new StaleRead("The page changed while this was loading.");
  if (!res.ok) { const err = new Error((data && data.error) || ("Request failed (" + res.status + ")")); err.status = res.status; throw err; }
  return data;
};
NB.capi = (method, path, body) => NB.api(method, "/api/case/" + encodeURIComponent(NB.state.case) + path, body);
NB.fileUrl = rel => "/file/" + encodeURIComponent(NB.state.case) + "/" + rel.split("/").map(encodeURIComponent).join("/");
NB.toast = function (msg, isError, actions) {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  actions = actions ? [].concat(actions) : [];
  const t = h("div", { class: "toast" + (isError ? " err" : ""), role: "status" }, msg,
    actions.length ? h("div", { class: "row", style: "margin-top:8px" }, actions.map(a => h("button", { onclick: () => { t.remove(); a.run(); } }, a.label)),
      h("button", { class: "x", onclick: () => t.remove() }, "Dismiss")) : null);
  document.body.append(t);
  if (!actions.length) setTimeout(() => t.remove(), isError ? 9000 : 3500);
};
NB.fail = function (e) {
  if (e instanceof StaleRead) return;
  if (e.status === 409) return NB.toast(e.message, true, { label: "Load the current version", run: () => NB.route() });   // someone else saved this record
  NB.toast(e.message || String(e), true);
};
/* ---------- unsaved work: a prompt before leaving, a draft kept on this computer, and a three-way merge after a conflict */
NB.dirty = false;
NB.confirmLeave = () => !NB.dirty || confirm("Leave this page? Your unsaved changes are kept as a draft on this computer and offered when you come back.");
window.addEventListener("beforeunload", e => { if (NB.dirty) { e.preventDefault(); e.returnValue = ""; } });
NB.draft = {
  key: k => "nb-draft:" + NB.state.case + ":" + k,
  save(k, data) { try { localStorage.setItem(this.key(k), JSON.stringify({ t: Date.now(), data })); } catch (e) { /* storage full or off */ } },
  load(k) { try { return JSON.parse(localStorage.getItem(this.key(k)) || "null"); } catch (e) { return null; } },
  clear(k) { try { localStorage.removeItem(this.key(k)); } catch (e) { /* nothing to clear */ } },
};
NB.same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
NB.merge3 = function (base, mine, theirs) {     // my changes on top of theirs; `both` lists what each side changed differently
  const out = JSON.parse(JSON.stringify(theirs)), both = [];
  for (const k of new Set([...Object.keys(base), ...Object.keys(mine)])) {
    if (NB.same(mine[k], base[k])) continue;
    if (k === "entries" && mine.entries) {
      const b = base.entries || {}, t = theirs.entries || {};
      out.entries = Object.assign({}, t);
      for (const tag of new Set([...Object.keys(b), ...Object.keys(mine.entries)])) {
        if (NB.same(mine.entries[tag], b[tag])) continue;
        if (!NB.same(t[tag], b[tag]) && !NB.same(t[tag], mine.entries[tag])) both.push("entry " + tag);
        if (mine.entries[tag] === undefined) delete out.entries[tag]; else out.entries[tag] = mine.entries[tag];
      }
      continue;
    }
    if (!NB.same(theirs[k], base[k]) && !NB.same(theirs[k], mine[k])) both.push(k);
    if (mine[k] === undefined) delete out[k]; else out[k] = mine[k];
  }
  return { merged: out, both };
};
NB.expNo = id => parseInt(id.split("-")[1], 10);
NB.typeClass = t => "t-" + (/synth/.test(t) ? "synthesis" : /screen/.test(t) ? "screening" : /comput/.test(t) ? "computational" : "other");
NB.vial = function (row, href) {
  const legacy = row.legacy_id && !/not yet|computational/.test(row.legacy_id) ? h("small", {}, row.legacy_id) : null;
  return h(href ? "a" : "span", { class: "vial " + NB.typeClass(row.type || "") + (row.status === "planned" ? " planned" : ""), href: href || null },
    "Exp " + NB.expNo(row.id), legacy);
};
NB.flagChips = function (flags) {
  const out = [];
  for (const tier of ["blocking", "needed"])
    if (flags[tier]) out.push(h("span", { class: "chip " + tier, title: flags[tier] + " " + tier + " flag" + (flags[tier] > 1 ? "s" : "") }, flags[tier] + " " + tier));
  return out.length ? h("span", { class: "row", style: "gap:4px;flex-wrap:nowrap" }, out) : h("span", { class: "muted" }, "none");
};
NB.fmtTime = iso => { try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); } catch (e) { return iso; } };
NB.openNative = async function (path) {
  try { await NB.capi("POST", "/open", { path }); } catch (e) { NB.fail(e); }
};
NB.pageHead = function ({ eyebrow, title, status, actions, number, badge, tabs, screenOnly }) {
  const heading = title && title.tagName === "H1" ? title : h("h1", {}, title);
  if (number != null) {
    return h("header", { class: "page-head exphead" + (screenOnly ? " noprint" : "") },
      h("div", { class: "no" }, h("span", {}, "Experiment"), String(number)),
      h("div", { class: "what" }, badge, heading, status),
      actions ? h("div", { class: "head-actions row noprint" }, actions) : null, tabs);
  }
  return h("header", { class: "page-head" },
    h("div", { class: "eyebrow noprint" }, eyebrow || NB.shellPage(location.hash || "#/").group),
    actions ? h("div", { class: "row", style: "justify-content:space-between" }, heading, actions) : heading,
    status);
};
NB.setView = function (...nodes) {
  const v = document.getElementById("view");
  NB.put(v, ...nodes.flat(Infinity).filter(x => x !== null && x !== undefined && x !== false));
  if (NB.recordShell) {
    if (NB.recordShell.toggle && !v.querySelector("#record-drawer")) NB.recordShell = null;
    NB.drawBar();
  }
  window.scrollTo(0, 0);
};
NB.loadIndex = async function () {
  NB.state.index = await NB.capi("GET", "/index");
  return NB.state.index;
};

NB.rebuild = async function (ev, force) {
  const btn = ev && ev.currentTarget;
  if (btn) { btn.disabled = true; btn.textContent = "Rebuilding…"; }
  try {
    const res = await NB.capi("POST", "/build", { force: !!force });
    if (res.pending) {
      NB.toast(res.message, true, [
        { label: "Review and import them", run: async () => { try { NB.wordImport((await NB.capi("GET", "/wordsync")).items); } catch (e) { NB.fail(e); } } },
        { label: "Rebuild anyway (a copy of the Word file is kept)", run: () => NB.rebuild(null, true) }]);
    } else if (res.ok) NB.toast("Word notebook and index rebuilt." + (res.kept ? "\nThe previous Word file is in " + res.kept + "." : ""));
    else NB.toast(res.message, true);
    if (res.ok && NB.state.index) NB.state.index.stale = false;
    await NB.loadIndex();
  } catch (e) { NB.fail(e); }
  NB.drawBar();
};

NB.openCase = function (item, seq) {
  if (!NB.state.cases.some(c => c.name === item.name)) {
    NB.state.cases.push(item);
    NB.state.cases.sort((a, b) => a.name.localeCompare(b.name));
  }
  if (seq !== NB.routeSeq) return NB.drawBar();
  NB.state.case = item.name;
  NB.state.index = null;
  localStorage.setItem("nb-case", item.name);
  if ((location.hash || "#/") === "#/") NB.route();
  else location.hash = "#/";
};
NB.openDemo = async function (event) {
  if (!NB.confirmLeave()) return;
  const button = event.currentTarget;
  button.disabled = true;
  const seq = NB.routeSeq;
  try {
    const demo = NB.state.cases.find(c => c.demo) || await NB.api("POST", "/api/demo", {});
    if (seq === NB.routeSeq) NB.dirty = false;
    NB.openCase(demo, seq);
  } catch (e) { NB.fail(e); }
  finally { button.disabled = false; }
};

NB.startNotebook = function () {
  const name = h("input", { type: "text", required: true });
  const title = h("input", { type: "text" }), researcher = h("input", { type: "text" });
  const message = h("div", { role: "alert" });
  const submit = h("button", { type: "submit", class: "primary" }, "Create notebook");
  const field = (label, control) => h("label", { class: "f" }, h("span", {}, label), control);
  NB.setView(NB.pageHead({ eyebrow: "Tools", title: "Start a notebook" }),
    h("p", { class: "prose" }, "The project folder holds rules for AI agents that the researcher can edit."),
    h("form", { class: "prose", onsubmit: async e => {
      e.preventDefault();
      if (submit.disabled) return;
      submit.disabled = true;
      NB.put(message);
      const seq = NB.routeSeq;
      try {
        const created = await NB.api("POST", "/api/cases", { name: name.value.trim(), title: title.value.trim(), researcher: researcher.value.trim() });
        NB.openCase(created, seq);
      } catch (err) {
        if (seq === NB.routeSeq) NB.put(message, h("div", { class: "banner err" }, err.message));
      } finally {
        submit.disabled = false;
      }
    } },
      field("Notebook folder name", name), field("Title (optional)", title), field("Researcher (optional)", researcher),
      message, h("p", { class: "row" }, submit, h("button", { type: "button", onclick: NB.openDemo }, "Open a demo notebook"),
        NB.state.case ? h("a", { href: "#/" }, "Cancel") : null)),
    h("p", { class: "prose" }, "The demo uses invented values to teach record review."),
    NB.state.inventory ? null : NB.inventoryUpload());
  name.focus();
};

NB.notFound = function (reason) {
  NB.setView(NB.pageHead({ eyebrow: "Navigation", title: "Page not found" }), reason && h("p", {}, reason),
    h("p", {}, h("a", { href: "#/" }, "Back to Today")));
};

/* ---------- router */
NB.route = async function () {
  const hash = location.hash || "#/";
  const my = ++NB.routeSeq;
  NB.currentHash = hash;
  NB.recordShell = null;
  if (hash !== "#/experiments") NB.pendingSearch = null;
  NB.dirty = false;
  const help = /^#\/help(?:\/|$)/.test(hash);
  try {
    if (NB.state.case && !NB.state.index) await NB.loadIndex();
    NB.drawBar();
    if (hash === "#/followups" && !NB.state.schedule_and_supplies) return NB.notFound(NB.state.schedule_off_message);
    if ((!NB.state.case && !help) || hash === "#/start") return NB.startNotebook();
    for (const [re, fn] of NB.routes) {
      const m = hash.match(re);
      if (m) {
        await fn(...m.slice(1));
        const head = document.querySelector("#view h1");
        if (head && my === NB.routeSeq && !document.activeElement?.matches("#view input, #view textarea")) {
          head.tabIndex = -1; head.focus({ preventScroll: true });
        }
        return;
      }
    }
    NB.notFound();
  } catch (e) {
    if (e instanceof StaleRead) return;
    NB.setView(h("div", { class: "banner err" }, e.message || String(e)), h("p", {}, h("a", { href: "#/" }, "Back to Today")));
  }
};
NB.start = async function () {
  try {
    const st = await NB.api("GET", "/api/state", undefined, true);
    Object.assign(NB.state, { root: st.root, cases: st.cases, user: st.user, elements: st.elements, formula_rules: st.formula_rules, inventory: st.inventory,
      schedule_and_supplies: st.schedule_and_supplies, schedule_off_message: st.schedule_off_message,
      inventory_dir: st.inventory_dir || "inventory", about: st.about, sketcher: st.sketcher, structureReason: st.structure_reason, reference_lookup: st.reference_lookup });
    const saved = localStorage.getItem("nb-case");
    NB.state.case = st.cases.some(c => c.name === saved) ? saved : (st.cases[0] && st.cases[0].name);
  } catch (e) { return NB.setView(h("div", { class: "banner err" }, e.message)); }
  window.addEventListener("hashchange", () => {
    if (NB.skipHash) { NB.skipHash = false; return; }
    if ((location.hash || "#/") !== NB.currentHash && !NB.confirmLeave()) {
      NB.pendingSearch = null;
      NB.skipHash = true; location.hash = NB.currentHash; return;
    }
    NB.route();
  });
  NB.route();
};

/* ---------- Today: what is next at the bench comes first, record curation after it */
NB.routes.push([/^#\/$/, async function () {
  const idx = await NB.loadIndex();
  const [flags, changes, word, fu] = await Promise.all([NB.capi("GET", "/flags"), NB.capi("GET", "/changes?limit=8"), NB.capi("GET", "/wordsync"),
    NB.state.schedule_and_supplies ? NB.capi("GET", "/followups").catch(e => { if (e instanceof NB.StaleRead) throw e; return null; }) : null]);
  NB.drawBar();
  const byId = Object.fromEntries(idx.rows.map(r => [r.id, r]));
  const next = idx.rows.filter(r => r.status === "planned");
  const nextIds = new Set(next.map(r => r.id));
  const blocking = flags.flags.filter(f => f.tier === "blocking");
  const before = blocking.filter(f => nextIds.has(f.exp)), curation = blocking.filter(f => !nextIds.has(f.exp));
  const counts = {};
  idx.rows.forEach(r => { const k = NB.typeClass(r.type).slice(2); counts[k] = (counts[k] || 0) + 1; });
  const fresh = word.items.filter(i => i.kind === "new").length, clash = word.items.length - fresh;
  const today = NB.localDate();
  const due = fu ? fu.tasks.filter(t => t.state === "open" && t.start && t.start.slice(0, 10) <= today) : [];
  const need = fu ? fu.supplies.filter(x => x.state !== "ok") : [];
  const waste = fu ? fu.waste.filter(b => b.state === "full" || fu.waste_status[String(b.id)].nearly_full) : [];
  const demo = NB.state.cases.some(c => c.name === NB.state.case && c.demo);
  const caveats = h("details", { open: demo }, h("summary", {}, "Project question and shared caveats"),
    h("p", { class: "prose" }, idx.question), h("ul", { class: "prose" }, idx.caveats.map(c => h("li", {}, c.replace(/`/g, "")))));
  NB.setView(
    NB.pageHead({ title: idx.title,
      status: h("p", { class: "muted", style: "margin:4px 0 14px" }, idx.rows.length ? idx.rows.length + " experiments: " + Object.entries(counts).map(([k, n]) => n + " " + k).join(", ") + "." : "No experiments yet.") }),
    demo ? [caveats, h("p", {}, h("a", { href: "#/help/DEMO.md" }, "Demo walk-through"))] : null,
    !demo && !NB.state.inventory ? NB.inventoryUpload() : null,
    word.items.length ? h("div", { class: "banner" },
      h("span", {}, (fresh ? fresh + " field" + (fresh === 1 ? "" : "s") + " typed into the Word notebook " + (fresh === 1 ? "is" : "are") + " not in the records yet. " : "") +
        (clash ? clash + " field" + (clash === 1 ? "" : "s") + " differ" + (clash === 1 ? "s" : "") + " between Word and a newer record value." : "")),
      h("button", { onclick: () => NB.wordImport(word.items) }, "Review")) : null,
    fu && (due.length || need.length || waste.length) ? [h("h2", {}, "Due today or overdue"),
      h("ul", { class: "plain attention" }, due.map(t => h("li", {}, h("strong", {}, t.start.slice(11, 16) || "any time"), "  ", NB.formula(t.text), t.exp ? ["  ", NB.vial(byId[t.exp] || { id: t.exp }, "#/exp/" + t.exp)] : null)),
        need.map(x => h("li", {}, h("span", { class: "chip needed" }, x.state === "ordered" ? "ordered" : "running low"), "  ", NB.formula(x.item), x.count !== undefined ? " (" + x.count + " left)" : "")),
        waste.map(b => h("li", {}, h("span", { class: "chip needed" }, b.state === "full" ? "full" : "nearly full"),
          "  ", NB.formula(b.label), " (" + NB.wasteVolume(b, fu.waste_status[String(b.id)]) + ")"))),
      h("p", { class: "small" }, h("a", { href: "#/followups" }, "Open the schedule and supplies"))] : null,
    h("h2", {}, "Next at the bench"),
    next.length ? h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, next.map(r => h("tr", {},
      h("td", { style: "width:1%" }, NB.vial(r, "#/exp/" + r.id)),
      h("td", {}, NB.formula(r.title), before.filter(f => f.exp === r.id).map(f => h("div", { class: "small", style: "color:var(--blocking)" }, NB.formula("Before you start (" + f.id + "): " + f.text)))),
      h("td", { style: "width:1%;white-space:nowrap" }, h("a", { href: "#/exp/" + r.id + "/bench" }, "Bench card")))))))
      : h("p", { class: "empty" }, "Nothing planned. ", h("a", { href: "#/new" }, "Plan an experiment")),
    h("h2", {}, curation.length ? "Record curation: blocking flags on recorded experiments (" + curation.length + ")" : "No blocking flags on recorded experiments"),
    curation.length ? h("ul", { class: "plain attention" }, curation.map(f => h("li", {},
      NB.vial(byId[f.exp], "#/exp/" + f.exp), " ", h("span", { class: "muted" }, f.id + " "), NB.formula(f.text)))) : null,
    h("h2", {}, "Recent changes"),
    changes.changes.length ? h("ul", { class: "plain" }, changes.changes.map(c => h("li", { class: "small", style: "margin-bottom:4px" },
      h("span", { class: "muted" }, NB.fmtTime(c.ts) + "  "), c.exp ? h("a", { href: "#/exp/" + c.exp }, "Exp " + NB.expNo(c.exp)) : null, c.exp ? "  " : "",
      c.summary || c.action, c.fields && c.fields.length ? h("span", { class: "muted" }, "  (" + c.fields.join(", ") + ")") : null)))
      : h("p", { class: "empty" }, "No changes saved yet."),
    demo ? null : caveats,
    h("p", { class: "row noprint", style: "margin-top:18px" },
      idx.notebook ? h("button", { class: "quiet", onclick: () => NB.openNative(idx.notebook) }, "Open the Word notebook") : null,
      h("button", { class: "quiet", onclick: () => NB.openNative(".") }, "Open the notebook folder"))
  );
}]);

NB.wordImport = function (items) {
  const picks = new Set(items.filter(i => i.kind === "new").map(i => i.tag));
  NB.setView(
    NB.pageHead({ eyebrow: "Tools", title: "Typed in Word",
      status: h("p", { class: "prose" }, "Importing copies a Word field into the record, so the next rebuild keeps it. Fields marked as a conflict also changed in the record after the last rebuild: they start unticked, and ticking one replaces the record's value with the Word text.") }),
    h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Import"), h("th", {}, "Experiment"), h("th", {}, "Field"), h("th", {}, "In Word"), h("th", {}, "In the record now"), h("th", {}, "Status"))),
      h("tbody", {}, items.map(i => h("tr", {},
        h("td", {}, h("input", { type: "checkbox", checked: i.kind === "new", "aria-label": "Import " + i.field, onchange: e => e.target.checked ? picks.add(i.tag) : picks.delete(i.tag) })),
        h("td", {}, h("a", { href: "#/exp/" + i.exp }, "Exp " + NB.expNo(i.exp))), h("td", {}, i.field),
        h("td", { style: "white-space:pre-wrap" }, i.word), h("td", { class: "muted", style: "white-space:pre-wrap" }, i.record || "empty"),
        h("td", {}, h("span", { class: "chip " + (i.kind === "new" ? "good" : "needed") }, i.kind === "new" ? "new in Word" : "conflict"))))))),
    h("p", { class: "row", style: "margin-top:14px" },
      h("button", { class: "primary", onclick: async () => {
        try { const r = await NB.capi("POST", "/wordsync", { tags: [...picks] }); NB.toast(r.imported + " field(s) imported."); NB.state.index = null; location.hash = "#/"; NB.route(); }
        catch (e) { NB.fail(e); } } }, "Import ticked fields"),
      h("a", { href: "#/" }, "Cancel"))
  );
};

NB.searchAllRecords = function (text) {
  NB.pendingSearch = text;
  if (location.hash === "#/experiments") NB.route();
  else location.hash = "#/experiments";
};

/* ---------- Flags */
NB.routes.push([/^#\/flags$/, async function () {
  const [idx, res] = await Promise.all([NB.loadIndex(), NB.capi("GET", "/flags")]);
  NB.drawBar();
  const byId = Object.fromEntries(idx.rows.map(r => [r.id, r]));
  const blocking = res.flags.filter(f => f.tier === "blocking");
  const needed = res.flags.filter(f => f.tier === "needed");
  const nice = res.flags.filter(f => f.tier === "nice");
  const experiments = new Set([...blocking, ...needed].map(f => f.exp)).size;
  const groups = new Map();
  for (const f of needed) {
    if (!groups.has(f.exp)) groups.set(f.exp, []);
    groups.get(f.exp).push(f);
  }
  const table = list => list.length ? h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {},
    list.map(f => h("tr", {}, h("td", {}, NB.vial(byId[f.exp], "#/exp/" + f.exp)), h("td", { class: "muted" }, f.id),
      h("td", {}, NB.formula(f.text)), h("td", {}, h("a", { href: "#/exp/" + f.exp + "/edit" }, "Resolve")))))))
    : h("p", { class: "empty" }, "None.");
  const extra = h("div", {});
  const reveal = h("button", { class: "quiet", "aria-expanded": "false", onclick: () => {
    const show = reveal.getAttribute("aria-expanded") === "false";
    reveal.setAttribute("aria-expanded", String(show));
    reveal.textContent = show ? "Hide nice-to-have flags" : "Show nice-to-have flags";
    NB.put(extra, show ? table(nice) : null);
  } }, "Show nice-to-have flags");
  NB.setView(NB.pageHead({ title: "Open flags", status: h("p", { class: "muted" },
    blocking.length + " blocking and " + needed.length + " needed on " + experiments + (experiments === 1 ? " experiment." : " experiments.")) }),
    h("h2", { class: "tier blocking" }, "Blocking (" + blocking.length + ")"), table(blocking),
    h("h2", { class: "tier needed" }, "Needed (" + needed.length + ")"),
    groups.size ? Array.from(groups, ([id, flags]) => h("details", {},
      h("summary", {}, id + " · ", NB.formula(byId[id].title), " (" + flags.length + ")"), table(flags))) : table([]),
    h("p", { class: "small" }, nice.length + " nice-to-have " + (nice.length === 1 ? "flag" : "flags"), nice.length ? [" · ", reveal] : null), extra);
}]);

/* ---------- Inventory */
NB.demoCase = () => NB.state.cases.some(c => c.name === NB.state.case && c.demo);
NB.hasInventory = () => NB.state.inventory || NB.demoCase();
NB.inventoryQuery = function (query) {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (NB.demoCase()) params.set("case", NB.state.case);
  const suffix = params.toString();
  return NB.api("GET", "/api/inventory" + (suffix ? "?" + suffix : ""));
};
NB.inventoryMissing = () => h("p", { class: "empty" },
  h("a", { href: "#/inventory" }, "Upload an inventory workbook"), " to find bottles while planning.");
NB.inventoryUpload = function (onImported) {
  const message = h("p", { class: "small", role: "status" });
  const input = h("input", { type: "file", accept: ".xlsx", "aria-label": "Upload inventory workbook" });
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    input.disabled = true;
    message.textContent = "Reading " + file.name + "…";
    try {
      const result = await NB.api("POST", "/api/inventory/import?name=" + encodeURIComponent(file.name), file);
      NB.state.inventory = true;
      if (!input.isConnected) return;
      const confirmation = result.name + " added · " + result.bottles + (result.bottles === 1 ? " bottle." : " bottles.");
      if (onImported) { NB.toast(confirmation); onImported(); }
      else message.textContent = confirmation;
    } catch (err) { message.textContent = err.message; }
    finally { input.disabled = false; input.value = ""; }
  };
  return h("fieldset", {}, h("legend", {}, "Upload inventory workbook"),
    h("p", {}, "Choose an .xlsx file to search your bottles. The first worksheet needs a Name, Chemical Name or ChemName column."),
    input, message);
};
NB.routes.push([/^#\/inventory(?:\?(.*))?$/, async function (params) {
  const info = await NB.inventoryQuery();
  NB.state.inventory = !!info.source.files && !info.demo_inventory;
  const structures = NB.inventoryStructureSearch();
  const upload = NB.inventoryUpload(() => NB.route());
  if (!info.source.files || info.bottles === 0) {
    const empty = info.source.files ? "The exports contain no readable bottle rows." : "This project has no inventory yet.";
    return NB.setView(NB.pageHead({ title: "Inventory", status: h("p", {}, empty) }), upload, structures);
  }
  const search = NB.inventorySearch(new URLSearchParams(params || "").get("q") || (info.demo_inventory ? "acetone" : ""));
  const description = info.demo_inventory ? "Demo inventory. Bottle locations and amounts are fictional. Upload your own workbook to search your project’s stock."
    : "Searches the spreadsheet exports in the project, best name match first, then your group's bottles. Check the shelf for current stock.";
  NB.setView(NB.pageHead({ title: "Inventory", status: h("p", { class: "muted" }, description) }), search.el, structures, upload);
  search.input.focus();
}]);

let inventorySearchId = 0;
NB.inventorySearch = function (initial = "", onPick, onClose) {
  const id = "inventory-results-" + ++inventorySearchId;
  const input = h("input", { type: "search", role: "combobox", "aria-label": "Search inventory", "aria-haspopup": "grid",
    "aria-controls": id, "aria-expanded": "false", "aria-autocomplete": "list", value: initial,
    placeholder: "Chemical name, product number, barcode, CAS or formula" });
  const status = h("p", { class: "muted small", role: "status" });
  const table = h("table", { id, role: "grid", "aria-label": "Inventory results" });
  let timer, generation = 0, items = [], active = -1;
  function select(index, scroll) {
    const rows = table.querySelectorAll("tbody tr");
    if (rows[active]) rows[active].setAttribute("aria-selected", "false");
    active = index;
    if (!rows[index]) { input.removeAttribute("aria-activedescendant"); return; }
    rows[index].setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", rows[index].id);
    if (scroll) rows[index].scrollIntoView({ block: "nearest" });
  }
  function pick(index) {
    if (!items[index]) return;
    if (onPick) { const item = items[index]; input.value = ""; schedule(); onPick(item); }
    else {
      select(index);
      input.value = items[index].name;
      items = [items[index]];
      render(1);
    }
  }
  function render(total, source) {
    NB.put(table);
    if (items.length) {
      const headers = ["Chemical", "Group", "Location", "Left", "Supplier, product no.", "Barcode"];
      if (onPick) headers.push("");
      NB.put(table, h("thead", {}, h("tr", {}, headers.map(label => h("th", { scope: "col" }, label)))),
        h("tbody", {}, items.map((i, index) => h("tr", { id: id + "-" + index, "aria-selected": "false",
          onmousedown: e => e.preventDefault(), onclick: () => pick(index) },
          h("td", {}, NB.formula(i.name, i.highlights),
            i.match === "part" ? h("span", { class: "chip plain", title: "The search word is only part of a longer name" }, "related name") : null,
            i.same_formula ? h("span", { class: "chip needed", title: i.same_formula.join(", ") }, "same formula, different CAS: check the isomer") : null,
            h("div", { class: "muted small" }, NB.formula([i.formula, i.cas].filter(Boolean).join(" · ")))),
          h("td", {}, i.group), h("td", {}, i.location || "–"),
          h("td", { class: "num" }, [i.remaining, i.unit].filter(Boolean).join(" ") || "–"),
          h("td", {}, [i.supplier, i.product].filter(Boolean).join(", ")), h("td", {}, i.barcode || ""),
          onPick ? h("td", {}, h("button", { class: "quiet", tabindex: -1 }, "Use")) : null))));
    }
    input.setAttribute("aria-expanded", String(!!items.length));
    status.textContent = items.length + " of " + total + (source?.newest ? " · Inventory export of " + source.newest : "");
    select(items.length ? 0 : -1);
  }
  function schedule() {
    const query = input.value.trim(), mine = ++generation;
    clearTimeout(timer);
    items = []; render(0);
    if (query.length < 2) { status.textContent = "Type at least two characters."; return; }
    status.textContent = "Searching…";
    timer = setTimeout(async () => {
      try {
        const result = await NB.inventoryQuery(query);
        if (generation !== mine || !input.isConnected) return;
        items = result.items; render(result.total, result.source);
        if (!items.length) status.textContent += " · No bottle matches in the inventory exports.";
      } catch (err) { if (mine === generation && input.isConnected) NB.fail(err); }
    }, 150);
  }
  input.addEventListener("input", schedule);
  input.addEventListener("keydown", e => {
    if (e.isComposing) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); input.value = ""; schedule(); }
    else if (items.length && ["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) {
      e.preventDefault();
      if (e.key === "Enter") pick(active);
      else select(Math.max(0, Math.min(items.length - 1, active + (e.key === "ArrowDown" ? 1 : -1))), true);
    }
  });
  schedule();
  return { input, el: h("div", {}, h("div", { class: "toolbar" }, input,
    onClose ? h("button", { class: "x", onclick: onClose }, "Close") : null), status, h("div", { class: "tablewrap" }, table)) };
};

/* ---------- Change log */
NB.routes.push([/^#\/changes$/, async function () {
  const res = await NB.capi("GET", "/changes?limit=500");
  NB.setView(
    NB.pageHead({ title: "Change log",
      status: h("p", { class: "muted" }, "Record saves, newest first. The previous versions are in _logs/history.") }),
    res.changes.length ? h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Who"), h("th", {}, "Via"), h("th", {}, "Experiment"), h("th", {}, "What"), h("th", {}, "Fields changed"))),
      h("tbody", {}, res.changes.map(c => h("tr", {},
        h("td", { style: "white-space:nowrap" }, NB.fmtTime(c.ts)), h("td", {}, c.by || "–"), h("td", {}, c.via || "–"),
        h("td", {}, c.exp ? h("a", { href: "#/exp/" + c.exp }, "Exp " + NB.expNo(c.exp)) : "–"),
        h("td", {}, c.summary || c.action), h("td", { class: "muted" }, (c.fields || []).join(", ")))))))
      : h("p", { class: "empty" }, "No changes saved yet."));
}]);
