/* Experiment page, edit form and bench card. */
"use strict";
(function () {
const h = NB.h;
const METRIC_KINDS = ["yield", "conversion", "dr", "ee", "er", "regioselectivity", "other"];
NB.isScreening = type => /screen/i.test(type || "");
NB.hasYieldMetric = kind => kind === "yield" || !METRIC_KINDS.includes(kind);
NB.metricText = rec => [rec.metric_kind, rec.metric].filter(Boolean).join(" — ");
NB.metricKindSelect = (kind, change) => h("select", { onchange: e => change(e.target.value) },
  h("option", { value: "" }, "Choose a metric"),
  METRIC_KINDS.map(k => h("option", { value: k, selected: k === kind }, k)));

/* ---------- chemistry helpers shared with the planner */
NB.mw = function (formula) {
  const el = NB.state.elements, text = String(formula || "").replace(/\s+/g, "").replace(/[+-]\d*$/, "");
  if (!text) return null;
  let total = 0;
  for (let part of text.split(/[·*]/)) {
    if (!part) continue;
    let mult = 1;
    const lead = part.match(/^(\d+)(?=[A-Z(\[])/);
    if (lead) { mult = parseInt(lead[1], 10); part = part.slice(lead[0].length); }
    const stack = [0];
    const re = /([A-Z][a-z]?)(\d*\.?\d*)|([(\[])|([)\]])(\d*\.?\d*)/g;
    let m, used = 0;
    while ((m = re.exec(part))) {
      if (m.index !== used) return null;
      used = re.lastIndex;
      if (m[1]) { if (!(m[1] in el)) return null; stack[stack.length - 1] += el[m[1]] * (m[2] ? parseFloat(m[2]) : 1); }
      else if (m[3]) stack.push(0);
      else { if (stack.length < 2) return null; const g = stack.pop(); stack[stack.length - 1] += g * (m[5] ? parseFloat(m[5]) : 1); }
    }
    if (used !== part.length || stack.length !== 1) return null;
    total += stack[0] * mult;
  }
  return total || null;
};
NB.basisKind = function (basis) {
  const b = String(basis || "").trim().toLowerCase();
  if (b.startsWith("measured")) return "measured";
  if (b.includes("slide")) return "slides";
  if (b.startsWith("target")) return "target";
  if (b.startsWith("literature")) return "literature";
  return b ? "other" : "none";
};
NB.outlinedBasis = kind => kind === "target" || kind === "literature";
NB.yieldLegend = (...extra) => h("div", { class: "legend yield-legend" },
  h("span", {}, h("i", {}), "measured or recorded"),
  h("span", {}, h("i", { class: "slides" }), "from slides, not re-integrated"),
  h("span", {}, h("i", { class: "outlined" }), "target or literature, not measured here"),
  h("span", {}, h("i", { class: "upper" }), "upper bound (<)"), ...extra);
NB.parseResult = function (text) {   // {kind: yield|nd|nr|text|none, value, qualifier, label}; the label is the result as written
  const t = String(text || "").trim(), low = t.toLowerCase();
  if (!t) return { kind: "none" };
  if (low.startsWith("nr")) return { kind: "nr" };
  if (low.startsWith("nd") || low.startsWith("no product") || low.startsWith("not detected")) return { kind: "nd", label: "nd" };
  const range = t.match(/^(\d+(?:\.\d+)?)\s*%?\s*(?:[-−–—]|\bto\b)\s*(\d+(?:\.\d+)?)\s*%/i);
  if (range) return { kind: "yield", value: Math.min(Number(range[1]), Number(range[2])), qualifier: "", label: t };
  const m = t.match(/^([<>~≈≤≥]?)\s*(\d+(?:\.\d+)?)\s*%/);
  return m ? { kind: "yield", value: parseFloat(m[2]), qualifier: m[1], label: m[1] + m[2] + "%" } : { kind: "text" };
};
NB.parseYield = t => { const p = NB.parseResult(t); return p.kind === "yield" ? p.value : null; };
NB.yieldBar = function (result, basis, metricEntry) {
  const p = metricEntry ? { kind: "yield", value: metricEntry.width, qualifier: metricEntry.qualifier, label: result } : NB.parseResult(result);
  if (p.kind !== "yield" && p.kind !== "nd") return h("span", {}, result || "–");
  const kind = NB.basisKind(basis);
  const style = NB.outlinedBasis(kind) ? " outlined" : kind === "slides" ? " slides" : "";
  const cls = "fill" + style + (p.qualifier === "<" || p.qualifier === "≤" ? " upper" : "");
  return h("div", { class: "bar", title: result + (basis ? " (" + basis + ")" : "") },
    h("div", { class: "track" }, p.kind === "yield" && p.value > 0 ? h("div", { class: cls, style: "width:" + Math.min(100, p.value) + "%" }) : null),
    h("span", { class: "val" }, p.label));
};
function materialLocation(material, bottles, limit, style) {
  if (material.bottle) return h("div", { class: style }, NB.formula("Bottle: " + NB.bottleText(material.bottle)));
  if (!bottles?.length) return null;
  const labels = bottles.slice(0, limit).map(b => {
    const details = [b.location || b.path || "location unrecorded"];
    if (!b.own_group && b.group) details.push(b.group);
    if (b.name.toLowerCase() !== (material.name || "").toLowerCase()) {
      details.push(b.name.length > 36 ? b.name.slice(0, 35) + "…" : b.name);
    }
    if (b.empty) details.push("empty");
    return details.join(" · ");
  });
  const more = bottles.length - labels.length;
  return h("div", { class: style }, "Kept in: ", labels.join("; "), more > 0 ? [" · ",
    h("a", { href: "#/inventory?q=" + encodeURIComponent(bottles[0].query) }, "+" + more + " more")] : null,
    bottles[0].basis === "name" ? " · name match, check the label" : null);
}

NB.bottleText = b => typeof b === "string" ? b : b ? [b.supplier, b.product, b.location, b.barcode ? "barcode " + b.barcode : ""].filter(Boolean).join(", ") : "";
NB.runTag = (id, run) => "exp" + String(NB.expNo(id)).padStart(2, "0") + "_run_" + String(run).toLowerCase().replace(/[^a-z0-9]+/g, "_") + "_yield";
NB.entryFields = function (rec) {
  const nn = String(NB.expNo(rec.id)).padStart(2, "0");
  const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const groups = [];
  if (rec.planned && rec.materials) {
    const mats = rec.materials.filter(m => !String(m.id).startsWith("P"));
    const vessels = rec.vessels && rec.vessels.length ? rec.vessels : [null];
    for (const v of vessels)
      groups.push({ title: "Actual charges" + (v ? ", vessel " + v : ""), kind: "actual",
        fields: mats.map(m => ({ tag: "exp" + nn + "_actual_" + (v ? v + "_" : "") + m.id, label: m.id + "  " + (m.name || m.formula || ""), hint: "planned " + (m.amount || "") })) });
  }
  if (rec.planned_work) {
    const pw = rec.planned_work, f = [];
    for (let i = 0; i < (pw.tlc_rows || 0); i++) (pw.tlc_columns || []).forEach((c, j) => f.push({ tag: "exp" + nn + "_tlc_r" + (i + 1) + "c" + (j + 1), label: "TLC " + (i + 1) + ": " + c, hint: "" }));
    if (f.length) groups.push({ title: "TLC screen", fields: f });
    groups.push({ title: "Purification", fields: (pw.fields || []).map(x => ({ tag: "exp" + nn + "_purif_" + slug(x.field), label: x.field, hint: x.hint })) });
  }
  if (rec.bench) {
    const vessels = rec.vessels && rec.vessels.length ? rec.vessels : [null];
    for (const v of vessels)
      groups.push({ title: "Bench record" + (v ? ", vessel " + v : ""),
        fields: rec.bench.map(x => ({ tag: "exp" + nn + "_bench_" + (v ? v.replace(/-/g, "_") + "_" : "") + slug(x.field), label: x.field, hint: x.hint })) });
  }
  if (rec.planned && rec.runs && rec.runs.length)
    groups.push({ title: "Run results", fields: rec.runs.map(r => ({ tag: NB.runTag(rec.id, r.run), label: "Run " + r.run + (r.variable ? ": " + r.variable : ""),
      hint: rec.metric_kind ? "Record " + rec.metric_kind + " and its basis" : "Result with its basis, e.g. 41% (1H vs mesitylene)" })) });
  if (rec.result_fields) groups.push({ title: "Results", fields: rec.result_fields.map(x => ({ tag: "exp" + nn + "_result_" + slug(x.field), label: x.field, hint: x.hint })) });
  return { groups, review: "review_exp" + nn };
};
NB.fmtNum = (v, d1, d2) => v === undefined || v === null || typeof v !== "number" ? (v || "") : (Math.round(v * 10 ** d1) / 10 ** d1 === v ? v.toFixed(d1) : v.toFixed(d2));
const para = (label, text) => text ? h("p", { class: "prose" }, h("strong", { style: "font-family:var(--ui)" }, label + " "), NB.formula(text)) : null;
const gridTable = (head, rows) => h("div", { class: "tablewrap" }, h("table", {},
  head ? h("thead", {}, h("tr", {}, head.map(c => h("th", {}, c)))) : null, h("tbody", {}, rows.map(r => h("tr", {}, r.map(c => h("td", {}, c?.nodeType ? c : NB.formula(c))))))));

function attachmentBlock(id, view) {
  const d = view.derived;
  const file = h("input", { type: "file", required: true });
  const kind = h("select", { required: true }, d.attachment_kinds.map(k => h("option", { value: k, selected: k === "other" }, k)));
  const sample = h("input", { type: "text" });
  const run = h("input", { type: "text" });
  const note = h("input", { type: "text" });
  const submit = h("button", { type: "submit", class: "secondary" }, "Attach");
  const upload = async e => {
    e.preventDefault();
    const picked = file.files[0];
    if (!picked) return;
    const query = new URLSearchParams({ kind: kind.value, name: picked.name, sample: sample.value.trim(),
      run: run.value.trim(), note: note.value.trim(), hash: view.meta.hash });
    submit.disabled = true;
    try {
      const result = await NB.capi("POST", "/record/" + id + "/attach?" + query, picked);
      NB.toast(result.changed ? "File attached." : "File already attached.");
      NB.state.index = null;
      if (location.hash === "#/exp/" + id) NB.route();
    } catch (err) { submit.disabled = false; NB.fail(err); }
  };
  return [
    h("h2", {}, "Attachments"),
    d.attachments.length ? gridTable(["Kind", "Name", "Sample or run", "Added", "State"], d.attachments.map(a => {
      const path = typeof a.path === "string" ? a.path : "";
      const name = path.split("/").pop() || "Invalid path";
      const url = path && NB.fileUrl(path) + (a.directory ? "?exp=" + encodeURIComponent(id) : "");
      return [a.kind, !url || a.state === "missing" ? name : h("a", { href: url, target: "_blank", rel: "noopener" }, name),
        [a.sample ? "Sample " + a.sample : "", a.run ? "Run " + a.run : ""].filter(Boolean).join(", "),
        String(a.added || "").slice(0, 10), h("span", { class: "chip " + (a.state === "ok" ? "good" : "needed") }, a.state)];
    })) : null,
    h("details", { class: "noprint" }, h("summary", {}, "Attach file"),
      h("form", { onsubmit: upload }, h("div", { class: "cols c2" }, field("File", file), field("Kind", kind),
        field("Sample (optional)", sample), field("Run (optional)", run)), field("Note (optional)", note), submit)),
  ];
}

/* ---------- experiment page */
NB.experimentHead = function (view, current, actions) {
  const rec = view.record, d = view.derived, record = "#/exp/" + rec.id;
  const hasSpectra = d.acquisitions.some(a => a.exists && a.spectra.length);
  const legacy = rec.legacy_id && !/not yet|computational/.test(rec.legacy_id) ? rec.legacy_id : null;
  const meta = [rec.type ? rec.type[0].toUpperCase() + rec.type.slice(1) : null, rec.started ? "started " + rec.started : null, rec.researcher, rec.status].filter(Boolean).join(", ") + "." + (rec.eln ? " ELN " + rec.eln + "." : "");
  const tab = (name, href) => h("a", { href, "aria-current": current === name ? "page" : null }, name);
  const tabs = h("nav", { class: "exp-tabs noprint", "aria-label": "Experiment pages" },
    tab("Record", record),
    (rec.planned || NB.entryFields(rec).groups.length) ? tab("Bench card", record + "/bench") : null,
    rec.runs && hasSpectra ? tab("NMR yields", "#/nmr/" + rec.id) : null,
    (!rec.runs && hasSpectra || rec.materials?.some(m => m.name_basis?.kind === "generated" || m.name_basis?.generated))
      ? tab("SI draft", "#/si/" + rec.id) : null);
  NB.recordShell = { id: rec.id, prev: d.prev, next: d.next };
  const blocking = (rec.flags || []).filter(f => f.tier === "blocking").length;
  return NB.pageHead({ number: d.n, title: NB.formula(rec.title), actions, tabs, screenOnly: location.hash !== record,
    badge: legacy ? h("span", { class: "vial " + NB.typeClass(rec.type || "") + (rec.status === "planned" ? " planned" : "") }, legacy) : null,
    status: h("div", { class: "muted" }, meta, h("span", { class: "head-chips noprint" },
      rec.status ? h("span", { class: "chip plain" }, rec.status) : null,
      blocking ? h(current === "Record" ? "a" : "span", { class: "chip blocking", href: current === "Record" ? record + "/edit" : null }, blocking + " blocking") : null)) });
};

NB.routes.push([/^#\/exp\/(EXP-\d+)$/, async function (id) {
  const view = await NB.capi("GET", "/record/" + id);
  const rec = view.record, d = view.derived, n = d.n;
  const entries = rec.entries || {};
  const ef = NB.entryFields(rec);
  const head = NB.experimentHead(view, "Record",
    [h("a", { class: "btn primary", href: "#/exp/" + id + "/edit" }, "Edit"),
      d.experiment_folder ? h("button", { class: "quiet noprint", onclick: () => NB.openNative(d.experiment_folder) }, "Open the experiment folder") : null]);

  const main = [];
  main.push(para("Question.", rec.question), para(rec.metric_kind ? "Primary metric." : "Metric.", NB.metricText(rec)));
  const requestEdit = (row, method) => { NB.openStructureFor = { id, material: row?.id, method }; location.hash = "#/exp/" + id + "/edit"; };
  const openDrawing = () => requestEdit(null, null);
  if (d.scheme || d.scheme_preview) main.push(h("div", {}, NB.recordScheme(view, NB.state.structureReason ? null : openDrawing),
    d.scheme_is_full_drawing ? h("div", { class: "muted small" }, "Full ChemDraw preview. Its drawn table is not updated from the record; use the materials table below.") : null));
  else if (d.index_scheme) main.push(h("div", { class: "scheme" }, h("img", {
    src: NB.schemeUrl(id, view.meta.hash), alt: rec.scheme_alt || "Reaction scheme for Exp " + n,
    ondblclick: openDrawing, onerror: e => e.currentTarget.parentElement.remove() })));
  const sketchScheme = NB.isSketch(rec, rec.reaction?.drawing);
  const drawScheme = h("button", { class: "quiet noprint", disabled: !!NB.drawReason(), title: NB.drawReason(),
    onclick: () => requestEdit(null, "draw") }, "Edit in Draw");
  const nativeReason = sketchScheme ? NB.drawReason() : NB.state.structureReason;
  const nativeScheme = h("button", { class: "quiet noprint", disabled: !!nativeReason, title: nativeReason,
    onclick: () => requestEdit(null, "native") }, "Edit in ChemDraw");
  main.push(...NB.schemeEditButtons(sketchScheme, drawScheme, nativeScheme));
  for (const warning of d.validation.filter(v => v.kind === "scheme_mismatch")) {
    main.push(h("p", { class: "note caution" }, warning.msg));
  }
  if (d.same_step?.length) main.push(h("details", {}, h("summary", {}, "Same step (" + d.same_step.length + ")"),
    d.same_step.map(hit => h("p", {}, h("a", { href: "#/exp/" + hit.id }, hit.id, " · ", NB.formula(hit.title)), " · ", hit.key_result, " · ", hit.started))));
  if (rec.summary_basis) main.push(h("p", { class: "muted small" }, rec.summary_basis));

  if (rec.materials && rec.materials.length) {
    const fmt = NB.fmtNum;
    main.push(h("h2", {}, rec.planned ? "Materials (planned)" : rec.runs ? "Materials per run" : "Materials"),
      h("div", { class: "tablewrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "ID"), h("th", {}, "Material"), h("th", {}, "Formula"), h("th", { class: "num" }, "MW"), h("th", {}, rec.planned ? "Planned" : "Amount"),
          h("th", { class: "num" }, "mmol"), h("th", { class: "num" }, "equiv"), h("th", {}, "Note"))),
        h("tbody", {}, rec.materials.map(m => h("tr", {}, h("td", {}, h("strong", {}, m.id)), h("td", {}, NB.materialDrawing(view, m, (method) => requestEdit(m, method)), m.check_name ? "Check the name · " : null, NB.formula(m.name || m.formula),
          m.name && NB.nameBasisText(m.name_basis) ? h("div", { class: "muted small" }, NB.nameBasisText(m.name_basis)) : null,
          materialLocation(m, (rec.planned || rec.status === "planned") && d.locations?.[m.id], 3, "muted small")), h("td", {}, m.formula ? NB.formula(m.formula) : ""),
          h("td", { class: "num" }, m.mw || ""), h("td", {}, m.amount || ""), h("td", { class: "num" }, fmt(m.mmol, 3, 4)), h("td", { class: "num" }, fmt(m.equiv, 2, 3)), h("td", { class: "muted" }, NB.formula(m.note),
            m.density_basis ? h("div", { class: "small" }, m.density + " g/mL · " + m.density_basis) : null)))))));
  }
  main.push(para("Conditions.", rec.conditions));
  if (rec.procedure && rec.procedure.length)
    main.push(h("h2", {}, rec.planned ? "Planned procedure" : "Procedure"), rec.procedure.map(p => h("p", { class: "prose" }, NB.formula(p))), rec.procedure_basis ? h("p", { class: "muted small" }, rec.procedure_basis) : null);
  if (rec.safety) main.push(h("div", { class: "note warning" }, h("strong", {}, "Safety. "), NB.formula(rec.safety)));
  if (d.hazards.length) main.push(h("details", { open: rec.planned ? true : null }, h("summary", {}, "Hazard prompts (" + d.hazards.length + ")"),
    d.hazards.map(p => h("div", { class: "note " + p.level }, NB.formula(p.text))),
    h("p", { class: "muted small" }, "Prompts from a short rule list (nbapp/data/hazards.yaml), not a safety assessment. Check the SDS and group SOPs.")));
  (rec.notes || []).forEach(t => main.push(h("p", { class: "muted small" }, NB.formula(t))));

  if (rec.runs && rec.runs.length) {
    const yields = NB.hasYieldMetric(rec.metric_kind);
    main.push(h("h2", {}, "Runs and results"),
      yields ? NB.yieldLegend() : null,
      h("div", { class: "tablewrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Run"), h("th", {}, "Conditions"), h("th", {}, yields ? "NMR yield" : "Result"), h("th", {}, "Basis"), h("th", {}, "Spectrum"))),
        h("tbody", {}, rec.runs.map(r => {
          const acq = d.acquisitions.find(a => a.sample === d.run_samples[String(r.run)]);
          const measured = r.measured && typeof r.measured === "object" ? r.measured.value : r.measured;
          const extra = yields && NB.parseYield(r.result) !== null && /\(/.test(r.result) ? h("div", { class: "muted small" }, r.result.slice(r.result.indexOf("(")))
            : typeof measured === "number" ? h("div", { class: "muted small" }, "integral gives " + measured.toFixed(1).replace("-", "−") + "%") : null;
          const shown = r.result || (rec.planned ? entries[NB.runTag(id, r.run)] : "") || "";
          const result = shown ? (yields ? NB.yieldBar(shown, r.basis) : shown) : h("span", { class: "muted" }, rec.planned ? "to be measured" : "–");
          return h("tr", {}, h("td", {}, h("strong", {}, r.run)), h("td", {}, NB.formula(r.variable)), h("td", {}, result, extra),
            h("td", { class: "small" }, NB.formula(r.basis)),
            h("td", { class: "small" }, acq && acq.exists ? NB.spectrumLinks(id, acq) : "–"));
        })))),
      rec.results_basis ? h("p", { class: "muted small", style: "margin-top:6px" }, NB.formula(rec.results_basis)) : null);
  } else if (rec.result) {
    main.push(h("h2", {}, "Result"), h("p", { class: "prose" }, h("strong", {}, NB.formula(rec.result.text)), h("span", { class: "muted" }, "  " + (rec.result.basis || ""))));
  }
  for (const g of ef.groups) {
    const filled = g.fields.filter(f => entries[f.tag]);
    main.push(h("h2", {}, g.title), filled.length
      ? h("dl", { class: "kv" }, filled.map(f => [h("dt", {}, NB.formula(f.label)), h("dd", { style: "white-space:pre-wrap" }, NB.formula(entries[f.tag]))]))
      : h("p", { class: "empty" }, "Nothing entered yet. ", h("a", { href: "#/exp/" + id + "/bench" }, "Open the bench card")));
  }
  if (rec.method) main.push(h("h2", {}, "Model and method"), gridTable(null, rec.method.map(r => [h("strong", {}, r[0]), r[1]])));
  if (rec.species) main.push(h("h2", {}, "Species"), gridTable(rec.species[0], rec.species.slice(1)));
  if (rec.status_items) main.push(h("h2", {}, rec.status_heading || "Status"), Object.entries(rec.status_items).map(([k, items]) => [h("h3", {}, k), h("ul", { class: "prose" }, items.map(i => h("li", {}, i)))]));
  if (rec.results_table) main.push(h("h2", {}, "Results"), rec.results_note ? h("p", { class: "muted small" }, rec.results_note) : null, gridTable(rec.results_table[0], rec.results_table.slice(1)));
  main.push(para("Interpretation.", rec.interpretation), para("Next.", rec.next));
  if (rec.next_items) main.push(h("h2", {}, "Next steps"), h("ul", { class: "prose" }, rec.next_items.map(i => h("li", {}, i))));
  if (rec.links) main.push(h("p", { class: "muted small" }, "Project files: ", rec.links.map((l, i) => [i ? "; " : "", h("a", { href: "#", title: l[1], onclick: e => { e.preventDefault(); NB.openNative(l[1]); } }, l[0])])));

  const loose = d.acquisitions.filter(a => !Object.values(d.run_samples).includes(a.sample));
  if (loose.length) main.push(h("h2", {}, rec.runs ? "Other NMR samples" : "NMR"),
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Sample"), h("th", {}, "Spectra (PDF)"), h("th", {}, "Acquired"), h("th", {}, ""))),
      h("tbody", {}, loose.map(a => h("tr", {}, h("td", {}, a.sample, a.exists ? null : h("span", { class: "chip needed", style: "margin-left:6px" }, "folder not found")),
        h("td", {}, a.exists ? NB.spectrumLinks(id, a) : a.spectra.map(s => s.nucleus + " " + s.mhz).join(", ")),
        h("td", {}, a.date), h("td", {}, a.exists ? h("button", { class: "quiet noprint", onclick: () => NB.openNative(a.folder) }, "Open folder") : null)))))));

  if (d.unlinked_nmr.length) main.push(h("div", { class: "note good", style: "margin-top:14px" },
    h("strong", {}, d.unlinked_nmr.length === 1 ? "One NMR folder is named for this experiment but not listed in the record." : d.unlinked_nmr.length + " NMR folders are named for this experiment but not listed in the record."),
    h("ul", { class: "small", style: "margin:6px 0;padding-left:18px" }, d.unlinked_nmr.map(u => h("li", {}, u.sample + ": " + u.spectra + (u.date ? ", acquired " + u.date : "")))),
    h("button", { class: "noprint", onclick: async () => {
      const next = JSON.parse(JSON.stringify(rec));
      next.nmr = (next.nmr || []).concat(d.unlinked_nmr);
      try { await NB.capi("PUT", "/record/" + id, { record: next, hash: view.meta.hash, summary: "linked " + d.unlinked_nmr.length + " NMR folder(s)" }); NB.toast("NMR folders linked to the record."); NB.state.index = null; NB.route(); }
      catch (e) { NB.fail(e); } } }, "Add to the record")));

  main.push(attachmentBlock(id, view));

  const side = [];
  if (!/comput/i.test(rec.type)) side.push(NB.referenceCard(view));
  const reviewBox = h("textarea", { rows: 3, placeholder: "Corrections or confirmations, reviewer and date", "aria-label": "Review response" });
  reviewBox.value = entries[ef.review] || "";
  side.push(h("h2", {}, "Review response"), reviewBox,
    h("button", { class: "quiet noprint", style: "margin-top:6px", onclick: async () => {
      const next = JSON.parse(JSON.stringify(rec));
      next.entries = Object.assign({}, next.entries);
      if (reviewBox.value.trim()) next.entries[ef.review] = reviewBox.value.trim(); else delete next.entries[ef.review];
      if (!Object.keys(next.entries).length) delete next.entries;
      try {
        const r = await NB.saveMerged(id, rec, next, view.meta.hash, "review response");
        if (r.conflict) return NB.toast("The review response was also changed elsewhere. Open Edit to compare; your text is still in the box.", true);
        NB.toast(r.changed ? "Review response saved." : "Nothing to save."); NB.state.index = null; NB.route();
      } catch (e) { NB.fail(e); } } }, "Save response"));
  if (rec.checks && rec.checks.length) side.push(h("h2", {}, "Checks"), rec.checks.map(c => h("p", { class: "small" }, c)));
  if (rec.history && rec.history.length) side.push(h("h2", {}, "Closed"), rec.history.map(c => h("p", { class: "small muted" }, c)));
  const src = rec.sources || {};
  side.push(h("h2", {}, "Sources"), h("ul", { class: "plain small" },
    d.eln ? h("li", {}, h("a", { href: NB.fileUrl(d.eln), target: "_blank", rel: "noopener" }, "ELN export (PDF)")) : null,
    d.chemdraw ? h("li", {}, h("a", { href: "#", onclick: e => { e.preventDefault(); if (/\.cdxml$/i.test(d.chemdraw)) openDrawing(); else NB.openNative(d.chemdraw); } }, "Open the ChemDraw file")) : null,
    src.slides ? h("li", {}, "Slides: " + src.slides) : null,
    Object.entries(src.refs || {}).map(([k, v]) => h("li", { style: "margin-top:4px" }, "[" + k + "] " + v)),
    h("li", { style: "margin-top:4px" }, h("a", { href: NB.fileUrl(d.record_path), target: "_blank", rel: "noopener" }, "Record file (" + d.record_path.split("/").pop() + ")"))));
  const drawer = h("aside", { id: "record-drawer", class: "margin dark", "aria-labelledby": "drawer-title" },
    h("div", { class: "drawer-heading noprint" }, h("h2", { id: "drawer-title" }, "Reference and review"),
      h("button", { class: "x", "aria-label": "Close review" }, "×")),
    h("div", {}, side));
  NB.setupDrawer(drawer, !!d.reference || !!reviewBox.value.trim());
  NB.setView(head, NB.sequenceLinks(view), h("div", { class: "split record-split", style: "margin-top:16px" }, h("div", {}, main), drawer));
}]);

