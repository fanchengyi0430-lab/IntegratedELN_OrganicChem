/* Screening results, NMR yield tool, spectrum viewer and SI drafts. */
"use strict";
(function () {
const h = NB.h;
const INK = "#1D1A26", INK3 = "#767384", LINE = "#D5D7DB";
const FILL = { product: "rgba(106,44,145,0.16)", standard: "rgba(194,87,26,0.18)" };
const EDGE = { product: "#6A2C91", standard: "#C2571A" };
const NUC = { "1H": "¹H", "13C": "¹³C", "19F": "¹⁹F", "31P": "³¹P", "11B": "¹¹B" };
const phaseLabels = { topspin: "TopSpin's values", manual: "Manual", auto0: "Automatic zero-order" };
const savedProcessing = run => run.measured == null ? null : run.measured.processing || { source: "topspin" };
function processingText(p) {
  if (!p) return "";
  if (p.source === "topspin") return "TopSpin's spectrum";
  const delta = p.phase_mode !== "auto0" ? "" : p.delta_ph0 == null ? " (no TopSpin comparison)" :
    " (" + (p.delta_ph0 >= 0 ? "+" : "") + Number(p.delta_ph0.toFixed(4)) + "° from TopSpin)";
  return "Raw FID · " + p.lb_hz + " Hz · " + p.points + " points · " + phaseLabels[p.phase_mode] +
    " · PHC0 " + p.ph0 + "°" + delta + " · PHC1 " + p.ph1 + "° · numpy " + p.numpy;
}

NB.spectrumLinks = function (id, a) {
  return a.spectra.map((s, i) => [i ? ", " : "",
    h("a", { href: "#/spectrum/" + id + "/" + encodeURIComponent(a.sample) + "/" + s.acq, title: "View the processed spectrum" }, (NUC[s.nucleus] || s.nucleus) + " " + s.mhz),
    s.pdf ? [" (", h("a", { href: NB.fileUrl(s.pdf), target: "_blank", rel: "noopener" }, "PDF"), ")"] : null]).concat(
    a.mnova ? ["  ", h("a", { href: "#", title: (a.mnova_status ? a.mnova_status + ". " : "") + a.mnova, onclick: e => { e.preventDefault(); NB.openNative(a.mnova); } }, "Open in Mnova")]
            : [h("span", { class: "muted", title: "No .mnova file is linked or found for this sample" }, "  no Mnova file")]);
};

/* ---------- spectrum panel: drag to zoom, double-click to reset */
const { gainStep, wheelStep, fullKey, primary, hitEdge, width: plotWidth } = NB.plotControls;
const plots = new WeakMap();
const plotHint = "Left-drag to zoom, double-click to reset, F for full spectrum, wheel up or down for peak height.";
for (const event of ["beforeprint", "afterprint"]) window.addEventListener(event, () => {
  document.querySelectorAll(".spec canvas").forEach(canvas => plots.get(canvas)?.print(event === "beforeprint"));
});
document.addEventListener("keydown", e => {
  const canvas = document.querySelector(".spec canvas:hover") || document.querySelector(".spec canvas:focus");
  const typing = document.activeElement?.closest("input, textarea, select, [contenteditable]:not([contenteditable=false])");
  if (fullKey(e, !!canvas, !!typing)) { e.preventDefault(); plots.get(canvas)?.full(); }
});

NB.spectrumPanel = function (opts) {
  const canvas = h("canvas", { role: "img", tabindex: 0, "aria-label": "Processed NMR spectrum. " + plotHint });
  const readout = h("div", { class: "readout" });
  const el = h("div", { class: "spec" }, canvas, readout);
  let meta = null, ref = null, corr = 0, env = null, view = null, home = null, gain = 1, hover = null, drag = null, seq = 0;
  let printEnv = null, printing = false, requestedWidth = 0;
  const geom = () => { const W = plotWidth(canvas.clientWidth, printing), H = printing ? 340 : canvas.clientHeight; return { W, H, l: 14, r: 14, t: 24, b: 38, pw: W - 28, ph: H - 62 }; };
  const xOf = (ppm, g) => g.l + (view.hi - ppm) / (view.hi - view.lo) * g.pw;
  const ppmOf = (x, g) => view.hi - (x - g.l) / g.pw * (view.hi - view.lo);

  function draw() {
    const g = geom(), dpr = printing ? 1 : window.devicePixelRatio || 1;
    const envelope = printing ? printEnv : env;
    if (!g.W) return;
    canvas.width = Math.round(g.W * dpr); canvas.height = Math.round(g.H * dpr);
    const c = canvas.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, g.W, g.H);
    c.font = "12px Bahnschrift, 'DIN Alternate', 'DejaVu Sans Condensed', sans-serif";
    if (!envelope || !view) { c.fillStyle = INK3; c.fillText("Loading the spectrum…", g.l, g.t + 14); return; }
    let tallest = Math.max(1, ...envelope.max);
    const fit = opts.fit ? opts.fit() : [];
    if (fit.length) {                       // scale to the peaks being integrated; a solvent peak may run off the top
      let inside = 0;
      const n0 = envelope.max.length;
      for (let i = 0; i < n0; i++) {
        const ppm = envelope.hi + corr - (i + 0.5) / n0 * (envelope.hi - envelope.lo);
        if (envelope.max[i] > inside && fit.some(r => ppm >= r.lo && ppm <= r.hi)) inside = envelope.max[i];
      }
      if (inside > 0) tallest = Math.min(tallest, inside * 1.5);
    }
    const top = tallest / gain * 1.06, bottom = -0.05 * top;
    const yOf = v => g.t + g.ph - (Math.max(bottom, Math.min(top, v)) - bottom) / (top - bottom) * g.ph;
    for (const rg of (opts.regions ? opts.regions() : [])) {
      const x1 = Math.max(g.l, xOf(rg.hi, g)), x2 = Math.min(g.l + g.pw, xOf(rg.lo, g));
      if (x2 <= g.l || x1 >= g.l + g.pw) continue;
      c.fillStyle = FILL[rg.kind]; c.fillRect(x1, g.t, Math.max(2, x2 - x1), g.ph);
      c.fillStyle = EDGE[rg.kind]; c.fillRect(x1, g.t - 3, Math.max(2, x2 - x1), 3);
      if (opts.editEdge && !printing) for (const edge of [rg.hi, rg.lo]) {
        const x = xOf(edge, g);
        if (x >= g.l && x <= g.l + g.pw) { c.fillRect(x - 1, g.t, 2, g.ph); c.fillRect(x - 4, g.t + 4, 8, 10); }
      }
      c.fillStyle = INK; c.textAlign = "center"; c.fillText(rg.label, Math.max(g.l + 30, Math.min(g.l + g.pw - 30, (x1 + x2) / 2)), g.t - 8);
    }
    c.strokeStyle = LINE; c.lineWidth = 1; c.beginPath(); c.moveTo(g.l, yOf(0) + 0.5); c.lineTo(g.l + g.pw, yOf(0) + 0.5); c.stroke();
    const n = envelope.max.length;
    c.strokeStyle = INK; c.lineWidth = 1.2; c.lineJoin = "round"; c.beginPath();
    for (let i = 0; i < n; i++) {
      const x = g.l + (i + 0.5) / n * g.pw;
      if (i === 0) c.moveTo(x, yOf(envelope.max[i])); else c.lineTo(x, yOf(envelope.max[i]));
      if (envelope.min[i] !== envelope.max[i]) c.lineTo(x, yOf(envelope.min[i]));
    }
    c.stroke();
    /* axis */
    const span = view.hi - view.lo;
    const step = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].find(s => span / s <= 10) || 100;
    const dec = step < 0.01 ? 3 : step < 0.1 ? 2 : step < 1 ? 1 : 0;
    c.strokeStyle = INK3; c.fillStyle = "#4B4858"; c.textAlign = "center"; c.beginPath();
    c.moveTo(g.l, g.t + g.ph + 0.5); c.lineTo(g.l + g.pw, g.t + g.ph + 0.5);
    for (let t = Math.ceil(view.lo / step) * step; t <= view.hi + 1e-9; t += step) {
      const x = Math.round(xOf(t, g)) + 0.5;
      c.moveTo(x, g.t + g.ph); c.lineTo(x, g.t + g.ph + 5);
      c.fillText(t.toFixed(dec).replace("-", "−"), x, g.t + g.ph + 18);
    }
    c.stroke();
    c.textAlign = "right"; c.fillText("chemical shift, ppm", g.l + g.pw, g.H - 3);
    if (printing) return;
    if (drag && !drag.edge && Math.abs(drag.x1 - drag.x0) > 2) {
      const x0 = drag.x0, x1 = drag.x1;
      c.fillStyle = "rgba(29,26,38,0.10)"; c.fillRect(Math.min(x0, x1), g.t, Math.abs(x1 - x0), g.ph);
    } else if (hover !== null) {
      const x = hover + 0.5;
      c.strokeStyle = INK3; c.setLineDash([3, 3]); c.beginPath(); c.moveTo(x, g.t); c.lineTo(x, g.t + g.ph); c.stroke(); c.setLineDash([]);
    }
  }
  async function load() {
    if (!canvas.isConnected) return;
    requestedWidth = canvas.clientWidth;
    const mine = ++seq, bins = Math.max(10, requestedWidth - 28);
    let url = "/nmr/spectrum?folder=" + encodeURIComponent(opts.folder) + "&acq=" + encodeURIComponent(opts.acq) + "&bins=" + bins + "&print_bins=" + (plotWidth(requestedWidth, true) - 28);
    if (opts.processing) {
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(opts.processing())) if (value != null) query.set(key, value);
      url += "&" + query;
    }
    if (view) url += "&lo=" + (view.lo - corr) + "&hi=" + (view.hi - corr);
    try {
      const res = await NB.capi("GET", url);
      if (mine !== seq || !canvas.isConnected) return;
      const first = !meta;
      meta = res.meta; ref = res.reference; corr = ref && (!opts.reference || opts.reference()) ? ref.correction : 0;
      env = res.env; printEnv = res.print_env;
      if (opts.onProcessing) opts.onProcessing(meta.processing);
      readout.textContent = "";
      if (!view) view = { lo: env.lo + corr, hi: env.hi + corr };
      if (first) {
        home = opts.initial || { lo: view.lo, hi: view.hi };
        if (opts.onMeta) opts.onMeta(meta, ref);
        if (opts.initial) { view = { lo: opts.initial.lo, hi: opts.initial.hi }; return load(); }
      }
      draw();
    } catch (e) { if (mine === seq) { env = printEnv = null; draw(); readout.textContent = e.message; } }
  }
  const px = e => e.clientX - canvas.getBoundingClientRect().left;
  function edgeAt(e) {
    if (!view || !opts.editEdge) return null;
    const g = geom(), rect = canvas.getBoundingClientRect();
    const edges = opts.regions().flatMap(r => ["lo", "hi"].map(key => ({
      kind: r.kind, key, x: xOf(r[key], g), top: g.t - 3, bottom: g.t + g.ph
    }))).filter(edge => edge.x >= g.l && edge.x <= g.W - g.r);
    return hitEdge(e.clientX - rect.left, e.clientY - rect.top, edges);
  }
  canvas.addEventListener("mousedown", e => { if (e.button === 1) e.preventDefault(); });
  canvas.addEventListener("pointerdown", e => {
    if (!view || !primary(e)) return;
    canvas.focus({ preventScroll: true });
    const x = px(e);
    drag = { id: e.pointerId, x0: x, x1: x, edge: edgeAt(e) };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    if (!view || (drag && drag.id !== e.pointerId)) return;
    const g = geom(), x = Math.max(g.l, Math.min(g.l + g.pw, px(e)));
    hover = x;
    if (drag) {
      drag.x1 = x;
      if (drag.edge && x !== drag.x0) opts.editEdge(drag.edge, ppmOf(x, g));
    }
    canvas.style.cursor = (drag ? drag.edge : edgeAt(e)) ? "ew-resize" : "crosshair";
    readout.textContent = ppmOf(x, g).toFixed(3).replace("-", "−") + " ppm";
    draw();
  });
  canvas.addEventListener("pointerup", e => {
    if (!primary(e) || !drag || e.pointerId !== drag.id) return;
    const g = geom(), a = ppmOf(drag.x0, g), b = ppmOf(drag.x1, g);
    const zoom = !drag.edge && Math.abs(drag.x1 - drag.x0) > 6;
    drag = null;
    if (zoom) { view = { lo: Math.min(a, b), hi: Math.max(a, b) }; gain = 1; load(); } else draw();
  });
  canvas.addEventListener("lostpointercapture", () => { drag = null; draw(); });
  canvas.addEventListener("pointerleave", () => { hover = null; readout.textContent = ""; if (!drag) draw(); });
  canvas.addEventListener("dblclick", e => { if (primary(e) && home) { view = { ...home }; gain = 1; load(); } });
  canvas.addEventListener("wheel", e => { e.preventDefault(); gain = gainStep(gain, wheelStep(e.deltaY, true)); draw(); }, { passive: false });
  const full = () => { view = null; gain = 1; load(); };
  plots.set(canvas, { full, print(active) { printing = active; draw(); } });
  if (window.ResizeObserver) new ResizeObserver(() => {
    if (printing || !canvas.isConnected || !requestedWidth || canvas.clientWidth === requestedWidth) return;
    load();
  }).observe(canvas);
  setTimeout(load, 0);
  return { el, redraw: draw, reload() { env = printEnv = null; draw(); load(); },
    setView(lo, hi) { view = { lo: Math.min(lo, hi), hi: Math.max(lo, hi) }; gain = 1; load(); },
    full,
    getView() { return view ? { lo: view.lo, hi: view.hi } : null; },
    taller() { gain = gainStep(gain, 1); draw(); }, shorter() { gain = gainStep(gain, -1); draw(); } };
};

