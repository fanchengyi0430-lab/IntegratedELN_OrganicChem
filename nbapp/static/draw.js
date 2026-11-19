/* Same-origin Ketcher adapter. All identities and notebook depictions come from RDKit. */
"use strict";
(() => {
  const h = NB.h;
  const post = (action, body) => NB.capi("POST", "/structures/" + action, body);
  NB.drawReason = () => NB.state.structureReason || (!NB.state.sketcher?.installed
    ? "Install Draw with py -3 packaging/build_sketcher.py." : "");
  const btn = (label, run, attrs = {}) => h("button", { type: "button", class: "quiet", ...attrs,
    onclick: e => { const control = e.currentTarget; return Promise.resolve().then(() => run(control)).catch(NB.fail); } }, label);
  const select = (label, items, current) => h("select", { "aria-label": label },
    items.map(([value, caption]) => h("option", { value, selected: value === current }, caption)));
  NB.drawScopes = ["all", "experiments", "reactions", "inventory", "library"];
  const switches = { stereo: "Stereoisomers", salts: "Salts and mixtures that contain it",
    isotopes: "Isotope-labelled forms", charge: "Other charge states" };
  let activeDialog;
  NB.drawDialog = function (opts) {
    if (activeDialog?.open) { activeDialog.focus(); return activeDialog; }
    if (NB.drawReason()) return NB.toast(NB.drawReason(), true);
    const search = opts.search;
    const frame = h("iframe", { title: "Chemical structure canvas", sandbox: "allow-scripts allow-same-origin allow-downloads",
      src: "/sketcher/index.html?disableMacromoleculesEditor=true" });
    const species = h("div", { class: "draw-species", "aria-live": "polite" }, "Loading the editor…");
    const feedback = h("div", { role: "status" }), choices = h("div", { class: "row draw-choices" }), leave = h("div", { role: "status" });
    const searchNote = h("span", { class: "small", role: "status" });
    const scope = select("Search in", NB.drawScopes.map(v => [v, v]), search?.scope || "all");
    const mode = select("Match", [["drawn", "As drawn"], ["substructure", "As substructure"], ["similarity", "Similar"]], search?.mode || "drawn");
    const role = select("Material role", ["any", "reactant", "product"].map(v => [v, v]), search?.role || "any");
    const threshold = h("input", { type: "number", min: 0, max: 1, step: 0.05, value: search?.threshold ?? 0.7 });
    const also = Object.entries(switches).map(([key, label]) => {
      const input = h("input", { type: "checkbox", checked: search?.switches?.includes(key) });
      return { key, input, label: h("label", { class: "checkline" }, input, label) };
    });
    let patternOnly = false;
    const options = () => { threshold.disabled = mode.value !== "similarity"; mode.disabled = patternOnly;
      also.forEach(v => { v.input.disabled = patternOnly; }); };
    mode.onchange = options; options();
    const editor = select("Editor", [["draw", "Draw here"]], "draw");
    editor.append(h("option", { value: "native", disabled: !opts.native }, opts.native ? "ChemDraw" : "ChemDraw — needs an experiment"));
    const term = h("input", { "aria-label": "Name, CAS number, SMILES or InChI", placeholder: "Name, CAS number, SMILES or InChI" });
    editor.disabled = true;
    let k, subscription, baseline, ready, timer, revision = 0, lookupRevision = 0, closed = false, moved = false, busy = false;
    const clean = () => {
      activeDialog = null; closed = true; revision++; lookupRevision++; clearTimeout(timer); clearTimeout(loadTimeout);
      if (subscription) k.editor.unsubscribe("change", subscription);
      window.removeEventListener("message", init);
      window.removeEventListener("hashchange", close);
    };
    function close() {
      if (closed) return;
      clean(); dialog.close(); dialog.remove();
      if (opts.opener?.isConnected) opts.opener.focus();
    }
    async function cancel() {
      if (busy) return;
      const n = revision;
      if (baseline === undefined || (await k.getKet() === baseline && n === revision)) return close();
      NB.put(leave, "Discard the changes to this drawing? ", btn("Keep drawing", () => NB.put(leave)), btn("Discard drawing", close));
    }
    const clear = btn("Clear", () => { k.editor.clear(); changed(); }, { disabled: true });
    const go = btn(search ? "Search" : "Use structure", async () => {
      if (!ready || busy) return;
      const result = ready;
      const settings = { scope: scope.value, mode: result.pattern ? "substructure" : mode.value, role: role.value,
        threshold: Number(threshold.value), switches: also.filter(v => !v.input.disabled && v.input.checked).map(v => v.key) };
      if (settings.mode === "similarity" && (!threshold.value || !threshold.checkValidity())) {
        threshold.reportValidity(); return;
      }
      busy = true; go.disabled = true;
      try {
        if (result.parsed.reaction && !result.pattern) {
          const parsed = await post("parse", { text: result.text, sketch: true });
          if (closed || ready !== result) return;
          result.parsed = parsed;
        }
        await opts.use(result, settings); close();
      }
      finally { busy = false; if (!closed && ready) go.disabled = false; }
    }, { class: "primary", disabled: true });
    async function native() {
      if (busy || !opts.native) return;
      busy = true; editor.disabled = true;
      try {
        if (k.editor.struct().isBlank() && opts.nativeSeed) await k.setMolecule(await opts.nativeSeed());
        const source = !k.editor.struct().isBlank() ? {
          draft: await k.getCDXml(), expected: await (k.containsReaction() ? k.getRxn() : k.getMolfile()) } : {};
        await opts.native(source); close();
      } catch (err) { feedback.textContent = err.message; }
      finally { editor.disabled = false; editor.value = "draw"; busy = false; }
    }
    editor.onchange = () => { if (editor.value === "native") native(); };
    const maximise = btn("Maximise", () => {
      const full = dialog.classList.toggle("maximised"); maximise.textContent = full ? "Restore size" : "Maximise";
      maximise.setAttribute("aria-pressed", String(full));
    });
    const add = btn("Add to drawing", convert, { disabled: true });
    term.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); add.click(); } };
    term.oninput = () => { lookupRevision++; NB.put(choices); feedback.textContent = ""; };
    async function convert() {
      const generation = ++lookupRevision, query = term.value.trim();
      NB.put(choices); feedback.textContent = "";
      if (!query || !k) return;
      const current = () => !closed && generation === lookupRevision;
      const append = async row => {
        if (!current()) return;
        // Ketcher aligns the incoming fragment's minimum corner with position. The
        // rendered bounds include arrowheads, plus signs, text and images in model units.
        const bounds = !k.editor.struct().isBlank() && k.editor.render.ctab.getVBoxObj({});
        const position = bounds ? { x: bounds.p1.x + 3, y: -bounds.p0.y } : null;
        await k.addFragment(row.molfile || row.smiles, position ? { position } : undefined);
        if (!closed) changed();
        if (current()) { term.value = ""; feedback.textContent = "Added from " + row.source + "."; NB.put(choices); }
      };
      try {
        const { rows } = await post("resolve", { query });
        if (!current()) return;
        if (rows.length === 1) return await append(rows[0]);
        if (rows.length) {
          feedback.textContent = "Choose a notebook match.";
          NB.put(choices, rows.map(row => btn((row.name || row.smiles) + " · " + row.source, () => append(row))));
        } else if (NB.state.reference_lookup === "pubchem") {
          feedback.textContent = "Search PubChem sends this name or CAS number to the US National Institutes of Health. Keep unpublished compounds private.";
          NB.put(choices, btn("Search PubChem", async () => {
            NB.put(choices);
            try {
              const result = await NB.api("POST", "/api/lookup", { query });
              const id = result.identity, smiles = id.SMILES || id.IsomericSMILES || id.ConnectivitySMILES || id.CanonicalSMILES;
              if (!smiles) throw Error("PubChem returned no structure.");
              const local = await post("resolve", { query: smiles });
              if (!local.rows[0]?.molfile) throw Error("The local engine could not read the PubChem structure.");
              await append({ ...local.rows[0], source: "PubChem CID " + result.cid });
            } catch (err) { if (current()) feedback.textContent = err.message; }
          }));
        } else feedback.textContent = "No notebook match. With look-up off this name cannot be resolved.";
      } catch (err) { if (current()) feedback.textContent = err.message; }
    }
    const panel = search && h("aside", { class: "draw-options" }, h("label", { class: "f" }, "Match", mode),
      h("label", { class: "f" }, "Tanimoto threshold", threshold), !search.bottlesOnly && h("label", { class: "f" }, "Role", role),
      h("fieldset", {}, h("legend", {}, "Also match"), also.map(v => v.label)));
    const dialog = h("dialog", { class: "draw-dialog noprint", "aria-label": "Draw a structure" },
      h("header", { class: "row" }, h("h2", {}, "Draw a structure"), editor, maximise, btn("Close", cancel)),
      search && !search.bottlesOnly && h("div", { class: "row" }, h("label", {}, "Search in ", scope), searchNote),
      h("div", {}, h("div", { class: "row draw-convert" }, term, add), choices, feedback),
      opts.note && h("div", { class: "note" }, opts.note),
      h("div", { class: "draw-work" }, frame, panel), species, h("footer", { class: "row" }, clear, leave, btn("Cancel", cancel), go));
    dialog.addEventListener("cancel", e => { e.preventDefault(); cancel().catch(NB.fail); });
    dialog.addEventListener("keydown", e => {
      if (e.key !== "Tab") return;
      const els = dialog.querySelectorAll("button:enabled,select:enabled,input:enabled,iframe");
      const first = els[0], last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    async function refresh(n) {
      const current = () => revision === n && !closed;
      try {
        const arrow = k.containsReaction();
        if (arrow && search?.bottlesOnly) { species.textContent = "Draw a molecule to search the inventory."; return; }
        if (arrow && search && !moved) { scope.value = "reactions"; moved = true; searchNote.textContent = "Arrow added. Searching reactions."; }
        if (k.editor.struct().isBlank()) { species.textContent = "Empty drawing."; return; }
        const [ket, text] = await Promise.all([k.getKet(), arrow ? k.getRxn() : k.getMolfile()]);
        if (!current()) return;
        const parsed = await post("parse", { text, sketch: true, speciesOnly: true });
        if (!current()) return;
        const errors = parsed.errors || [];
        const fragments = errors.filter(e => typeof e.position === "number");
        const query = fragments.some(e => e.query);
        const rows = parsed.molecules;
        NB.put(species, rows.map(m => h("span", {}, rows.length > 1 || arrow ? m.role + " · " : "", NB.formula(m.formula),
          " · " + (m.mw == null ? m.warning : m.mw.toFixed(3) + " g/mol"))),
          errors.map(e => h("span", { class: "note caution" }, "Fragment " + e.position + " · " + e.reason)));
        let pattern, svg;
        if (query && search && fragments.every(e => e.query)) {
          pattern = await k.getSmarts();
          const depiction = await post("pattern", { query: pattern });
          if (!current()) return;
          svg = depiction.svg; patternOnly = true; mode.value = "substructure"; options();
          species.append(h("span", {}, "Searching as SMARTS. The pattern sets its own matching rules."));
        } else if (!rows.length || fragments.length || (!search && errors.length)) return;
        ready = { ket, text, parsed, arrow, pattern, svg: svg || parsed.svg || rows[0]?.svg };
        go.disabled = false;
      } catch (err) { if (current()) species.textContent = err.message || String(err); }
    }
    function changed() {
      const n = ++revision;
      patternOnly = false; options(); ready = null; go.disabled = true; clearTimeout(timer);
      species.textContent = "Reading drawing…";
      timer = setTimeout(() => refresh(n), 90);
    }
    async function init(e) {
      if (k || closed || e.origin !== location.origin || e.source !== frame.contentWindow || e.data?.eventType !== "init") return;
      k = frame.contentWindow.ketcher;
      if (!k) return;
      clearTimeout(loadTimeout);
      try {
        if (opts.initial) await k.setMolecule(opts.initial);
        if (closed) return;
        baseline = await k.getKet();
        if (opts.initial && k.containsReaction()) moved = true;
        subscription = k.editor.subscribe("change", changed);
        frame.contentDocument.addEventListener("keydown", e => {
          if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); cancel().catch(NB.fail); }
        });
        editor.disabled = clear.disabled = add.disabled = false;
        if (opts.startNative) await native(); else changed();
      } catch (err) { species.textContent = err.message; }
    }
    const loadTimeout = setTimeout(() => { species.textContent = "The structure editor did not finish loading. Close and reopen Draw."; }, 30000);
    window.addEventListener("message", init);
    window.addEventListener("hashchange", close);
    activeDialog = dialog;
    document.body.append(dialog); dialog.showModal(); editor.focus();
    return dialog;
  };
})();
