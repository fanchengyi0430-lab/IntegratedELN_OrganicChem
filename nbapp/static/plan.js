/* Plan a new experiment: stoichiometry calculator, inventory lookup, hazard prompts, saved as a planned record. */
"use strict";
(function () {
const h = NB.h;

/* ---------- amounts */
const sig = (x, n) => Number(x.toPrecision(n));
NB.fmtMass = mg => mg >= 1000 ? (mg / 1000).toFixed(3) + " g" : mg >= 1 ? mg.toFixed(1) + " mg" : mg.toFixed(2) + " mg";
NB.fmtVol = uL => uL >= 1000 ? (uL / 1000).toFixed(2) + " mL" : uL.toFixed(1) + " µL";
NB.fmtSolvent = mL => mL >= 10 ? mL.toFixed(1) + " mL" : mL >= 1 ? mL.toFixed(2) + " mL" : (mL * 1000).toFixed(1) + " µL";
NB.parseAmount = function (text) {           // "44.1 mg, 31.5 µL" -> {mg, uL}
  const out = { mg: null, uL: null };
  for (const m of String(text || "").matchAll(/([\d.]+)\s*(mg|g|µL|uL|μL|mL)\b/g)) {
    const v = parseFloat(m[1]);
    if (m[2] === "mg" && out.mg === null) out.mg = v;
    else if (m[2] === "g" && out.mg === null) out.mg = v * 1000;
    else if (m[2] === "mL" && out.uL === null) out.uL = v * 1000;
    else if (/L$/.test(m[2]) && m[2] !== "mL" && out.uL === null) out.uL = v;
  }
  return out;
};

function compute(row, scale) {
  const out = { mmol: null, mg: null, uL: null, amount: "", mL: null };
  if (!(scale > 0)) return out;
  if (row.role === "S") {
    if (row.conc > 0) { out.mL = scale / row.conc; out.amount = NB.fmtSolvent(out.mL); }
    return out;
  }
  const factor = row.role === "P" ? (row.factor > 0 ? row.factor : 1) : row.equiv;
  if (!(factor > 0)) return out;
  out.mmol = sig(scale * factor, 4);
  if (row.mw > 0) {
    const assay = row.role === "R" && row.assay > 0 && row.assay < 100 ? row.assay / 100 : 1;
    out.mg = scale * factor * row.mw / assay;
    out.amount = NB.fmtMass(out.mg);
    if (row.role === "P") out.amount += " theoretical";
    else if (row.density > 0) { out.uL = out.mg / row.density; out.amount += ", " + NB.fmtVol(out.uL); }
  }
  return out;
}

NB.plannedCharge = compute;

function stockNote(row, need) {     // "enough" or "short" when the export's units can be compared with the calculated amount
  const b = row.bottle;
  if (!b || typeof b === "string" || !b.remaining) return "";
  const m = String(b.remaining).match(/([\d.]+)\s*([a-zµ]+)/i);
  if (!m) return "";
  const v = parseFloat(m[1]), u = m[2].toLowerCase(), mg = { mg: 1, g: 1e3, kg: 1e6 }[u], uL = { ml: 1e3, l: 1e6 }[u];
  const have = mg ? v * mg : uL ? v * uL : null, want = mg ? need.mg : uL ? (need.uL || (need.mL ? need.mL * 1000 : null)) : null;
  if (have === null || !want) return "export lists " + b.remaining + " left";
  return "export lists " + b.remaining + " left: " + (have >= want ? "enough for this plan" : "SHORT of what this plan needs");
}
function rowsFromRecord(rec) {
  const mats = rec.materials || [];
  const lim = mats.find(m => String(m.id).startsWith("R") && m.equiv === 1 && m.mmol > 0) || mats.find(m => m.mmol > 0);
  const scale = lim ? lim.mmol / (lim.equiv || 1) : null;
  const rows = mats.map(m => {
    const role = ["A", "P", "S"].includes(String(m.id)[0]) ? String(m.id)[0] : "R";
    const row = { role, name: m.name || "", formula: m.formula || "", mw: m.mw || null, note: m.note || "", bottle: m.bottle || "" };
    for (const key of ["name_basis", "check_name", "cas", "smiles", "inchikey", "pubchem_cid", "density", "density_basis"]) if (key in m) row[key] = m[key];
    if (!row.smiles && rec.smiles?.[m.id]) row.smiles = rec.smiles[m.id];
    const amt = NB.parseAmount(m.amount);
    if (role === "R" || role === "A") {
      row.equiv = m.equiv !== undefined ? m.equiv : (scale && m.mmol ? sig(m.mmol / scale, 3) : null);
      if (amt.mg && amt.uL) { row.density = sig(amt.mg / amt.uL, 3); row.derived = true; }
      const dn = String(m.note || "").match(/([\d.]+)\s*g\/mL/);
      if (dn) { row.density = parseFloat(dn[1]); row.derived = false; row.note = row.note.replace(dn[0], "").replace(/^[;,\s]+|[;,\s]+$/g, ""); }
      const wt = row.name.match(/(\d+(?:\.\d+)?)\s*wt\s*%/i), wn = row.note.match(/(\d+(?:\.\d+)?)\s*wt\s*%/i);
      if (typeof m.density === "number") { row.density = m.density; row.derived = false; }
      if (typeof m.assay === "number") row.assay = m.assay;
      else if (wt) row.assay = parseFloat(wt[1]);
      else if (wn) row.assay = parseFloat(wn[1]);
      else if (amt.mg && m.mmol && m.mw && /%/.test(row.name + " " + row.note)) { const a = m.mmol * m.mw / amt.mg * 100; if (a < 97) row.assay = sig(a, 3); }
      if (wn) row.note = row.note.replace(wn[0], "").replace(/^[;,\s]+|[;,\s]+$/g, "");   // written back from the assay column on save
    } else if (role === "S") {
      const mL = amt.uL ? amt.uL / 1000 : null;
      row.conc = scale && mL ? sig(scale / mL, 3) : null;
      row.note = row.note.replace(/[\d.]+\s*M\b/, "").replace(/^[;,\s]+|[;,\s]+$/g, "");
    } else {
      row.factor = scale && m.mmol ? sig(m.mmol / scale, 3) : 1;
    }
    return row;
  });
  return { rows, scale };
}

const BENCH = {
  synthesis: [["Reagent lots", "Supplier, lot and purity of each reagent"], ["Actual start and end", "Date and time"],
    ["Additions and temperature", "Order and times; bath temperature; colour changes"], ["Reaction monitoring", "TLC eluent and Rf values; time"],
    ["Workup", "Quench and wash volumes; drying agent"], ["Purification", "Silica, eluent or gradient, product fractions"], ["Deviations from plan", "Anything that differed"]],
  screening: [["Materials and lots", "Batches and lots of substrate, reagents and standard"], ["Addition order and setup", "Order, vial and closure, atmosphere, stirring"],
    ["Heating", "Block or bath temperature; actual start and stop"], ["Sampling for NMR", "Aliquot or whole sample, workup, NMR solvent"], ["Deviations from plan", "Anything that differed"]],
};

NB.routes.push([/^#\/new(?:\/(EXP-\d+))?$/, async function (fromId) {
  const idx = NB.state.index || await NB.loadIndex();
  const nextN = NB.expNo(idx.next_id);
  const st = { title: "", type: "synthesis", question: "", metric_kind: "", metric: "", conditions: "", procedure: "", basis: "Planned.", safety: "", legacy: "",
    scale: 1, rows: [{ role: "R", name: "", formula: "", mw: null, equiv: 1 }, { role: "S", name: "", conc: 0.1 }, { role: "P", name: "", formula: "", mw: null, factor: 1 }],
    runs: [], flags: [], smiles: null, refs: null };
  let source = null, sourceScale = null, sourceView;
  const key = "plan:" + (fromId || "blank");
  if (fromId) {
    try {
      sourceView = await NB.capi("GET", "/record/" + fromId);
      source = sourceView.record;
      const got = rowsFromRecord(source);
      sourceScale = got.scale;
      Object.assign(st, { title: source.title, type: NB.isScreening(source.type) ? source.type : "synthesis",
        metric_kind: source.metric_kind || "", metric: source.metric || "", conditions: source.conditions || "",
        procedure: (source.procedure || []).join("\n\n"), basis: "Planned; adapted from Exp " + NB.expNo(fromId) + ".", safety: source.safety || "",
        rows: got.rows.length ? got.rows : st.rows, scale: got.scale || 1, smiles: source.smiles || null, refs: (source.sources || {}).refs || null,
        runs: (source.runs || []).map(r => ({ run: String(r.run), variable: r.variable || "" })) });
    } catch (e) { if (e instanceof NB.StaleRead) throw e; NB.fail(e); }
  }

  const draft = NB.draft.load(key);
  if (NB.state.planRestore) { Object.assign(st, NB.state.planRestore); NB.state.planRestore = null; }
  const touch = () => { NB.dirty = true; clearTimeout(touch.t); touch.t = setTimeout(() => NB.draft.save(key, st), 400); };

  /* --- stoichiometry table */
  const tbody = h("tbody", {});
  const hazardBox = h("div", {}), proseBox = h("div", {});
  const checkBox = h("div", {});
  const invBox = h("div", {});
  const lookup = NB.referencePanel((row, values) => {
    if (!st.rows.includes(row)) return false;
    NB.applyReference(row, values);
    if ("formula" in values) row.mwTyped = false;
    if ("density" in values) row.derived = false;
    draw();
    touch();
  });
  const cells = [];
  const ids = () => { const c = { R: 0, S: 0, P: 0, A: 0 }; return st.rows.map(r => r.role + (++c[r.role])); };
  let hazardTimer;
  const refresh = () => {
    const labels = ids();
    st.rows.forEach((row, i) => {
      const c = compute(row, st.scale), cell = cells[i];
      if (!cell) return;
      cell.id.textContent = labels[i];
      cell.mmol.textContent = c.mmol === null ? "" : (Math.round(c.mmol * 1000) / 1000 === c.mmol ? c.mmol.toFixed(3) : String(c.mmol));
      cell.amount.textContent = c.amount || (row.role === "S" ? "set a concentration" : row.mw ? "" : "needs MW");
      cell.amount.className = c.amount ? "" : "muted small";
      const stock = stockNote(row, c);
      NB.put(cell.stock, NB.formula(row.bottle ? "Bottle: " + NB.bottleText(row.bottle) + (stock ? ". " + stock : "") : ""));
      cell.stock.style.color = /SHORT/.test(stock) ? "var(--blocking)" : "";
      const calc = NB.mw(row.formula);
      cell.mwHint.textContent = row.formula && !calc ? "formula not readable" : calc && row.mw && Math.abs(calc - row.mw) > 0.06 ? "formula gives " + calc.toFixed(3) : "";
    });
    const notes = [];
    if (!(st.scale > 0)) notes.push("Set the scale (mmol of the limiting reagent).");
    if (!st.rows.some(r => r.role === "R" && r.equiv === 1)) notes.push("No reagent has 1 equiv. The scale refers to the limiting reagent.");
    st.rows.forEach((r, i) => { if (r.role !== "S" && r.name && !r.mw) notes.push(ids()[i] + ": no MW, so no mass is calculated."); });
    NB.put(checkBox, ...notes.map(t => h("div", { class: "note caution small" }, t)));
    const named = source ? [...new Set(st.procedure.match(/\b\d+(?:\.\d+)?\s?(?:mg|g|kg|mL|µL|uL|L|mmol)\b/g) || [])] : [];
    NB.put(proseBox, named.length && sourceScale && Math.abs(st.scale - sourceScale) > 1e-9 ? h("div", { class: "note caution small" },
      "The copied procedure names amounts written for " + sourceScale + " mmol (" + named.join(", ") + "). They are not rescaled: edit them for " + st.scale + " mmol.") : null);
    clearTimeout(hazardTimer);
    hazardTimer = setTimeout(async () => {
      try {
        const res = await NB.api("POST", "/api/hazards", { materials: st.rows.filter(r => r.name).map(r => ({ name: r.name })), text: st.conditions + " " + st.procedure });
        NB.put(hazardBox, ...(res.prompts.length ? res.prompts.map(p => h("div", { class: "note " + p.level }, NB.formula(p.text))) : [h("p", { class: "empty" }, "No prompt matches the materials and temperatures entered so far.")]));
      } catch (e) { /* prompts are optional */ }
    }, 500);
  };
  const num = (row, key, label, width) => {
    const el = h("input", { type: "text", inputmode: "decimal", "aria-label": label, style: "width:" + (width || 70) + "px" });
    el.value = row[key] === null || row[key] === undefined ? "" : row[key];
    el.addEventListener("input", () => {
      const v = parseFloat(el.value); row[key] = isNaN(v) ? null : v;
      if (key === "density") delete row.density_basis;
      refresh();
    });
    return el;
  };
  const txt = (row, key, label, width, onchange) => {
    const el = h("input", { type: "text", "aria-label": label, style: "width:100%;min-width:" + (width || 90) + "px" });
    el.value = row[key] || "";
    el.addEventListener("input", () => { row[key] = el.value; if (onchange) onchange(el); refresh(); });
    return el;
  };
  const draw = () => {
    cells.length = 0;
    NB.put(tbody, ...st.rows.map((row, i) => {
      const cell = { id: h("strong", {}), mmol: h("span", {}), amount: h("span", {}), stock: h("div", { class: "muted small" }), mwHint: h("div", { class: "small", style: "color:var(--needed)" }) };
      cells.push(cell);
      const mwIn = num(row, "mw", "Molecular weight", 78);
      const role = h("select", { "aria-label": "Role", style: "min-width:96px", onchange: e => { row.role = e.target.value; if (row.role === "R" && !row.equiv) row.equiv = 1; if (row.role === "P" && !row.factor) row.factor = 1; if (row.role === "S" && !row.conc) row.conc = 0.1; draw(); } },
        [["R", "Reagent"], ["A", "Agent"], ["S", "Solvent"], ["P", "Product"]].map(([v, l]) => h("option", { value: v, selected: row.role === v }, l)));
      const ratio = ["R", "A"].includes(row.role) ? num(row, "equiv", "Equivalents", 58) : row.role === "P" ? num(row, "factor", "Moles of product per mole of limiting reagent", 58) : num(row, "conc", "Concentration in mol per litre", 58);
      return h("tr", {},
        h("td", {}, role), h("td", {}, cell.id),
        h("td", {}, txt(row, "name", "Material name", 150, el => { row.name_basis = { kind: "entered" }; delete row.check_name; el.parentNode.querySelector("[data-name-check]")?.remove(); }), row.check_name ? h("button", { class: "quiet", "data-name-check": true, onclick: () => { delete row.check_name; draw(); touch(); } }, "Check the name · confirm") : null, !row.name && row.smiles ? NB.formula(row.formula) : null, cell.stock),
        h("td", {}, txt(row, "formula", "Formula", 86, () => { const w = NB.mw(row.formula); if (w && !row.mwTyped) { row.mw = Math.round(w * 1000) / 1000; mwIn.value = row.mw; } }), cell.mwHint),
        h("td", {}, (mwIn.addEventListener("input", () => { row.mwTyped = mwIn.value !== ""; }), mwIn)),
        h("td", { style: "white-space:nowrap" }, ratio, h("span", { class: "muted small" }, row.role === "S" ? " M" : row.role === "P" ? " per mol" : "")),
        h("td", { class: "num" }, cell.mmol), h("td", {}, cell.amount),
        h("td", {}, num(row, "density", "Density in grams per millilitre", 58)),
        h("td", {}, row.role === "R" ? num(row, "assay", "Assay in weight percent", 50) : ""),
        h("td", {}, txt(row, "note", "Note", 76)),
        h("td", { style: "width:1%" },
          lookup.button(row),
          NB.state.structureReason ? null : h("button", { class: "quiet", onclick: () => NB.libraryPicker(invBox, (item, source) => {
            if (row.smiles !== item.smiles) {
              for (const key of ["cas", "pubchem_cid", "assay", "density", "density_basis", "bottle", "mwTyped", "derived"]) delete row[key];
            }
            delete row.sourceIndex;
            if (source) {
              row.sourceIndex = (st.structures ||= []).push(source) - 1;
              row.sourcePosition = source.position;
            }
            delete row.name_basis; delete row.check_name;
            Object.assign(row, item);
            draw(); touch();
          }) }, "From library"),
          NB.hasInventory() && row.role !== "P" ? h("button", { class: "quiet", style: "white-space:nowrap;display:block", onclick: () => findBottle(row) }, "Find bottle") : null,
          h("button", { class: "x", "aria-label": "Remove row", onclick: () => { st.rows.splice(i, 1); draw(); } }, "Remove")));
    }));
    refresh();
  };
  const findBottle = row => {
    const initial = (row.name || "").replace(/\(.*?\)/g, " ").replace(/[,;].*$/, "").trim();
    const close = () => NB.put(invBox);
    const search = NB.inventorySearch(initial, item => {
      if (!row.name) row.name_basis = { kind: "notebook", source: ["Bottle", item.barcode, item.location].filter(Boolean).join(" ") };
      NB.linkBottle(row, item);
      close(); draw(); touch();
      const inputs = Array.from(tbody.rows[st.rows.indexOf(row)].querySelectorAll("input"));
      (inputs.find(input => input.value === "") || inputs[0])?.focus();
    }, close);
    NB.put(invBox, h("div", { class: "pop" }, h("strong", {}, "Inventory"), search.el));
    search.input.focus();
  };

  /* --- scale */
  const scaleIn = h("input", { type: "text", inputmode: "decimal", style: "width:90px", "aria-label": "Scale in millimoles" });
  scaleIn.value = st.scale;
  scaleIn.addEventListener("input", () => { const v = parseFloat(scaleIn.value); st.scale = isNaN(v) ? 0 : v; refresh(); });
  const massIn = h("input", { type: "text", inputmode: "decimal", style: "width:90px", placeholder: "mass", "aria-label": "Mass of the limiting reagent in milligrams" });
  const fromMass = () => {
    const row = st.rows.find(r => r.role === "R" && r.equiv === 1) || st.rows.find(r => r.role === "R");
    const mg = parseFloat(massIn.value);
    if (!row || !row.mw || isNaN(mg)) return NB.toast("Enter the MW of the limiting reagent first, then a mass in mg.", true);
    st.scale = sig(mg * (row.assay > 0 && row.assay < 100 ? row.assay / 100 : 1) / row.mw / (row.equiv || 1), 4);
    scaleIn.value = st.scale; refresh();
  };

  /* --- text fields */
  const bind = (key, attrs) => { const el = h(attrs && attrs.rows ? "textarea" : "input", Object.assign({ type: attrs && attrs.rows ? null : "text" }, attrs || {})); el.value = st[key]; el.addEventListener("input", () => { st[key] = el.value; if (key === "conditions" || key === "procedure") refresh(); }); return el; };
  const f = (label, el) => h("label", { class: "f" }, h("span", {}, label), el);
  const showScreening = () => {
    const display = NB.isScreening(st.type) ? "" : "none";
    metricFields.style.display = display;
    runsField.style.display = display;
  };
  const typeSel = h("select", { onchange: e => { st.type = e.target.value; showScreening(); } },
    ["synthesis", "screening", "screening (isolation)"].map(t => h("option", { value: t, selected: st.type === t }, t)));
  const metricFields = h("div", { class: "cols c2" },
    f("Primary metric", NB.metricKindSelect(st.metric_kind, kind => { st.metric_kind = kind; })),
    f("Metric details", bind("metric", { placeholder: "How will you measure it?" })));

  /* --- runs (screening) */
  const runBody = h("div", {});
  const drawRuns = () => NB.put(runBody, ...st.runs.map((r, i) => h("div", { class: "row", style: "margin-bottom:6px" },
    (() => { const el = h("input", { type: "text", style: "width:70px", "aria-label": "Run label" }); el.value = r.run; el.addEventListener("input", () => { r.run = el.value; }); return el; })(),
    (() => { const el = h("input", { type: "text", style: "flex:1 1 300px", placeholder: "What differs in this run (solvent, loading, temperature…)", "aria-label": "Run conditions" }); el.value = r.variable; el.addEventListener("input", () => { r.variable = el.value; }); return el; })(),
    h("button", { class: "x", onclick: () => { st.runs.splice(i, 1); drawRuns(); } }, "Remove"))),
    h("button", { class: "quiet", onclick: () => { st.runs.push({ run: String(st.runs.length + 1), variable: "" }); drawRuns(); } }, "Add a run"));
  drawRuns();
  const runsField = h("fieldset", {}, h("legend", {}, "Runs"),
    h("p", { class: "muted small" }, "The materials table gives the charges per run. Use " + idx.nmr_hints.run.replace("EXP-NEW", idx.next_id) + " so spectra link to runs."), runBody);
  showScreening();

  /* --- flags */
  const flagBody = h("div", {});
  const drawFlags = () => NB.put(flagBody, ...st.flags.map((fl, i) => h("div", { class: "row", style: "margin-bottom:6px" },
    h("select", { "aria-label": "Tier", onchange: e => { fl.tier = e.target.value; } }, ["blocking", "needed", "nice"].map(t => h("option", { value: t, selected: fl.tier === t }, t))),
    (() => { const el = h("input", { type: "text", style: "flex:1 1 300px", placeholder: "Describe what needs to be checked before this step", "aria-label": "Flag text" }); el.value = fl.text; el.addEventListener("input", () => { fl.text = el.value; }); return el; })(),
    h("button", { class: "x", onclick: () => { st.flags.splice(i, 1); drawFlags(); } }, "Remove"))),
    st.flags.length < 3 ? h("button", { class: "quiet", onclick: () => { st.flags.push({ tier: "blocking", text: "" }); drawFlags(); } }, "Add a flag") : null);
  drawFlags();

  /* --- save */
  const save = async ev => {
    if (structureBox.editing()) return NB.toast("Accept or discard the ChemDraw working copy before saving.", true);
    if (!st.title.trim()) return NB.toast("Give the experiment a title.", true);
    if (!st.question.trim()) return NB.toast("State the question this experiment answers.", true);
    const screening = NB.isScreening(st.type);
    if (screening && (!st.metric_kind || !st.metric.trim())) return NB.toast("Choose a primary metric and describe how you will measure it.", true);
    const named = st.rows.filter(r => r.name.trim() || (r.smiles && r.formula));
    if (!named.some(r => r.role === "R")) return NB.toast("Add at least one reagent with a name or structure.", true);
    if (!(st.scale > 0)) return NB.toast("Set the scale (mmol of the limiting reagent).", true);
    const c = { R: 0, S: 0, P: 0, A: 0 };
    const materials = named.map(r => {
      const id = r.role + (++c[r.role]), k = compute(r, st.scale), m = { id, name: r.name.trim() };
      if (r.check_name) m.check_name = true;
      if (r.formula) m.formula = r.formula.trim();
      if (r.mw) m.mw = r.mw;
      for (const key of ["name_basis", "cas", "smiles", "inchikey", "pubchem_cid", "density_basis"]) if (r[key]) m[key] = r[key];
      if (k.amount) m.amount = k.amount;
      if (k.mmol !== null) m.mmol = k.mmol;
      if (["R", "A"].includes(r.role) && r.equiv) m.equiv = r.equiv;
      const notes = [];
      if (r.role === "R" && r.density) notes.push(r.density + " g/mL");
      if (r.role === "R" && r.assay > 0 && r.assay < 100 && !/%/.test(r.name)) notes.push(r.assay + " wt%");
      if (r.role === "S" && r.conc) notes.push(r.conc.toFixed(3) + " M");
      if (r.role === "P" && r.factor && r.factor !== 1 && !(r.note && r.note.trim())) notes.push(r.factor + " mol per mol of limiting reagent");
      if (r.note && r.note.trim()) notes.push(r.note.trim());
      if (notes.length) m.note = notes.join("; ");
      if (r.density > 0) m.density = r.density;
      if (r.assay > 0 && (r.role === "R" && r.assay < 100 || r.bottle && r.assay <= 100)) m.assay = r.assay;
      if (r.bottle) m.bottle = r.bottle;
      return m;
    });
    const products = materials.filter(m => m.id[0] === "P");
    const rec = { title: st.title.trim(), type: st.type, status: "planned", planned: true,
      researcher: idx.researcher || NB.state.user, started: NB.localDate() + " (planned)", question: st.question.trim() };
    if (st.legacy.trim()) rec.legacy_id = st.legacy.trim();
    if (screening) { rec.metric_kind = st.metric_kind; rec.metric = st.metric.trim(); }
    rec.key_result = "planned";
    if (st.smiles && source && !st.structures?.length) rec.smiles = st.smiles;
    rec.materials = materials;
    if (st.conditions.trim()) rec.conditions = st.conditions.trim();
    const paras = st.procedure.split(/\n\s*\n/).map(s => s.replace(/\s*\n\s*/g, " ").trim()).filter(Boolean);
    if (paras.length) { rec.procedure = paras; rec.procedure_basis = st.basis.trim() || "Planned."; }
    if (st.safety.trim()) rec.safety = st.safety.trim();
    if (screening && st.runs.some(r => r.run.trim())) {
      rec.runs = st.runs.filter(r => r.run.trim()).map(r => ({ run: r.run.trim(), variable: r.variable.trim(), result: "" }));
      rec.results_basis = "Planned; no results yet. Suggested NMR folders: " + idx.nmr_hints.run + ".";
    }
    rec.bench = BENCH[screening ? "screening" : "synthesis"].map(([field, hint]) => ({ field, hint }));
    rec.result_fields = screening
      ? [{ field: "NMR samples", hint: "Folders " + idx.nmr_hints.run + "; 1H with the internal standard" }, { field: "Outcome", hint: "Best run and what it shows" }]
      : [{ field: "Isolated mass and appearance", hint: "mass, appearance" },
         { field: "Yield", hint: products[0] && products[0].mmol ? "mmol isolated / " + products[0].mmol.toFixed(3) + " mmol theoretical" + (products[0].amount ? " (" + products[0].amount.replace(" theoretical", "") + ")" : "") : "mmol isolated / mmol theoretical" },
         { field: "NMR sample", hint: "Suggested folder: " + idx.nmr_hints.sample + "; 1H, 13C" }];
    rec.flags = st.flags.filter(fl => fl.text.trim()).map((fl, i) => ({ id: "new." + (i + 1), tier: fl.tier, text: fl.text.trim() }));
    if (st.refs && source) rec.sources = { refs: st.refs };
    const saveButton = ev.currentTarget;
    saveButton.disabled = true;
    try {
      const structures = st.structures?.map((d, i) => {
        const linked = materials.filter((m, j) => named[j].sourceIndex === i);
        const positions = Object.fromEntries(materials.flatMap((m, j) =>
          named[j].sourceIndex === i && named[j].sourcePosition != null ? [[m.id, named[j].sourcePosition]] : []));
        return { ...d, material_ids: linked.map(m => m.id), material_positions: positions };
      });
      const res = await NB.capi("POST", "/record", { record: rec, structures });
      clearTimeout(touch.t); NB.draft.clear(key); NB.dirty = false;
      NB.toast("Saved as experiment " + NB.expNo(res.id) + ". Rebuild the Word notebook to add its entry.");
      NB.state.index = null;
      location.hash = "#/exp/" + res.id;
    } catch (e) { saveButton.disabled = false; NB.fail(e); }
  };

  const fromSel = h("select", { "aria-label": "Start from an existing experiment", style: "min-width:0;flex:1 1 auto;width:100%", onchange: e => { location.hash = e.target.value ? "#/new/" + e.target.value : "#/new"; } },
    h("option", { value: "" }, "a blank plan"),
    idx.rows.filter(r => !/comput/.test(r.type)).map(r => h("option", { value: r.id, selected: r.id === fromId }, "Exp " + r.n + ": " + r.title)));
  draw();
  const structureBox = NB.structureBox({ sessionKey: key, view: sourceView, from: fromId, drafts: () => st.structures || [], rows: () => st.rows,
    apply: (species, draft, previous) => {
      st.rows = NB.importSpecies(st.rows, species, previous, true);
      st.rows.slice(0, species.length).forEach((r, i) => { r.sourceIndex = st.structures?.length || 0; r.sourcePosition = species[i].position; });
      (st.structures ||= []).push(draft); draw(); touch();
    } });
  const page = h("div", {},
    draft && draft.data && !NB.dirty ? h("div", { class: "banner" }, h("span", {}, "An unsaved plan from " + NB.fmtTime(draft.t) + " is kept on this computer."),
      h("span", { class: "row" }, h("button", { onclick: () => { NB.state.planRestore = draft.data; NB.draft.clear(key); NB.route().then(() => { NB.dirty = true; }); } }, "Restore it"),
        h("button", { class: "quiet", onclick: e => { NB.draft.clear(key); e.currentTarget.closest(".banner").remove(); } }, "Discard it"))) : null,
    NB.pageHead({ title: h("h1", {}, "Plan an experiment", h("span", { class: "vial planned t-" + (NB.isScreening(st.type) ? "screening" : "synthesis") }, "Exp " + nextN)),
      actions: h("label", { class: "row small", style: "flex:0 1 420px;min-width:0;flex-wrap:nowrap" }, h("span", { style: "white-space:nowrap" }, "Start from"), fromSel),
      status: source ? h("p", { class: "muted" }, "Copied from experiment " + NB.expNo(fromId) + ". Amounts in the table follow the scale; amounts written inside the procedure text do not. Results, NMR links and flags are not copied.") : h("p", { class: "muted" }, "Amounts are calculated from the scale. The plan is saved as a record with status planned; nothing is written until you save.") }),
    h("fieldset", {}, h("legend", {}, "What and why"),
      h("div", { class: "cols plan-basics" }, f("Title", bind("title")), f("Type", typeSel), f("Legacy or ELN ID, if assigned", bind("legacy"))),
      f("Question this experiment answers", bind("question", { rows: 2 })), metricFields),
    structureBox.box,
    h("fieldset", {}, h("legend", {}, "Stoichiometry"),
      h("div", { class: "row", style: "margin-bottom:10px" }, h("label", { class: "row" }, h("strong", {}, "Scale"), scaleIn, "mmol of the limiting reagent"),
        h("span", { class: "muted" }, "or from"), massIn, h("span", {}, "mg of it"), h("button", { class: "quiet", onclick: fromMass }, "Set scale")),
      h("div", { class: "tablewrap" }, h("table", { class: "grid" },
        h("thead", {}, h("tr", {}, ["Role", "ID", "Material", "Formula", "MW", "Equiv", "mmol", "Amount", "g/mL", "wt%", "Note", ""].map(c => h("th", {}, c)))), tbody)),
      h("div", { class: "row", style: "margin-top:8px" },
        h("button", { class: "quiet", onclick: () => { st.rows.splice(st.rows.filter(r => r.role === "R").length, 0, { role: "R", name: "", formula: "", mw: null, equiv: 1 }); draw(); } }, "Add a reagent"),
        h("button", { class: "quiet", onclick: () => { st.rows.push({ role: "S", name: "", conc: 0.1 }); draw(); } }, "Add a solvent"),
        h("button", { class: "quiet", onclick: () => { st.rows.push({ role: "P", name: "", formula: "", mw: null, factor: 1 }); draw(); } }, "Add a product")),
      lookup.panel, NB.hasInventory() ? null : NB.inventoryMissing(), invBox, checkBox,
      st.rows.some(r => r.derived) ? h("p", { class: "small", style: "color:var(--needed);margin-top:8px" }, "Densities were back-calculated from the recorded mass and volume, which are rounded. Correct them if you know the value.") : null,
      h("p", { class: "muted small", style: "margin-top:8px" }, "Mass = scale × equiv × MW ÷ assay. Volume = mass ÷ density. Solvent volume = scale ÷ concentration. Theoretical product = scale × (mol per mol) × MW.")),
    h("fieldset", {}, h("legend", {}, "Conditions and procedure"),
      f("Conditions, for example: 75 °C, 4 h", bind("conditions")),
      f("Planned procedure. Leave a blank line between paragraphs.", bind("procedure", { rows: 7 })), proseBox,
      f("Basis of the procedure", bind("basis")),
      f("Safety note (printed in red on the bench card and in the notebook)", bind("safety", { rows: 2 }))),
    runsField,
    h("fieldset", {}, h("legend", {}, "Hazard prompts"), hazardBox,
      h("p", { class: "muted small" }, "Matched from a short rule list against material names and temperatures. They are reminders, not a safety assessment: check the SDS and group SOPs.")),
    h("fieldset", {}, h("legend", {}, "Flags to settle before or after the run (three at most)"), flagBody),
    h("div", { class: "savebar" }, h("span", { style: "flex:1 1 auto" }, "Saves experiment " + nextN + " as planned, with bench and result fields to fill in."),
      h("button", { class: "primary", onclick: save }, "Save planned experiment"), h("a", { href: "#/experiments" }, "Cancel")));
  for (const ev of ["input", "change"]) page.addEventListener(ev, touch);
  page.addEventListener("click", e => { if (e.target.tagName === "BUTTON" && !e.target.closest(".banner")) touch(); });
  NB.setView(page);
}]);
})();