/* ---------- spectrum viewer */
NB.routes.push([/^#\/spectrum\/(EXP-\d+)\/([^/]+)\/(\d+)$/, async function (id, sampleEnc, acq) {
  const sample = decodeURIComponent(sampleEnc);
  const view = await NB.capi("GET", "/record/" + id);
  const a = view.derived.acquisitions.find(x => x.sample === sample);
  if (!a) throw new Error("Experiment " + NB.expNo(id) + " does not list the NMR sample " + sample + ".");
  const s = a.spectra.find(x => x.acq === acq) || {};
  const info = h("p", { class: "muted" }, "Reading the spectrum…");
  const panel = NB.spectrumPanel({ folder: a.folder, acq, onMeta: (m, ref) => {
    NB.put(info, NB.formula([(NUC[m.nucleus] || m.nucleus) + " at " + m.mhz + " MHz", m.solvent, m.scans ? m.scans + " scans" : null, m.pulprog].filter(Boolean).join(", ") + ". " +
      (ref ? "Axis re-referenced by " + (ref.correction >= 0 ? "+" : "−") + Math.abs(ref.correction).toFixed(3) + " ppm so that " + ref.solvent + " is at " + ref.target + " (found at " + ref.found.toFixed(3) + ")." : "Axis as processed (no solvent peak used for referencing).")));
  } });
  const zooms = (s.nucleus || "1H") === "1H" ? [["Aromatic", 6, 9.5], ["Aliphatic", 0, 5]] : [];
  const hasSpectra = view.derived.acquisitions.some(item => item.exists && item.spectra.length);
  const current = hasSpectra ? (view.record.runs ? "NMR yields" : "SI draft") : "Record";
  NB.setView(
    NB.experimentHead(view, current, h("a", { href: "#/exp/" + id }, "Back to experiment " + NB.expNo(id))),
    h("h1", { class: "print-only" }, sample), h("h2", { class: "noprint" }, sample), info,
    h("div", { class: "toolbar" }, h("button", { class: "quiet", title: "Full spectrum (F)", onclick: () => panel.full() }, "Full spectrum"),
      zooms.map(([label, lo, hi]) => h("button", { class: "quiet", onclick: () => panel.setView(lo, hi) }, label)),
      h("button", { class: "quiet", onclick: () => panel.taller() }, "Taller peaks"), h("button", { class: "quiet", onclick: () => panel.shorter() }, "Shorter peaks"),
      s.pdf ? h("a", { class: "btn quiet", href: NB.fileUrl(s.pdf), target: "_blank", rel: "noopener" }, "Open the PDF") : null,
      h("button", { class: "quiet", onclick: () => NB.openNative(a.folder) }, "Open the data folder")),
    panel.el,
    h("p", { class: "muted small noprint", style: "margin-top:8px" }, plotHint));
}]);