/* ---------- edit form */
const bindText = (obj, key, attrs) => {
  const el = h(attrs && attrs.rows ? "textarea" : "input", Object.assign({ type: attrs && attrs.rows ? null : "text" }, attrs || {}));
  el.value = obj[key] === undefined || obj[key] === null ? "" : obj[key];
  el.addEventListener("input", () => { if (el.value === "") delete obj[key]; else obj[key] = el.value; });
  return el;
};
const field = (label, input, style) => h("label", { class: "f", style: style || null }, h("span", {}, label), input);
function gridEditor(rows, cols, blank, afterChange, rowAction) {
  const body = h("tbody", {});
  const draw = () => {
    NB.put(body, ...rows.map((r, i) => h("tr", {},
      cols.map(c => {
        const el = h("input", { type: "text", placeholder: c.key === "name" && r.smiles ? r.formula : null, inputmode: c.num ? "decimal" : null, "aria-label": c.label + " row " + (i + 1) });
        el.value = r[c.key] === undefined || r[c.key] === null ? "" : r[c.key];
        el.addEventListener("input", () => {
          const v = el.value.trim();
          if (v === "") delete r[c.key];
          else if (c.num) { const f = parseFloat(v); if (!isNaN(f)) r[c.key] = f; }
          else r[c.key] = c.keepString ? String(v) : v;
          if (afterChange) afterChange(r, c.key, el);
        });
        return h("td", {}, el);
      }),
      h("td", { style: "width:1%" }, rowAction ? rowAction(r, draw) : null,
        h("button", { class: "x", title: "Remove this row", "aria-label": "Remove row " + (i + 1), onclick: () => { rows.splice(i, 1); draw(); } }, "Remove")))));
  };
  draw();
  const grid = h("div", {}, h("div", { class: "tablewrap" }, h("table", { class: "grid" }, h("thead", {}, h("tr", {}, cols.map(c => h("th", { style: c.width ? "width:" + c.width : null }, c.label)), h("th", { style: "width:1%" }, ""))), body)),
    h("button", { class: "quiet", style: "margin-top:6px", onclick: () => { rows.push(blank()); draw(); } }, "Add a row"));
  grid.redraw = draw;
  return grid;
}
function listEditor(list, addLabel, rows) {
  const box = h("div", { class: "plist" });
  const draw = () => {
    NB.put(box, ...list.map((t, i) => {
      const ta = h("textarea", { rows: rows || 3, "aria-label": addLabel + " " + (i + 1) });
      ta.value = t;
      ta.addEventListener("input", () => { list[i] = ta.value; });
      return h("div", {}, ta, h("button", { class: "x", onclick: () => { list.splice(i, 1); draw(); } }, "Remove"));
    }), h("button", { class: "quiet", onclick: () => { list.push(""); draw(); } }, addLabel));
  };
  draw();
  return box;
}
function entryInputs(rec, group) {
  rec.entries = rec.entries || {};
  return h("div", { class: "cols c2" }, group.fields.map(f => {
    const el = h("textarea", { rows: 1, placeholder: f.hint || "" });
    el.value = rec.entries[f.tag] || "";
    el.addEventListener("input", () => { if (el.value.trim()) rec.entries[f.tag] = el.value; else delete rec.entries[f.tag]; });
    return field(f.label, el);
  }));
}
function cleanRecord(rec, base) {
  for (const k of ["procedure", "notes"]) if (Array.isArray(rec[k])) { rec[k] = rec[k].map(s => s.trim()).filter(Boolean); if (!rec[k].length) delete rec[k]; }
  for (const k of ["materials", "runs"]) if (Array.isArray(rec[k]) && !rec[k].length) delete rec[k];
  if (rec.entries && !Object.keys(rec.entries).length && (!base.entries || Object.keys(base.entries).length)) delete rec.entries;
  if (rec.result && !rec.result.text && !rec.result.basis) delete rec.result;
  (rec.runs || []).forEach(r => { if (r.run !== undefined) r.run = String(r.run); if (r.result === undefined) r.result = rec.planned ? "" : "nr"; });
  return rec;
}
NB.saveMerged = async function (id, base, mine, hash, summary, dependsOn = [], structures) {
  /* Save; if the record changed on disk meanwhile, put my changes on top of the current version.
     Returns the save result, or {conflict} when both sides changed the same field differently. */
  try { return await NB.capi("PUT", "/record/" + id, { record: mine, hash, summary, structures }); }
  catch (e) {
    if (e.status !== 409) throw e;
    const cur = await NB.capi("GET", "/record/" + id);
    const m = NB.merge3(base, mine, cur.record);
    for (const key of dependsOn) if (!NB.same(base[key], cur.record[key])) m.both.push(key);
    if (m.both.length) return { conflict: { view: cur, merged: m.merged, both: m.both } };
    const r = await NB.capi("PUT", "/record/" + id, { record: m.merged, hash: cur.meta.hash, summary, structures });
    r.rebased = true;
    return r;
  }
};
const draftBanner = (draft, onRestore, onDiscard) => h("div", { class: "banner noprint" },
  h("span", {}, "Unsaved changes from " + NB.fmtTime(draft.t) + " are kept on this computer."),
  h("span", { class: "row" }, h("button", { onclick: onRestore }, "Restore them"), h("button", { class: "quiet", onclick: onDiscard }, "Discard them")));