/* ---------- screening results */
NB.routes.push([/^#\/screening$/, async function () {
  const [idx, res] = await Promise.all([NB.loadIndex(), NB.capi("GET", "/screening")]);
  const byId = Object.fromEntries(idx.rows.map(r => [r.id, r]));
  let basis = "all", sort = "notebook", query = "";
  const body = h("tbody", {}), head = h("thead", {}), info = h("p", { class: "muted small" });
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Filter by basis" });
  const columns = ["Run", "Conditions", "Result", "Conv.", "Basis"];
  const metric = r => NB.metricText(r) || "Unspecified";
  const countRuns = rows => rows.filter(r => r.run).length;
  const draw = () => {
    NB.put(seg, ...[["all", "All"], ["measured", "Measured"], ["slides", "From slides"], ["outlined", "Target or literature"]].map(([k, l]) => h("button", { class: basis === k ? "on" : "", onclick: () => { basis = k; draw(); } }, l)));
    const q = query.trim().toLowerCase();
    let rows = res.rows.filter(r => (basis === "all" || r.basis_kind === basis || (basis === "outlined" && NB.outlinedBasis(r.basis_kind))) &&
      (!q || [r.variable, r.title, r.result, metric(r), "exp " + r.n].join(" ").toLowerCase().includes(q)));
    const cells = r => [h("td", {}, h("strong", {}, r.run)), h("td", {}, NB.formula(r.variable)),
      h("td", {}, NB.hasYieldMetric(r.metric_kind) ? NB.yieldBar(r.result, r.basis) : r.result || "–",
        r.nmr_source ? h("div", { class: "muted small" }, r.nmr_source === "fid" ? "Raw FID" : "TopSpin") : null),
      h("td", { class: "num" }, r.conv === null ? "" : r.conv + "%"), h("td", { class: "small" }, r.basis ? NB.formula(r.basis) : h("span", { class: "muted" }, "none"))];
    if (sort === "yield") {
      rows = rows.filter(r => NB.hasYieldMetric(r.metric_kind) && (r.yield !== null || r.kind === "nd"))
        .sort((a, b) => (b.yield === null ? -1 : b.yield) - (a.yield === null ? -1 : a.yield));
      NB.put(head, h("tr", {}, ["Experiment", "Primary metric", ...columns].map(c => h("th", {}, c))));
      NB.put(body, ...rows.map(r => h("tr", {}, h("td", {}, NB.vial(byId[r.exp], "#/exp/" + r.exp)), h("td", {}, metric(r)), cells(r))));
    } else {
      NB.put(head, h("tr", {}, columns.map(c => h("th", {}, c))));
      const out = [];
      let last = null;
      for (const r of rows) {
        if (r.exp !== last) {
          last = r.exp;
          const canMeasure = res.rows.some(x => x.exp === r.exp && x.has_spectrum);
          out.push(h("tr", {}, h("td", { colspan: columns.length, style: "background:var(--paper);padding-top:12px" }, NB.vial(byId[r.exp], "#/exp/" + r.exp), "  ", h("strong", {}, NB.formula(r.title)),
            h("span", { class: "muted", style: "margin-left:12px" }, "Primary metric · " + metric(r)),
            canMeasure ? h("a", { href: "#/nmr/" + r.exp, style: "margin-left:12px" }, "Measure from spectra") : null)));
        }
        out.push(h("tr", {}, r.run ? cells(r) : h("td", { colspan: columns.length, class: "muted" }, "No runs recorded.")));
      }
      NB.put(body, ...out);
    }
    const m = res.rows.filter(r => r.basis_kind === "measured").length, s = res.rows.filter(r => r.basis_kind === "slides").length;
    const total = countRuns(res.rows);
    const outlined = res.rows.filter(r => NB.outlinedBasis(r.basis_kind)).length;
    const experiments = new Set(res.rows.map(r => r.exp)).size;
    info.textContent = total + " runs in " + experiments + (experiments === 1 ? " experiment: " : " experiments: ") + m + " measured, " + s + " from slides, " + outlined + " target or literature, " + (total - m - s - outlined) + " other or not reported." + (rows.length !== res.rows.length ? " Showing " + countRuns(rows) + " runs." : "");
    if (!rows.length) NB.put(body, h("tr", {}, h("td", { colspan: columns.length + (sort === "yield" ? 2 : 0), class: "empty" }, "No run matches.")));
  };
  draw();
  NB.setView(
    NB.pageHead({ title: "Screening results", status: info }),
    h("div", { class: "toolbar" },
      h("input", { type: "search", placeholder: "Filter by conditions, for example CHCl3 or 20 mol%", "aria-label": "Filter runs", oninput: e => { query = e.target.value; draw(); } }), seg,
      h("select", { "aria-label": "Order", onchange: e => { sort = e.target.value; draw(); } }, h("option", { value: "notebook" }, "Notebook order"), h("option", { value: "yield" }, "Highest yield first")),
      h("a", { class: "btn quiet", href: "/api/case/" + encodeURIComponent(NB.state.case) + "/screening?format=csv" }, "Download CSV")),
    NB.yieldLegend(h("span", {}, "nd = not detected, nr = not reported")),
    h("div", { class: "tablewrap" }, h("table", {}, head, body)));
}]);

/* ---------- NMR yield tool: a value can only be saved with the settings that produced it */
NB.routes.push([/^#\/nmr\/(EXP-\d+)$/, async function (id) {
  const [view, capability] = await Promise.all([NB.capi("GET", "/record/" + id), NB.capi("GET", "/nmr/meta")]);
  const rec = view.record, d = view.derived, n = d.n;
  if (!rec.runs || !rec.runs.length) throw new Error("Experiment " + n + " has no run table. NMR yields are measured per run.");
  const yields = NB.hasYieldMetric(rec.metric_kind);
  const first = list => list && list[0] ? { name: list[0].name, lo: list[0].lo, hi: list[0].hi, nH: list[0].nH } : null;
  const set = { product: first(d.nmr_presets.product) || { name: "", lo: 8.6, hi: 8.8, nH: 1 }, standard: first(d.nmr_presets.standard) || { name: "", lo: 6.77, hi: 6.83, nH: 3 },
    std_mmol: d.nmr_defaults.std_mmol, limiting_mmol: d.nmr_defaults.limiting_mmol, baseline: true, reference: true, snap: true };
  set.regions_by_run = Object.fromEntries(rec.runs.filter(r => r.measured?.regions).map(r =>
    [r.run, JSON.parse(JSON.stringify(r.measured.regions))]));
  const opt = { nd: 2 };
  const saved = Object.fromEntries(rec.runs.map(r => [r.run, savedProcessing(r)]));
  set.processing_by_run = Object.fromEntries(rec.runs.map(r => {
    const p = saved[r.run];
    if (!p || p.source !== "fid") return [r.run, { source: "topspin" }];
    const { source, lb_hz, points, phase_mode, ph0, ph1 } = p;
    return [r.run, { source, lb_hz, points, phase_mode, ph0, ph1 }];
  }));
  let rows = rec.runs.map(r => {
    const sample = d.acquisitions.find(a => a.sample === d.run_samples[r.run]);
    const h1 = sample && sample.spectra.find(s => s.nucleus === "1H");
    return { run: String(r.run), variable: r.variable, recorded: r.result, basis: r.basis,
      folder: h1 && sample.folder, acq: h1 && h1.acq };
  });
  let picked = new Set(), current = null, panel = null, used = null, stale = false, batchSequence = 0;
  const tbody = h("tbody", {}), specBox = h("div", {}), saveBox = h("div", {}), staleBox = h("div", { "aria-live": "polite" });
  const keyResult = h("input", { type: "text", style: "flex:1 1 320px", "aria-label": "Key result" });
  keyResult.value = rec.key_result || "";
  const fmtRegion = r => r.lo + "–" + r.hi + " ppm (" + r.nH + "H)";
  let runEditor;
  const changed = () => {            // an input of the calculation moved: what is on screen no longer matches the controls
    if (used && !stale) { stale = true; drawTable(); drawSave(); }
    if (panel) panel.redraw();
    runEditor?.sync();
  };
  const numIn = (obj, key, label, width, onChange) => {
    const el = h("input", { type: "text", inputmode: "decimal", style: "width:" + (width || 64) + "px", "aria-label": label });
    el.value = obj[key] === null || obj[key] === undefined ? "" : obj[key];
    el.addEventListener("input", () => { const v = parseFloat(el.value); obj[key] = isNaN(v) ? null : v; (onChange || changed)(); });
    return el;
  };
  function processingEditor(run) {
    const box = h("fieldset", {}), status = h("p", { class: "muted small", "aria-live": "polite" });
    let effective = null, inputs = {};
    const settings = () => set.processing_by_run[run];
    const refresh = () => { changed(); status.textContent = ""; panel.reload(); };
    const select = (label, value, choices, change) => h("label", { class: "row" }, label,
      h("select", { "aria-label": label, onchange: e => change(e.target.value) },
        Object.entries(choices).map(([k, name]) => h("option", { value: k, selected: value === k,
          disabled: k === "fid" && !capability.fid_available }, name))));
    function field(key, label, step) {
      const p = settings(), input = h("input", { type: "text", inputmode: "decimal", "aria-label": label,
        style: "width:76px", value: p[key] ?? "" });
      input.addEventListener("input", () => {
        const value = input.value.trim();
        // Preserve invalid text for a validation message from the processor. A blank uses its default.
        p[key] = value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : value;
        refresh();
      });
      inputs[key] = input;
      const adjust = sign => {
        const start = Number(p[key] ?? effective?.[key] ?? input.placeholder ?? 0);
        if (!Number.isFinite(start)) return;
        p[key] = Number((start + sign * step).toFixed(6)); input.value = p[key]; refresh();
      };
      return h("div", { class: "row" }, h("label", { class: "row" }, label, input), step ? [-1, 1].map(sign =>
        h("button", { class: "quiet", type: "button", "aria-label": (sign > 0 ? "Increase " : "Decrease ") + label,
          onclick: () => adjust(sign) }, sign > 0 ? "+1°" : "−1°")) : null);
    }
    function draw() {
      const p = settings();
      inputs = {};
      const changeSource = source => {
        set.processing_by_run[run] = source === "fid" ? { source, phase_mode: "topspin" } : { source };
        effective = null; draw(); refresh();
      };
      NB.put(box, h("legend", {}, "Processing for run " + run),
        h("div", { class: "row" }, select("Spectrum source", p.source,
          { topspin: "TopSpin's spectrum", fid: "Raw FID, processed here" }, changeSource),
          !capability.fid_available ? h("span", { class: "muted small" }, capability.fid_reason) : null),
        p.source === "fid" ? h("div", { class: "row" }, field("lb_hz", "Line broadening (Hz)"), field("points", "Points"),
          select("Phase", p.phase_mode, phaseLabels, mode => {
            if (mode === "manual" && effective) { p.ph0 = effective.ph0; p.ph1 = effective.ph1; }
            else { delete p.ph0; delete p.ph1; }
            p.phase_mode = mode; draw(); refresh();
          }), p.phase_mode === "manual" ? [field("ph0", "Zero-order (°)", 1), field("ph1", "First-order (°)", 1)] : null) : null,
        status, rec.runs.length > 1 ? h("button", { class: "quiet", onclick: () => {
          for (const r of rec.runs) set.processing_by_run[r.run] = { ...p };
          // Keep this run's input handlers attached to its settings object.
          set.processing_by_run[run] = p; changed();
        } }, "Use these processing settings for all runs") : null);
    }
    draw();
    return { el: box, settings, onProcessing(p) {
      effective = p; status.textContent = processingText(p);
      for (const [k, input] of Object.entries(inputs)) input.placeholder = p[k] ?? "";
    } };
  }
  const regionEditor = (kind, title, presets) => {
    const r = set[kind], box = h("div", {});
    const drawBox = () => NB.put(box,
      h("div", { class: "row", style: "gap:6px" }, h("strong", { style: "min-width:74px" }, title), numIn(r, "hi", title + " region, high edge in ppm"), "to", numIn(r, "lo", title + " region, low edge in ppm"), "ppm,",
        numIn(r, "nH", title + " number of protons", 44), "H",
        presets.length ? h("select", { "aria-label": title + " preset", onchange: e => { const p = presets[e.target.value]; if (p) { Object.assign(r, { name: p.name, lo: p.lo, hi: p.hi, nH: p.nH }); drawBox(); changed(); } } },
          h("option", { value: "" }, "Presets"), presets.map((p, i) => h("option", { value: i, selected: p.name === r.name }, p.name))) : null,
        h("button", { class: "quiet", title: "Zoom the spectrum to the range you want, then press this", onclick: () => { const v = panel && panel.getView(); if (!v) return; r.lo = +v.lo.toFixed(3); r.hi = +v.hi.toFixed(3); r.name = ""; drawBox(); changed(); } }, "Use the zoomed range")));
    drawBox();
    return box;
  };
  const check = (key, label) => h("label", { class: "row", style: "gap:5px" }, h("input", { type: "checkbox", checked: set[key], onchange: e => { set[key] = e.target.checked; changed(); if (key === "reference") panel?.reload(); } }), label);
  const regions = () => {
    const row = rows.find(r => r.run === current), c = !stale && row && row.calc, corr = c && c.reference ? c.reference.correction : 0;
    return ["product", "standard"].map(kind => {
      let bounds = set.regions_by_run[current]?.[kind];
      if (!bounds && c && kind === "standard" && set.snap) {
        bounds = [c.standard.lo, c.standard.hi].map(edge => Number((edge + corr).toFixed(4)));
      }
      bounds ||= [set[kind].lo, set[kind].hi];
      return { kind, lo: bounds[0], hi: bounds[1], label: kind + ", " + set[kind].nH + "H" };
    });
  };
  function manualEditor(run) {
    const fields = {}, state = h("span", { class: "muted small" });
    const release = h("button", { class: "quiet", onclick: () => {
      delete set.regions_by_run[run]; changed();
    } }, "Use the shared regions");
    function sync() {
      for (const r of regions()) for (const key of ["lo", "hi"]) {
        const input = fields[r.kind + key];
        if (document.activeElement !== input) input.value = r[key] ?? "";
      }
      release.disabled = !set.regions_by_run[run];
      state.textContent = release.disabled ? "" : "manual regions";
    }
    function edit(kind, key, value) {
      const manual = set.regions_by_run[run] ||= { manual: true,
        ...Object.fromEntries(regions().map(r => [r.kind, [r.lo, r.hi]])) };
      manual[kind][key === "lo" ? 0 : 1] = value;
      changed();
    }
    const row = h("fieldset", {}, h("legend", {}, "Regions for this run"),
      h("div", { class: "row" }, ["product", "standard"].map(kind => [
        h("strong", {}, kind === "product" ? "Product" : "Standard"),
        ["lo", "hi"].map(key => {
          const label = key === "lo" ? "Low ppm" : "High ppm";
          const input = fields[kind + key] = h("input", { type: "number", step: "any", style: "width:78px",
            "aria-label": kind + " " + label, oninput: e => edit(kind, key, Number.isFinite(e.target.valueAsNumber) ? e.target.valueAsNumber : null) });
          return h("label", {}, label, input);
        })]), state, release));
    sync();
    return { row, sync, edge({ kind, key }, value) {
      const r = regions().find(region => region.kind === kind);
      const ppm = Number(value.toFixed(4));
      if (key === "lo" ? ppm < r.hi : ppm > r.lo) edit(kind, key, ppm);
    } };
  }
  const showRun = run => {
    current = run;
    const row = rows.find(r => r.run === run);
    drawTable();
    if (!row || !row.folder) { panel = runEditor = null; return NB.put(specBox, h("p", { class: "empty" }, "Run " + run + " has no ¹H spectrum linked to it.")); }
    runEditor = manualEditor(run);
    const bounds = () => regions();
    const lo = Math.min(...bounds().map(r => r.lo)) - 0.25, hi = Math.max(...bounds().map(r => r.hi)) + 0.25;
    const editor = processingEditor(run);
    panel = NB.spectrumPanel({ folder: row.folder, acq: row.acq, editEdge: runEditor.edge, regions, fit: regions, reference: () => set.reference,
      initial: { lo, hi }, processing: editor.settings, onProcessing: editor.onProcessing });
    NB.put(specBox,
      h("h2", {}, "Run " + run + ": ", NB.formula(row.variable)), h("p", { class: "muted small" }, row.folder + ", acquisition " + row.acq),
      editor.el,
      h("div", { class: "toolbar" },
        h("button", { class: "quiet", onclick: () => panel.setView(bounds()[0].lo - 0.12, bounds()[0].hi + 0.12) }, "Product region"),
        h("button", { class: "quiet", onclick: () => panel.setView(bounds()[1].lo - 0.12, bounds()[1].hi + 0.12) }, "Standard region"),
        h("button", { class: "quiet", onclick: () => panel.setView(lo, hi) }, "Both"), h("button", { class: "quiet", title: "Full spectrum (F)", onclick: () => panel.full() }, "Full spectrum"),
        h("button", { class: "quiet", onclick: () => panel.taller() }, "Taller peaks"), h("button", { class: "quiet", onclick: () => panel.shorter() }, "Shorter peaks")),
      h("div", { class: "legend" }, h("span", {}, h("i", { class: "prod" }), "product region"), h("span", {}, h("i", { class: "std" }), "standard region"),
        h("span", {}, "Height is scaled to the integrated peaks, so the solvent peak may run off the top.")),
      panel.el, h("p", { class: "muted small noprint" }, plotHint), runEditor.row);
  };
  const drawTable = () => {
    NB.put(staleBox, stale ? h("div", { class: "banner" }, h("span", {}, "The settings changed after these values were calculated. Integrate again before saving."),
      h("button", { class: "primary integrate-again", onclick: integrate }, "Integrate again")) : null);
    NB.put(tbody, rows.map(r => {
      const c = r.calc, y = c && c.yield !== null ? c.yield : null, rec0 = yields ? NB.parseYield(r.recorded) : null;
      const delta = y !== null && rec0 !== null ? y - rec0 : null;
      return h("tr", { class: "link" + (r.run === current ? " current" : "") + (stale ? " stale" : ""), onclick: e => { if (!/INPUT|BUTTON/.test(e.target.tagName)) showRun(r.run); } },
        h("td", {}, yields && y !== null ? h("input", { type: "checkbox", checked: picked.has(r.run), disabled: stale, "aria-label": "Save run " + r.run, onchange: e => { e.target.checked ? picked.add(r.run) : picked.delete(r.run); drawSave(); } }) : null),
        h("td", {}, h("button", { class: "runpick", "aria-pressed": String(r.run === current), title: "Show this run's spectrum", onclick: () => showRun(r.run) }, r.run)), h("td", {}, NB.formula(r.variable)),
        h("td", {}, yields ? NB.yieldBar(r.recorded, r.basis) : r.recorded || "–", h("div", { class: "muted small" }, NB.formula(r.basis)),
          h("div", { class: "muted small" }, processingText(saved[r.run]))),
        h("td", {}, y !== null ? h("div", { class: "bar" }, h("div", { class: "track" }, y > 0 ? h("div", { class: "fill", style: "width:" + Math.min(100, y) + "%" }) : null), h("span", { class: "val" }, y.toFixed(1).replace("-", "−") + "%")) : h("span", { class: "muted" }, "–"),
          c ? h("div", { class: "muted small" }, processingText(c.processing) + (c.regions ? " · manual regions" : "")) : null,
          (c && c.note) || r.note ? h("div", { class: "small", style: "color:var(--needed)" }, (c && c.note) || r.note) : null),
        h("td", { class: "num" }, delta === null ? "" : (delta >= 0 ? "+" : "−") + Math.abs(delta).toFixed(1)));
    }));
  };
  const drawSave = () => {
    if (!yields) return NB.put(saveBox, rows.length ? h("p", { class: "muted small" },
      "The primary metric is " + rec.metric_kind + ". Use Edit to record that result.") : null);
    NB.put(saveBox, rows.length ? h("fieldset", { style: "margin-top:18px" }, h("legend", {}, "Save to the record"),
      h("p", { class: "small" }, "Ticked runs get the value calculated above, the basis “measured " + NB.localDate() + "” and a reference to the settings used, which are written once under the run table. Runs measured earlier with other settings keep their own description. The earlier value stays in the basis text and in the record's history folder."),
      h("div", { class: "row" }, h("label", { class: "row" }, "Report as nd below", numIn(opt, "nd", "Not-detected limit in percent", 50, () => {}), "%"),
        h("label", { class: "row", style: "flex:1 1 420px" }, "Key result for the index", keyResult)),
      h("p", { class: "row", style: "margin-top:10px" }, h("button", { class: "primary save-measured", disabled: stale || !picked.size, onclick: save }, "Save " + picked.size + " measured run" + (picked.size === 1 ? "" : "s")),
        h("span", { class: "muted small" }, "Check the phase and baseline of each spectrum before saving."))) : null);
  };
  const integrate = async ev => {
    const btn = ev && ev.currentTarget;
    if (!(set.product.hi > set.product.lo) || !(set.standard.hi > set.standard.lo) || !(set.product.nH > 0) || !(set.standard.nH > 0)) return NB.toast("Each region needs a high edge above its low edge and a proton count.", true);
    if (!(set.std_mmol > 0) || !(set.limiting_mmol > 0)) return NB.toast("Enter the mmol of internal standard and of limiting reagent.", true);
    const asked = JSON.parse(JSON.stringify(set));
    const sequence = ++batchSequence;
    if (btn) btn.disabled = true;
    try {
      const res = await NB.capi("POST", "/nmr/batch", Object.assign({ exp: id }, asked));
      if (sequence !== batchSequence) return;
      rows = res.runs; used = asked; stale = !NB.same(asked, set);
      picked = new Set(rows.filter(r => r.calc && r.calc.yield !== null && !r.calc.note).map(r => r.run));
      drawTable(); drawSave();
      const best = rows.filter(r => r.folder).sort((a, b) => ((b.calc && b.calc.yield) || 0) - ((a.calc && a.calc.yield) || 0))[0];
      showRun(current && rows.some(r => r.run === current) ? current : best ? best.run : rows[0].run);
    } catch (e) { NB.fail(e); }
    if (btn) btn.disabled = false;
  };
  const save = async () => {
    if (stale || !used) return NB.toast("Integrate again first: the settings changed after the values were calculated.", true);
    const next = JSON.parse(JSON.stringify(rec)), U = used, today = NB.localDate();
    let stdName = (U.standard.name || d.nmr_defaults.std_name || "internal standard").replace(/\s*\(internal standard\)/, "");
    stdName = stdName[0].toLowerCase() + stdName.slice(1);
    const integration = manual => {
      const region = k => manual ? { ...U[k], lo: manual[k][0], hi: manual[k][1] } : U[k];
      return today + (manual ? ", manual regions" : "") + ", product " + fmtRegion(region("product")) + "; " + stdName + " " + fmtRegion(region("standard")) + "; " + U.std_mmol + " mmol standard, " + U.limiting_mmol + " mmol limiting reagent" +
      (U.baseline ? "; linear baseline" : "; no baseline correction") + (U.reference ? "; solvent peak set to its reference shift" : "") + (!manual && U.snap ? "; standard region centred on its tallest peak" : "") +
      (opt.nd > 0 ? "; below " + opt.nd + "% reported as nd" : "");
    };
    /* methods already described under the run table keep their text; this calculation gets its own tag */
    const mark = "Measured runs (notebook app, processed ¹H spectra; 'measured' is the integral ratio in percent):";
    const whole = String(next.results_basis || "").replace(/\s*Runs marked measured:[\s\S]*$/, ""), at = whole.indexOf(mark);
    const head = (at < 0 ? whole : whole.slice(0, at)).trim(), methods = {};
    if (at >= 0) for (const m of whole.slice(at + mark.length).matchAll(/\[(m\d+)\]\s*([^\[]*)/g)) methods[m[1]] = m[2].trim().replace(/\.$/, "");
    let count = 0;
    for (const row of rows) {
      if (!picked.has(row.run) || !row.calc || row.calc.yield === null) continue;
      const run = next.runs.find(r => String(r.run) === row.run);
      if (!run) continue;
      const method = integration(row.calc.regions) + ". " + processingText(row.calc.processing);
      let tag = Object.keys(methods).find(k => methods[k] === method);
      if (!tag) { tag = "m" + (Math.max(0, ...Object.keys(methods).map(k => parseInt(k.slice(1), 10))) + 1); methods[tag] = method; }
      const y = row.calc.yield, was = String(run.basis || "");
      const prior = was.startsWith("measured") ? (was.split("; was ")[1] || "") : [run.result, was ? "(" + was + ")" : ""].filter(Boolean).join(" ");
      run.result = y < (opt.nd || 0) ? "nd" : Math.round(y) + "%";
      run.basis = "measured " + today + " [" + tag + "]" + (prior ? "; was " + prior : "");
      run.measured = { value: Math.round(y * 100) / 100, processing: row.calc.processing };
      if (row.calc.regions) run.measured.regions = row.calc.regions;
      delete run.integration;
      if (next.planned) { next.entries = next.entries || {}; next.entries[NB.runTag(id, run.run)] = run.result + " (measured " + today + ")"; }
      count++;
    }
    const inUse = Object.keys(methods).filter(k => next.runs.some(r => String(r.basis || "").includes("[" + k + "]")));
    next.results_basis = (head + " " + mark + " " + inUse.map(k => "[" + k + "] " + methods[k] + ".").join(" ")).trim();
    if (keyResult.value.trim()) next.key_result = keyResult.value.trim();
    try {
      const r = await NB.saveMerged(id, rec, next, view.meta.hash, count + " run(s) measured from the ¹H spectra", ["metric_kind"]);
      if (r.conflict) return NB.toast("This experiment was changed elsewhere in the same fields (" + r.conflict.both.join(", ") + "). Reload this page and integrate again.", true);
      NB.toast(r.changed ? count + " run(s) saved as measured." : "Nothing changed.");
      NB.state.index = null;
      location.hash = "#/exp/" + id;
    } catch (e) { NB.fail(e); }
  };

  NB.setView(
    NB.experimentHead(view, "NMR yields", h("a", { href: "#/exp/" + id }, "Back to experiment " + n)),
    h("h1", { class: "print-only" }, "NMR yields", NB.vial({ id, type: rec.type, legacy_id: rec.legacy_id })),
    h("p", { class: "muted" }, NB.formula(rec.title + ". " + NB.metricText(rec))),
    h("fieldset", {}, h("legend", {}, "Integration"),
      regionEditor("product", "Product", d.nmr_presets.product), h("div", { style: "height:8px" }), regionEditor("standard", "Standard", d.nmr_presets.standard),
      h("div", { class: "row", style: "margin-top:12px" },
        h("label", { class: "row" }, "Internal standard", numIn(set, "std_mmol", "Internal standard in millimoles", 84), "mmol"),
        h("label", { class: "row" }, "Limiting reagent", numIn(set, "limiting_mmol", "Limiting reagent in millimoles", 84), "mmol"),
        h("span", { class: "muted small" }, [d.nmr_defaults.std_name, d.nmr_defaults.limiting_name].filter(Boolean).join("; ") || "No standard found in the materials table: enter both amounts.")),
      h("div", { class: "row", style: "margin-top:10px;gap:18px" }, check("baseline", "Subtract a linear baseline"), check("reference", "Set the solvent peak to its reference shift first"), check("snap", "Centre the standard region on its tallest peak")),
      h("p", { style: "margin:12px 0 0" }, h("button", { class: "primary integrate-all", onclick: integrate }, "Integrate all runs"),
        h("span", { class: "muted small", style: "margin-left:12px" }, "Yield = (product area ÷ H) ÷ (standard area ÷ H) × mmol standard ÷ mmol limiting reagent."))),
    staleBox,
    h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Save"), h("th", {}, "Run"), h("th", {}, "Conditions"), h("th", {}, "In the record"), h("th", {}, "Calculated here"), h("th", { class: "num" }, "Difference"))), tbody)),
    saveBox, specBox);
  const initial = rows.find(r => r.folder && saved[r.run]) || rows.find(r => r.folder) || rows[0];
  showRun(initial.run);
  if (set.std_mmol > 0 && set.limiting_mmol > 0 && d.nmr_presets.product.length) integrate();
}]);