NB.applyStructureEdit = function (rec, structures, species, draft, previous, target) {
  const existing = rec.materials.map(m => ({ ...m, smiles: m.smiles || rec.smiles?.[m.id] }));
  const imported = NB.importSpecies(existing, species, previous, false, target);
  draft.material_ids = imported.slice(0, species.length).map(m => m.id);
  draft.material_positions = Object.fromEntries(species.map((m, i) => [draft.material_ids[i], m.position]));
  if (target) {
    const index = rec.materials.findIndex(m => m.id === target.id);
    if (index < 0) throw Error("The material row has been removed.");
    imported[0].id = target.id;
    draft.material_ids = [target.id]; draft.target = target.id;
    rec.materials.splice(index, 1, imported[0]);
    if (rec.smiles && Object.hasOwn(rec.smiles, target.id)) rec.smiles[target.id] = imported[0].smiles;
    if (rec.reaction && draft.schemeState) rec.reaction = { ...rec.reaction, smiles: draft.schemeState.smiles };
  } else rec.materials.splice(0, rec.materials.length, ...imported);
  Object.defineProperty(draft, "images", { value: Object.fromEntries(species.map((m, i) => [draft.material_ids[i], m.svg])) });
  structures.push(draft);
};

function editPage(view, start, opts) {
  opts = opts || {};
  const base = view.record, id = base.id, n = view.derived.n, key = "edit:" + id;
  const rec = JSON.parse(JSON.stringify(start || base));
  const proposal = NB.proposal?.id === id && NB.proposal.case === NB.state.case && !opts.draft ? NB.proposal : null;
  if (proposal) {
    NB.proposal = null;
    rec.characterization = [...(rec.characterization || []), proposal.line];
    rec.characterization_basis = [rec.characterization_basis, proposal.basis].filter(Boolean).join(" ");
  }
  let mode = "form";
  const structures = opts.structures || [];
  const ef = NB.entryFields(rec);
  rec.flags = rec.flags || [];
  const summary = h("input", { type: "text", placeholder: "What changed? (optional, goes to the change log)", "aria-label": "Change summary" });
  const yamlBox = h("textarea", { class: "code", rows: 30, spellcheck: "false", "aria-label": "Record as YAML" });
  const current = () => {
    const out = cleanRecord(JSON.parse(JSON.stringify(rec)), base);
    if (out.history && !out.history.length) delete out.history;
    if (out.characterization && !out.characterization.length && base.characterization?.length !== 0) delete out.characterization;
    return out;
  };
  const touch = () => {
    NB.dirty = true;
    clearTimeout(touch.t);
    touch.t = setTimeout(() => NB.draft.save(key, mode === "yaml" ? { hash: view.meta.hash, base, structures, yaml: yamlBox.value } : { hash: view.meta.hash, base, structures, rec: current() }), 400);
  };

  /* basics */
  const typeInput = bindText(rec, "type", { list: "types" });
  const metricFields = h("div", { class: "cols c2" },
    field("Primary metric", NB.metricKindSelect(rec.metric_kind, kind => {
      if (kind) rec.metric_kind = kind;
      else delete rec.metric_kind;
    })),
    field("Metric details", bindText(rec, "metric")));
  const showMetric = () => { metricFields.style.display = NB.isScreening(rec.type) || rec.metric || rec.metric_kind ? "" : "none"; };
  typeInput.addEventListener("input", showMetric);
  showMetric();
  const basics = h("fieldset", {}, h("legend", {}, "Basics"),
    h("div", { class: "cols c4" },
      "legacy_id" in rec ? field("Legacy ID", bindText(rec, "legacy_id")) : null,
      "eln" in rec ? field("ELN ID", bindText(rec, "eln")) : null,
      field("Type", typeInput), field("Status", bindText(rec, "status", { list: "statuses" }))),
    h("datalist", { id: "types" }, ["synthesis", "screening", "screening (isolation)", "computational", "NMR only"].map(t => h("option", { value: t }))),
    h("datalist", { id: "statuses" }, ["planned", "open", "complete"].map(t => h("option", { value: t }))),
    h("div", { class: "cols c2" }, field("Title", bindText(rec, "title")), h("div", { class: "cols c2" }, field("Started", bindText(rec, "started")), field("Researcher", bindText(rec, "researcher")))),
    field("Question", bindText(rec, "question", { rows: 2 })),
    h("label", { class: "checkline" }, h("input", { type: "checkbox", checked: !!rec.planned, onchange: e => { if (e.target.checked) rec.planned = true; else delete rec.planned; } }),
      h("span", {}, "Show planned and actual charges side by side. This is a layout choice; Status says whether the experiment is still planned.")),
    metricFields,
    field("Key result with its basis (shown in the index)", bindText(rec, "key_result")),
    field("Scheme image (optional). Enter the path relative to the notebook folder, for example " + view.derived.scheme_example, bindText(rec, "scheme_image")));

  /* materials */
  rec.materials = rec.materials || [];
  let materialGrid;
  const lookup = NB.referencePanel((row, values) => {
    if (!rec.materials.includes(row)) return false;
    NB.applyReference(row, values);
    materialGrid.redraw();
    touch();
  });
  materialGrid = gridEditor(rec.materials, [{ key: "id", label: "ID", width: "6%" }, { key: "name", label: "Material", width: "30%" }, { key: "formula", label: "Formula", width: "12%" },
      { key: "mw", label: "MW", num: true, width: "8%" }, { key: "amount", label: "Amount", width: "14%" }, { key: "mmol", label: "mmol", num: true, width: "8%" },
      { key: "equiv", label: "equiv", num: true, width: "7%" }, { key: "density", label: "g/mL", num: true },
      { key: "note", label: "Note", width: "15%" }],
      () => ({ id: "R" + (rec.materials.filter(m => String(m.id).startsWith("R")).length + 1), name: "" }),
      (row, k, el) => {
        if (k === "name") row.name_basis = { kind: "entered" };
        if (k === "name" && row.check_name) { delete row.check_name; el.closest("tr").querySelector("[data-name-check]")?.remove(); }
        if (k === "density") delete row.density_basis;
        if (k !== "formula") return;
        const w = NB.mw(row.formula);
        if (w && !row.mw) { row.mw = Math.round(w * 1000) / 1000; el.closest("tr").querySelectorAll("input")[3].value = row.mw; }
      }, row => [lookup.button(row), NB.materialDrawing(view, row, (method, opener) =>
        structureBox.edit({ ...row, smiles: row.smiles || rec.smiles?.[row.id] }, method, opener).catch(NB.fail), structures),
        row.check_name ? h("button", { class: "quiet", "data-name-check": true, onclick: () => { delete row.check_name; materialGrid.redraw(); touch(); } }, "Check the name · confirm") : null]);
  const mats = h("fieldset", {}, h("legend", {}, "Materials"), materialGrid, lookup.panel,
    h("p", { class: "muted small", style: "margin-top:6px" }, "MW fills in from the formula when it is empty. Saving checks MW against the formula and mass against mmol."));

  /* procedure */
  rec.procedure = rec.procedure || [];
  rec.notes = rec.notes || [];
  const proc = h("fieldset", {}, h("legend", {}, "Conditions and procedure"),
    field("Conditions", bindText(rec, "conditions", { rows: 2 })),
    h("label", { class: "f" }, h("span", {}, "Procedure, one paragraph per step")), listEditor(rec.procedure, "Add a paragraph"),
    field("Procedure basis (as run, adapted from a reference, planned…)", bindText(rec, "procedure_basis", { rows: 2 }), "margin-top:10px"),
    field("Safety note", bindText(rec, "safety", { rows: 2 })));

  /* results */
  rec.runs = rec.runs || [];
  rec.result = rec.result || {};
  const charBox = h("textarea", { rows: 3, placeholder: "¹H NMR (500 MHz, CDCl3) δ 8.46 (s, 4H), 8.07 (s, 2H).", "aria-label": "Reviewed characterization" });
  charBox.value = (rec.characterization || []).join("\n");
  charBox.addEventListener("input", () => { const l = charBox.value.split("\n").map(x => x.trim()).filter(Boolean); if (l.length) rec.characterization = l; else delete rec.characterization; });
  const results = h("fieldset", {}, h("legend", {}, "Results"),
    h("label", { class: "f" }, h("span", {}, "Runs (screening). Every result needs a basis: measured, recalculated, slides, literature or target. Keep qualifiers as written: <4%, ~44%, nd, nr.")),
    gridEditor(rec.runs, [{ key: "run", label: "Run", width: "8%", keepString: true }, { key: "variable", label: "Conditions", width: "36%" }, { key: "result", label: "Result", width: "18%" }, { key: "basis", label: "Basis", width: "38%" }],
      () => ({ run: String(rec.runs.length + 1), variable: "", result: rec.planned ? "" : "nr" })),
    field("Basis for the run table as a whole", bindText(rec, "results_basis", { rows: 2 }), "margin-top:10px"),
    h("div", { class: "cols c2" }, field("Isolated result (synthesis), for example 940 mg, 2.060 mmol, 13.4%", bindText(rec.result, "text")), field("Basis of that result", bindText(rec.result, "basis"))),
    h("div", { class: "cols c2" }, field("Reviewed characterization for the SI, one line per spectrum. Leave empty until the assignment has been reviewed.", charBox),
      field("Who reviewed it, and when", bindText(rec, "characterization_basis"))),
    field("Interpretation", bindText(rec, "interpretation", { rows: 3 })), field("Next", bindText(rec, "next", { rows: 2 })));

  const bench = ef.groups.length ? h("fieldset", {}, h("legend", {}, "Bench entries"), ef.groups.map(g => [h("h3", {}, g.title), entryInputs(rec, g)])) : null;
  rec.entries = rec.entries || {};
  const review = h("fieldset", {}, h("legend", {}, "Review response"), bindText(rec.entries, ef.review, { rows: 2, placeholder: "Corrections or confirmations, reviewer and date" }));

  /* flags */
  rec.history = rec.history || [];
  const flagBox = h("div", {});
  const drawFlags = () => {
    NB.put(flagBox, rec.flags.map((f, i) => {
      const closeNote = h("input", { type: "text", placeholder: "How was it closed?", style: "flex:1 1 220px", "aria-label": "Closing note for flag " + f.id });
      const closeRow = h("div", { class: "row", style: "display:none;margin:4px 0 0 0" }, closeNote,
        h("button", { onclick: () => {
          if (!closeNote.value.trim()) return NB.toast("Say how the flag was closed; the note goes to the record's history.", true);
          rec.history.push(f.id + " closed " + NB.localDate() + ": " + closeNote.value.trim());
          rec.flags.splice(i, 1); drawFlags();
        } }, "Close flag"));
      const tier = h("select", { "aria-label": "Tier of flag " + f.id, onchange: e => { f.tier = e.target.value; } }, ["blocking", "needed", "nice"].map(t => h("option", { value: t, selected: f.tier === t }, t)));
      return h("div", { class: "flag " + f.tier, style: "margin-bottom:12px" },
        h("div", { class: "row" }, h("strong", {}, f.id), tier, h("button", { class: "quiet", onclick: () => { closeRow.style.display = "flex"; closeNote.focus(); } }, "Resolve…")),
        bindText(f, "text", { rows: 2, "aria-label": "Text of flag " + f.id }), closeRow);
    }), h("button", { class: "quiet", onclick: () => {
      const used = rec.flags.map(f => f.id).concat((rec.history.join(" ").match(/\b\d+\.\d+\b/g) || [])).filter(x => x.startsWith(n + ".")).map(x => parseInt(x.split(".")[1], 10));
      rec.flags.push({ id: n + "." + (Math.max(0, ...used) + 1), tier: "needed", text: "" }); drawFlags();
    } }, "Add a flag"),
    rec.flags.length > 3 ? h("p", { class: "small", style: "color:var(--needed)" }, "More than three open flags. The house rule is three or fewer per entry.") : null);
  };
  drawFlags();

  const structureBox = NB.structureBox({ id, view, record: () => rec, hasScheme: !!view.derived.scheme,
    drafts: () => structures, rows: () => rec.materials.map(m => ({ ...m, smiles: m.smiles || rec.smiles?.[m.id] })),
    apply: (species, draft, previous, target) => {
      NB.applyStructureEdit(rec, structures, species, draft, previous, target); materialGrid.redraw(); touch();
    } });
  const formPane = h("div", {}, basics, structureBox.box, /comput/.test(rec.type || "") ? h("div", { class: "note" }, "Method, species and result tables of computational entries are edited in the record file view.") : [mats, proc, results], bench,
    h("fieldset", {}, h("legend", {}, "Open flags"), flagBox), review);
  const yamlPane = h("div", { style: "display:none" }, h("p", { class: "muted" }, "The same draft as YAML, for fields the form does not cover. Switching views carries your edits across."), yamlBox);
  for (const ev of ["input", "change"]) { formPane.addEventListener(ev, touch); yamlPane.addEventListener(ev, touch); }
  formPane.addEventListener("click", e => { if (e.target.tagName === "BUTTON") touch(); });
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Editor view" });
  const printSeg = seg.cloneNode(false);
  const drawSeg = () => {
    NB.put(seg,
      h("button", { class: mode === "form" ? "on" : "", "aria-pressed": String(mode === "form"), onclick: async () => {
        if (mode === "form") return;
        try { const r = (await NB.capi("POST", "/convert", { yaml: yamlBox.value })).record; const was = NB.dirty; editPage(view, r, { notice: opts.notice, structures }); NB.dirty = was; } catch (e) { NB.fail(e); }
      } }, "Form"),
      h("button", { class: mode === "yaml" ? "on" : "", "aria-pressed": String(mode === "yaml"), onclick: async () => {
        if (mode === "yaml") return;
        try { yamlBox.value = (await NB.capi("POST", "/convert", { record: current() })).yaml; mode = "yaml"; formPane.style.display = "none"; yamlPane.style.display = ""; drawSeg(); } catch (e) { NB.fail(e); }
      } }, "Record file"));
    printSeg.replaceChildren(...Array.from(seg.children, button => button.cloneNode(true)));
  };
  drawSeg();

  const save = async () => {
    if (structureBox.editing()) return NB.toast("Accept or discard the ChemDraw working copy before saving.", true);
    let out;
    try { out = mode === "yaml" ? (await NB.capi("POST", "/convert", { yaml: yamlBox.value })).record : current(); } catch (e) { return NB.fail(e); }
    if (out.result && (!out.result.text || !out.result.basis)) return NB.toast("An isolated result needs both the result and its basis.", true);
    try {
      const dependsOn = structures.length ? ["reaction", "scheme_image", "materials"] : [];
      const r = await NB.saveMerged(id, base, out, view.meta.hash, summary.value.trim(), dependsOn, structures);
      if (r.conflict) {
        editPage(r.conflict.view, r.conflict.merged, { structures, notice: "Experiment " + n + " was saved elsewhere while you were editing. Your edits are shown on top of the current version. Both sides changed: " + r.conflict.both.join(", ") + ". Your version of those is shown; compare with the record file, then save again." });
        NB.dirty = true;
        return;
      }
      clearTimeout(touch.t); NB.draft.clear(key); NB.dirty = false; NB.state.index = null;
      const metricWarning = r.notes.find(note => note.msg.startsWith("primary metric changed"));
      NB.toast(metricWarning ? "Saved. " + metricWarning.msg + "." : r.changed
        ? "Saved" + (r.rebased ? " on top of a change made elsewhere" : "") + ". Changed: " + r.fields.join(", ") + "."
        : "Nothing changed.");
      location.hash = "#/exp/" + id;
    } catch (e) { NB.fail(e); }
  };
  const restore = async () => {
    const dd = opts.draft.data;
    try {
      const mine = dd.yaml !== undefined ? (await NB.capi("POST", "/convert", { yaml: dd.yaml })).record : dd.rec;
      const m = dd.hash === view.meta.hash ? { merged: mine, both: [] } : NB.merge3(dd.base, mine, base);
      editPage(view, m.merged, { structures: dd.structures, notice: dd.hash === view.meta.hash ? "Draft restored." : "Draft restored on top of the current version of the record." + (m.both.length ? " Both changed: " + m.both.join(", ") + "; your version of those is shown." : "") });
      NB.dirty = true;
    } catch (e) { NB.fail(e); }
  };
  NB.setView(
    NB.experimentHead(view, "Record", seg),
    h("div", { class: "row print-only", style: "justify-content:space-between" }, h("h1", {}, "Edit experiment " + n), printSeg),
    h("p", { class: "muted print-only" }, NB.formula(rec.title)),
    opts.notice ? h("div", { class: "banner" }, opts.notice) : null,
    opts.draft ? draftBanner(opts.draft, restore, () => { NB.draft.clear(key); editPage(view); }) : null,
    formPane, yamlPane,
    h("div", { class: "savebar" }, summary, h("button", { class: "primary", onclick: save }, "Save changes"),
      h("button", { class: "light", onclick: () => { clearTimeout(touch.t); NB.draft.clear(key); NB.dirty = false; location.hash = "#/exp/" + id; } }, "Discard changes")));
  if (proposal) { touch(); charBox.focus(); }
  if (NB.openStructureFor?.id === id) {
    const request = NB.openStructureFor; NB.openStructureFor = null;
    const row = rec.materials.find(m => m.id === request.material);
    const opener = row && Array.from(materialGrid.querySelectorAll("[data-edit-material]")).find(el =>
      el.dataset.editMaterial === row.id && (!request.method || el.dataset.editor === request.method));
    structureBox.edit(row && { ...row, smiles: row.smiles || rec.smiles?.[row.id] }, request.method, opener || structureBox.drawButton).catch(NB.fail);
  }
}
NB.routes.push([/^#\/exp\/(EXP-\d+)\/edit$/, async function (id) {
  const view = await NB.capi("GET", "/record/" + id);
  const d = NB.draft.load("edit:" + id);
  editPage(view, null, { draft: d && d.data && (d.data.yaml !== undefined || d.data.structures?.length || !NB.same(d.data.rec, view.record)) ? d : null });
}]);