/* ---------- SI drafts: reviewed characterization and unassigned peak lists are kept apart */
NB.routes.push([/^#\/si$/, async function () {
  const idx = await NB.loadIndex();
  const rows = idx.rows.filter(r => /synth|isolation/.test(r.type) && r.status !== "planned");
  NB.setView(
    NB.pageHead({ title: "SI drafts",
      status: h("p", { class: "prose" }, "A draft collects what the record and the processed spectra already contain for one isolated compound, and lists what is still missing. Peak lists read from spectra are unassigned observations until a reviewed characterization is entered on the edit page.") }),
    h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Experiment"), h("th", {}, "Compound or subject"), h("th", {}, "Result (basis)"), h("th", { class: "num" }, "Spectra"), h("th", {}, "Flags"), h("th", {}, ""))),
      h("tbody", {}, rows.map(r => h("tr", {}, h("td", {}, NB.vial(r, "#/exp/" + r.id)), h("td", {}, NB.formula(r.title)), h("td", {}, NB.formula(r.key_result)), h("td", { class: "num" }, r.spectra || "–"), h("td", {}, NB.flagChips(r.flags)),
        h("td", {}, h("a", { href: "#/si/" + r.id }, "Open draft"))))))));
}]);
NB.routes.push([/^#\/si\/(EXP-\d+)$/, async function (id) {
  NB.setView(h("p", { class: "muted" }, "Reading the spectra for experiment " + NB.expNo(id) + "…"));
  const [d, view] = await Promise.all([NB.capi("GET", "/si/" + id), NB.capi("GET", "/record/" + id)]);
  const list = rows => h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, rows.map(l => h("tr", {},
    h("td", { class: "small muted" }, l.sample + ", acq " + l.acq), h("td", { class: "prose" }, NB.formula(l.text)))))));
  const copyEntry = async () => {
    try {
      await navigator.clipboard.write([new ClipboardItem({ "text/plain": new Blob([d.entry.plain], { type: "text/plain" }),
        "text/html": new Blob([d.entry.html], { type: "text/html" }) })]);
    } catch {
      try { await navigator.clipboard.writeText(d.entry.plain); }
      catch {
        const text = h("textarea", { "aria-label": "Entry text to copy", value: d.entry.plain });
        entry.append(text); text.select();
        if (!document.execCommand("copy")) return NB.toast("Select and copy the entry text.", true);
        text.remove();
      }
    }
    NB.toast("Entry copied.");
  };
  const entry = h("div", { class: "prose", html: d.entry.html });
  const acquisitions = view.derived.acquisitions.flatMap(a => a.spectra.filter(s => d.proton_possible && s.nucleus === "1H").map(s => ({ ...s, folder: a.folder, sample: a.sample })));
  const capability = acquisitions.length ? await NB.capi("GET", "/nmr/meta") : {};
  const proposal = h("section", {});
  NB.setView(
    NB.experimentHead(view, "SI draft", [h("a", { href: "#/si" }, "All SI drafts"), h("a", { href: "#/exp/" + id }, "Experiment " + NB.expNo(id))]),
    h("h1", { class: "print-only" }, NB.formula(d.compound)),
    h("div", { class: "split" },
      h("section", {}, h("h2", {}, "SI entry"), entry, h("button", { class: "primary noprint", onclick: copyEntry }, "Copy entry")),
      h("aside", { class: "margin" }, h("h2", {}, "Working notes"),
        d.names_to_check?.length ? [h("h3", {}, "Names to check"), h("ul", {}, d.names_to_check.map(m =>
          h("li", {}, m.id + " · ", NB.formula(m.name), " · " + m.basis.package + " " + m.basis.version)))] : null,
        d.flags.length ? [h("h3", {}, "Open flags"), d.flags.map(f => h("p", {}, h("strong", {}, f.tier + " " + f.id + ". "), NB.formula(f.text)))] : null,
        d.missing.length ? [h("h3", {}, "Still missing"), h("ul", {}, d.missing.map(m => h("li", {}, m)))] : null,
        h("h3", {}, "Unassigned peak lists from the processed spectra"), d.lines.length ? list(d.lines) : h("p", {}, "No peak list to show."),
        d.excluded.length ? [h("h3", {}, "Signals that are not from this compound"), list(d.excluded)] : null,
        h("h3", {}, "How the lists were made"), d.notes.map(t => h("p", { class: "small" }, NB.formula(t))),
        h("h3", {}, "Sources"), [d.sources, d.basis, d.reviewed_basis || (d.reviewed.length ? "Reviewer not stated." : ""), d.result.basis].filter(Boolean).map(t => h("p", { class: "small" }, NB.formula(t))),
        h("a", { href: "#/exp/" + id + "/edit" }, "Enter reviewed lines on the edit page"), proposal)));
  if (!acquisitions.length) return;
  const sample = h("select", { "aria-label": "Sample and acquisition" }, acquisitions.map((a, i) => h("option", { value: i }, a.sample + ", acq " + a.acq)));
  const source = h("select", { "aria-label": "Spectrum source" }, h("option", { value: "topspin" }, "TopSpin's spectrum"),
    h("option", { value: "fid", disabled: !capability.fid_available }, "Raw FID, processed here"));
  const reference = h("select", { "aria-label": "Reference group" });
  const count = h("input", { type: "number", min: 1, step: 1, "aria-label": "Reference proton count" });
  const result = h("div", { "aria-live": "polite" });
  let sequence = 0;
  async function load(reset) {
    const mine = ++sequence, a = acquisitions[sample.value];
    if (reset) { NB.put(reference); count.value = ""; }
    const index = reference.value;
    NB.put(result, "Reading the spectrum…");
    try {
      const got = await NB.capi("POST", "/nmr/proposal", { folder: a.folder, acq: a.acq, processing: { source: source.value },
        reference_group: index === "" ? null : Number(index), count: count.value === "" ? null : Number(count.value) });
      if (mine !== sequence || !result.isConnected) return;
      if (reset || !reference.options.length) NB.put(reference, got.rows.map((r,i) => h("option", { value: i }, r.label + " ppm")));
      if (!got.rows.length) return NB.put(result, "No peak list to show.");
      NB.put(result, h("table", {}, h("thead", {}, h("tr", {}, ["δ (ppm)", "Multiplicity", "J (Hz)", "Relative integral", "H"].map(k => h("th", {}, k)))),
        h("tbody", {}, got.rows.map(r => h("tr", {}, [r.label, r.multiplicity, r.j.map(j => j.toFixed(1)).join(", "), r.relative.toFixed(2), r.protons ?? "–"].map(v => h("td", {}, v)))))),
        h("p", { class: "prose", html: got.html }), h("button", { class: "quiet", onclick: () => {
          NB.proposal = { id, case: NB.state.case, line: got.editor_line, basis: "Started from an app proposal (" + a.sample + ", acq " + a.acq + ", " + processingText(got.processing) + ")." };
          location.hash = "#/exp/" + id + "/edit";
        } }, "Copy to characterization editor"));
    } catch (err) { if (mine === sequence) NB.put(result, err.message); }
  }
  sample.onchange = source.onchange = () => load(true);
  reference.onchange = count.oninput = () => load(false);
  NB.put(proposal, h("h3", {}, "Proposal from the spectrum, not reviewed"), h("div", { class: "row" }, sample, source),
    h("div", { class: "row" }, h("label", {}, "Reference group ", reference), h("label", {}, "Reference proton count ", count)), result);
  load(true);
}]);
})();