/* ---------- bench card: one sheet, what you see is what prints */
NB.steps = function (paras) {      // sentences as steps; the record keeps its prose
  const abbr = /(?:\b(?:sat|aq|conc|ca|approx|equiv|eq|vs|cf|Fig|Exp|no|temp|e\.g|i\.e)\.)$/i, out = [];
  for (const p of paras || []) {
    let cur = "";
    for (const part of String(p).split(/(?<=\.)\s+(?=[A-Z(])/)) {
      cur = cur ? cur + " " + part : part;
      if (!abbr.test(cur)) { out.push(cur); cur = ""; }
    }
    if (cur) out.push(cur);
  }
  return out;
};
const cardSections = { scheme: "Scheme", charges: "Charges", conditions: "Conditions", procedure: "Procedure", entries: "Entry fields" };
const chargeOptions = { mw: "MW", mmol: "mmol", equiv: "equiv", note: "Note", locations: "Kept in" };
const printHeight = 955;   // shared one-page budget for Letter and A4
const pixelsPerMm = 96 / 25.4;
const clipHeight = 12 * pixelsPerMm;
// The overlapping middle thirds on Letter and A4, relative to the 10 mm top margin.
const clipTop = (297 / 3 - 10) * pixelsPerMm;
const clipBottom = (279.4 * 2 / 3 - 10) * pixelsPerMm - clipHeight;
const clipTarget = ((297 + 279.4) / 4 - 10) * pixelsPerMm - clipHeight / 2;

function cardOrder(order) {
  const defaults = Object.keys(cardSections);
  return [...new Set([...(Array.isArray(order) ? order : []), ...defaults])].filter(key => defaults.includes(key));
}

function moveCardSection(order, shown, key, change) {
  const neighbor = shown[shown.indexOf(key) + change];
  if (!neighbor) return order;
  const moved = order.slice(), a = moved.indexOf(key), b = moved.indexOf(neighbor);
  [moved[a], moved[b]] = [moved[b], moved[a]];
  return moved;
}

function printedPrompts(prompts, hidden) {
  return prompts.filter(prompt => !hidden.includes(prompt.id));
}

function clipPosition(boundaries) {
  const candidates = boundaries.filter(y => y <= clipBottom);
  if (!candidates.length) return null;
  const natural = candidates.filter(y => y >= clipTop);
  const nearest = natural.length
    ? natural.reduce((a, b) => Math.abs(a - clipTarget) <= Math.abs(b - clipTarget) ? a : b)
    : Math.max(...candidates);
  return { index: boundaries.indexOf(nearest), gap: Math.max(0, clipTop - nearest) };
}

function placeClipBand(sheet) {
  const band = sheet.querySelector(".clip-band");
  band.hidden = true;
  if (sheet.dataset.clip !== "on" || !sheet.isConnected) return true;
  const top = sheet.getBoundingClientRect().top;
  const sections = Array.from(sheet.querySelectorAll(".sheet-section"));
  const pos = clipPosition(sections.map(section => section.getBoundingClientRect().top - top));
  if (!pos) return false;
  sections[pos.index].before(band);
  band.style.marginTop = pos.gap + "px";
  band.hidden = false;
  return true;
}

function growSheetFields(sheet) {
  sheet.querySelectorAll("textarea.fill").forEach(t => { t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; });
}

NB.fitSheet = function (sheet) {
  const img = sheet.querySelector(".scheme img");
  const aspect = img && img.naturalWidth ? img.naturalHeight / img.naturalWidth : 0.3;
  let withBand = true, bandPlaced = true;
  const fits = () => {
    growSheetFields(sheet);
    if (withBand) bandPlaced = placeClipBand(sheet);
    return (!withBand || bandPlaced) && sheet.getBoundingClientRect().height <= printHeight && sheet.scrollWidth <= sheet.clientWidth;
  };
  const imageHeight = height => { if (img) img.style.maxHeight = height + "px"; };
  const fit = () => {
    for (let pct = 100; pct >= 50; pct -= 2) {
      sheet.style.fontSize = (12.5 * pct / 100).toFixed(2) + "px";
      imageHeight((aspect > 0.45 ? 14 : 9) * 12.5 * pct / 100);
      if (fits()) break;
    }
    if (!img) return fits();
    // Give the scheme the space remaining after the table, text, margins and band.
    imageHeight(0);
    if (!fits()) return false;
    let low = 0, high = printHeight;
    while (high - low > 1) {
      const mid = (low + high) / 2;
      imageHeight(mid);
      if (fits()) low = mid; else high = mid;
    }
    imageHeight(low);
    return fits();
  };
  let onePage = fit();
  if (!onePage && !bandPlaced) {
    // An advisory or header spanning the middle of the page can leave no boundary.
    withBand = false;
    onePage = fit();
  }
  return { onePage, bandPlaced };
};

// Fit the printed prompts and entries with their display typography. Keep the live
// controls (including listeners, selection and raw text) for the return to editing.
const liveBenchFields = new WeakMap();
function prepareSheet(sheet) {
  for (const field of sheet.querySelectorAll("textarea.fill")) {
    const value = NB.chemicalPlain(field.value), placeholder = NB.chemicalPlain(field.placeholder);
    if (value === field.value && placeholder === field.placeholder) continue;
    const printed = field.cloneNode(false);
    printed.value = value; printed.placeholder = placeholder;
    liveBenchFields.set(printed, field);
    field.replaceWith(printed);
  }
  document.body.classList.add("printing");
  const { onePage, bandPlaced } = NB.fitSheet(sheet);
  if (!onePage) NB.toast("This card is too long for one page even at the smallest type. It will print on two pages; shorten the procedure or the bench fields.", true);
  else if (!bandPlaced) NB.toast("The clip band needs a section boundary in the middle third of the page.", true);
}

window.addEventListener("beforeprint", () => {
  const sheet = document.querySelector("#view .sheet");
  if (sheet && !document.body.classList.contains("printing")) prepareSheet(sheet);
});
window.addEventListener("afterprint", () => {
  document.body.classList.remove("printing");
  const sheet = document.querySelector("#view .sheet");
  if (!sheet) return;
  for (const printed of sheet.querySelectorAll("textarea.fill")) {
    const live = liveBenchFields.get(printed);
    if (live) printed.replaceWith(live);
  }
  sheet.style.fontSize = "";
  const img = sheet.querySelector(".scheme img");
  if (img) img.style.maxHeight = "";
  growSheetFields(sheet);
  placeClipBand(sheet);
});
window.addEventListener("resize", () => {
  const sheet = document.querySelector("#view .sheet");
  if (sheet && !document.body.classList.contains("printing")) {
    growSheetFields(sheet);
    placeClipBand(sheet);
  }
});

function cardLayout(sheet, sections, advisory, fixed, prompts, defaultHidden, id) {
  const key = "nb-card-layout:" + JSON.stringify([NB.state.root, NB.state.case]);
  let saved;
  try { saved = JSON.parse(localStorage.getItem(key)); } catch (err) { /* browser storage is optional */ }
  const defaults = () => ({ order: cardOrder(), omitted: [], clip: false, hiddenPrompts: {} });
  let prefs = defaults();
  // Copy only current settings so retired keys disappear on the next save.
  for (const k of Object.keys(prefs)) if (saved && typeof saved === "object" && k in saved) prefs[k] = saved[k];
  prefs.order = cardOrder(prefs.order);
  if (!Array.isArray(prefs.omitted)) prefs.omitted = [];
  if (!prefs.hiddenPrompts || typeof prefs.hiddenPrompts !== "object") prefs.hiddenPrompts = {};
  const hidden = () => Array.isArray(prefs.hiddenPrompts[id]) ? prefs.hiddenPrompts[id] : defaultHidden;
  const included = key => !prefs.omitted.includes(key);
  const shown = () => prefs.order.filter(name => sections[name] && included(name));
  const persist = () => {
    try { localStorage.setItem(key, JSON.stringify(prefs)); } catch (err) { /* browser storage is optional */ }
  };
  const apply = () => {
    sheet.dataset.clip = prefs.clip ? "on" : "off";
    const chosen = printedPrompts(prompts, hidden());
    NB.put(advisory, fixed, chosen.map(p => h("li", { class: p.level }, NB.formula(p.text))));
    advisory.hidden = !advisory.childElementCount;
    for (const section of sheet.querySelectorAll(".sheet-section")) section.remove();
    for (const name of shown()) sheet.append(name === "charges" ? sections.charges(included) : sections[name]);
    if (sheet.isConnected) growSheetFields(sheet);
    placeClipBand(sheet);
  };
  const update = () => { persist(); apply(); };
  const order = h("ol", { class: "card-order" });
  const columns = h("div", { class: "row" });
  const choice = (name, label) => h("label", { class: "row" },
    h("input", { type: "checkbox", checked: included(name), onchange: e => {
      if (e.target.checked) prefs.omitted = prefs.omitted.filter(key => key !== name);
      else prefs.omitted.push(name);
      update(); drawOrder(name);
    } }), label);
  const drawOrder = (focus, direction) => {
    const names = shown();
    let control;
    NB.put(order, prefs.order.map(name => {
      const idx = names.indexOf(name);
      const arrows = [-1, 1].map(change => h("button", { type: "button", class: "quiet", disabled: idx < 0 || !names[idx + change],
        "aria-label": "Move " + cardSections[name].toLowerCase() + (change < 0 ? " up" : " down"), onclick: () => {
          prefs.order = moveCardSection(prefs.order, names, name, change);
          update(); drawOrder(name, change);
        } }, change < 0 ? "↑" : "↓"));
      const label = choice(name, cardSections[name]);
      if (focus === name) {
        const first = direction < 0 ? 0 : 1;
        control = direction ? (arrows[first].disabled ? arrows[1 - first] : arrows[first]) : label.firstChild;
      }
      return h("li", {}, label, ...arrows);
    }));
    NB.put(columns, Object.entries(chargeOptions).map(([name, caption]) => {
      const label = choice(name, caption);
      if (focus === name) control = label.firstChild;
      return label;
    }));
    if (control) control.focus();
  };
  const clip = h("input", { type: "checkbox", checked: !!prefs.clip, onchange: e => { prefs.clip = e.target.checked; update(); } });
  const setHidden = ids => { prefs.hiddenPrompts[id] = [...ids]; update(); drawPrompts(); };
  const toggles = prompts.map(p => h("input", { type: "checkbox", onchange: e => {
    const ids = new Set(hidden());
    if (e.target.checked) ids.delete(p.id); else ids.add(p.id);
    setHidden(ids);
  } }));
  const all = h("button", { type: "button", class: "quiet", onclick: () => {
    const ids = new Set(hidden());
    const turnOff = printedPrompts(prompts, hidden()).length > 0;
    for (const p of prompts) {
      if (turnOff) ids.add(p.id); else ids.delete(p.id);
    }
    setHidden(ids);
  } });
  const drawPrompts = () => {
    const ids = hidden();
    toggles.forEach((toggle, i) => { toggle.checked = !ids.includes(prompts[i].id); });
    all.textContent = printedPrompts(prompts, ids).length ? "Hide all prompts" : "Show all prompts";
  };
  const reset = h("button", { type: "button", class: "quiet", onclick: () => {
    prefs = defaults();
    clip.checked = prefs.clip;
    try { localStorage.removeItem(key); } catch (err) { /* browser storage is optional */ }
    apply(); drawOrder(); drawPrompts();
  } }, "Reset layout");
  apply(); drawOrder(); drawPrompts();
  return h("details", { class: "card-layout noprint" }, h("summary", {}, "Card contents"),
    h("div", { class: "row" }, h("label", { class: "row" }, clip, "Clip band"), reset),
    h("h3", {}, "Sections"), order, h("h3", {}, "Charges"), columns,
    prompts.length ? [h("h3", {}, "Hazard prompts"), all, prompts.map((p, i) => h("label", { class: "card-prompt" }, toggles[i], h("span", {}, NB.formula(p.text))))] : null);
}

function benchPage(view, start, notice) {
  const base = view.record, id = base.id, d = view.derived, key = "bench:" + id, nn = String(d.n).padStart(2, "0");
  const rec = JSON.parse(JSON.stringify(base));
  rec.entries = Object.assign({}, start || base.entries);
  const ef = NB.entryFields(rec);
  const draft = start ? null : NB.draft.load(key);
  const touch = () => { NB.dirty = true; clearTimeout(touch.t); touch.t = setTimeout(() => NB.draft.save(key, rec.entries), 400); };
  const cell = (tag, label, hint) => {
    const el = h("textarea", { class: "fill", rows: 1, "aria-label": label, "data-tag": tag, placeholder: hint || "" });
    el.value = rec.entries[tag] || "";
    el.addEventListener("input", () => { if (el.value.trim()) rec.entries[tag] = el.value; else delete rec.entries[tag]; el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; placeClipBand(sheet); touch(); });
    return el;
  };
  const blocking = (rec.flags || []).filter(f => f.tier === "blocking");
  const flagText = blocking.map(f => f.text).join(" ").toLowerCase();
  const defaultHidden = d.hazards.filter(p => String(p.id).startsWith("above-bp-") && /boil/.test(flagText)).map(p => p.id);   // already said by a blocking flag
  const vessels = rec.vessels && rec.vessels.length ? rec.vessels : [null];
  const actual = ef.groups.some(g => g.kind === "actual"), others = ef.groups.filter(g => g.kind !== "actual");
  const tickKey = "nb-ticks:" + NB.state.case + ":" + id;
  let ticks = {};
  try { ticks = JSON.parse(localStorage.getItem(tickKey) || "{}"); } catch (e) { ticks = {}; }
  const steps = NB.steps(rec.procedure);
  const legacy = rec.legacy_id && !/not yet|computational/.test(rec.legacy_id) ? rec.legacy_id : "";
  const advisory = h("ul", { class: "warn" });
  const fixed = blocking.map(f => h("li", { class: "warning" }, h("strong", {}, "Before you start (" + f.id + "). "), NB.formula(f.text)));
  if (rec.safety) fixed.push(h("li", { class: "warning" }, h("strong", {}, "Safety. "), NB.formula(rec.safety)));
  const sheet = h("div", { class: "sheet" },
    h("div", { class: "sheethead" }, h("div", { class: "no" }, h("span", {}, "Bench card"), "Exp " + d.n),
      h("div", {}, h("div", { class: "title" }, NB.formula(rec.title)), h("div", { class: "meta" }, [legacy, rec.started, rec.researcher].filter(Boolean).join(", ")))),
    advisory, h("div", { class: "clip-band", hidden: true, "aria-hidden": "true" }));
  const section = (...kids) => h("div", { class: "sheet-section" }, ...kids);
  const sections = {
    scheme: (d.scheme || d.scheme_preview) ? section(NB.recordScheme(view, null, () => placeClipBand(sheet))) : null,
    charges: rec.materials?.length ? include => section(h("h2", {}, "Charges"), h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "ID"), h("th", {}, "Material"), include("mw") && h("th", { class: "num" }, "MW"),
        h("th", {}, "Planned"), include("mmol") && h("th", { class: "num" }, "mmol"), include("equiv") && h("th", { class: "num" }, "equiv"),
        vessels.map(v => h("th", {}, "Actual" + (v ? " " + v : ""))), include("note") && h("th", {}, "Note"))),
      h("tbody", {}, rec.materials.map(m => h("tr", {}, h("td", {}, h("strong", {}, m.id)),
        h("td", {}, NB.formula(m.name || m.formula), materialLocation(m, include("locations") && d.locations?.[m.id], 2, "hint")),
        include("mw") && h("td", { class: "num" }, m.mw || ""), h("td", {}, m.amount || ""),
        include("mmol") && h("td", { class: "num" }, NB.fmtNum(m.mmol, 3, 4)), include("equiv") && h("td", { class: "num" }, NB.fmtNum(m.equiv, 2, 3)),
        vessels.map(v => h("td", { class: "act" }, String(m.id).startsWith("P") ? "–" : actual ? cell("exp" + nn + "_actual_" + (v ? v + "_" : "") + m.id, "Actual charge of " + m.id + " " + (m.name || m.formula || "") + (v ? ", vessel " + v : "")) : "")),
        include("note") && h("td", { class: "hint" }, NB.formula(m.note))))))) : null,
    conditions: rec.conditions ? section(h("p", { class: "cond" }, h("strong", {}, "Conditions. "), NB.formula(rec.conditions))) : null,
    procedure: steps.length ? section(h("h2", {}, "Procedure"), h("div", { class: "steps" }, steps.map((t, i) => h("label", { class: "step" },
      h("input", { type: "checkbox", checked: !!ticks[i], onchange: e => { ticks[i] = e.target.checked; try { localStorage.setItem(tickKey, JSON.stringify(ticks)); } catch (err) { /* ticks are a convenience */ } } }), h("span", {}, NB.formula(t)))))) : null,
    entries: section((rec.notes || []).map(t => h("p", { class: "hint" }, NB.formula(t))),
      others.length ? others.map(g => [h("h2", {}, g.title), h("div", { class: "fields" }, g.fields.map(f => h("label", {}, h("span", { class: "lab" }, NB.formula(f.label)), cell(f.tag, f.label, f.hint))))])
        : [h("h2", {}, "Observations"), h("div", { class: "blank" }), h("div", { class: "blank" }), h("div", { class: "blank" })]),
  };
  const layout = cardLayout(sheet, sections, advisory, fixed, d.hazards, defaultHidden, id);
  const save = async () => {
    const out = JSON.parse(JSON.stringify(base));
    out.entries = Object.assign({}, rec.entries);
    if (!Object.keys(out.entries).length) delete out.entries;
    try {
      const r = await NB.saveMerged(id, base, out, view.meta.hash, "bench entries");
      if (r.conflict) { benchPage(r.conflict.view, r.conflict.merged.entries || {}, "This experiment was saved elsewhere meanwhile. Both changed: " + r.conflict.both.join(", ") + ". Your text is shown; save again to keep it."); NB.dirty = true; return; }
      clearTimeout(touch.t); NB.draft.clear(key); NB.dirty = false; NB.state.index = null;
      NB.toast(r.changed ? "Entries saved to the record" + (r.rebased ? ", on top of a change made elsewhere." : ".") : "Nothing changed.");
      benchPage(await NB.capi("GET", "/record/" + id));
    } catch (e) { NB.fail(e); }
  };
  const print = () => {
    prepareSheet(sheet);
    window.print();
  };
  NB.setView(
    NB.experimentHead(view, "Bench card", [
      h("button", { class: "primary", onclick: save }, "Save entries"),
      h("button", { onclick: print }, "Print on one page"),
      NB.state.schedule_and_supplies ? NB.wasteEntryControl(base) : null]),
    notice ? h("div", { class: "banner noprint" }, notice) : null,
    draft && draft.data && !NB.same(draft.data, base.entries || {}) ? draftBanner(draft, () => { benchPage(view, draft.data, "Draft restored. Save to put it in the record."); NB.dirty = true; }, () => { NB.draft.clear(key); benchPage(view); }) : null,
    layout, sheet,
    h("p", { class: "muted small noprint", style: "margin-top:10px" }, "Entries go into the record (" + d.record_path + ") when you save and into the Word notebook at the next rebuild. Tick marks stay on this computer only. Printing scales the card to one page."));
  growSheetFields(sheet);
  placeClipBand(sheet);
}
NB.routes.push([/^#\/exp\/(EXP-\d+)\/bench$/, async function (id) { benchPage(await NB.capi("GET", "/record/" + id)); }]);
})();
