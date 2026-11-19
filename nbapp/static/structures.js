/* Local ChemDraw text, shared species preview, library and structure search. */
"use strict";
(() => {
  const h = NB.h;
  const post = (action, body) => NB.capi("POST", "/structures/" + action, body);
  const button = (label, run) => h("button", { type: "button", class: "quiet", onclick: async e => {
    e.stopPropagation();
    const btn = e.currentTarget;
    btn.disabled = true;
    try { await run(btn); } catch (error) { NB.fail(error); } finally { btn.disabled = false; }
  } }, label);
  const smallImage = (svg, alt) => h("img", { class: "molecule", alt, src: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg) });
  const table = (headers, rows) => h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, headers.map(title => h("th", {}, title)))),
    h("tbody", {}, rows.map(row => h("tr", {}, row.map(cell => h("td", {}, cell)))))));
  const colourKey = "nb-colour-structure-change";
  function scheme(plain, coloured, reason, alt, open, onload) {
    const img = h("img", { alt, onload, ondblclick: open });
    const check = h("input", { type: "checkbox", checked: localStorage.getItem(colourKey) !== "off" });
    const draw = () => { img.src = coloured && check.checked ? coloured : plain; };
    check.onchange = () => { localStorage.setItem(colourKey, check.checked ? "on" : "off"); draw(); };
    draw();
    return h("div", { class: "scheme" }, img, coloured ? h("label", { class: "checkline noprint change-choice" },
      check, "Colour the change") : null, reason ? h("p", { class: "muted small" }, reason) : null);
  }
  NB.recordScheme = (view, open, onload) => {
    const d = view.derived, opts = d.scheme_options;
    if (d.scheme_preview) {
      const png = data => data && "data:image/png;base64," + data;
      const drawing = d.scheme_preview;
      return scheme(png(drawing.plain), png(drawing.colour), drawing.reason, "Reaction scheme", open, onload);
    }
    return d.scheme ? scheme(NB.fileUrl(opts?.plain || d.scheme), opts?.colour && NB.fileUrl(opts.colour),
      opts?.reason, view.record.scheme_alt || "Reaction scheme", open, onload) : null;
  };
  NB.isSketch = (rec, source) => !!source && (source.endsWith(".ket") ||
    rec?.attachments?.some(a => a.path === source && a.kind === "sketch"));
  NB.schemeEditButtons = (sketch, draw, native) => sketch ? [draw, native] : [native, draw];
  NB.materialDrawing = (view, row, edit, drafts = []) => {
    const smiles = row.smiles || view.record.smiles?.[row.id];
    if (!smiles) return null;
    const pending = drafts.slice().reverse().find(d => d.material_ids?.includes(row.id));
    const svg = pending?.images?.[row.id] || view.derived.material_drawings?.[row.id];
    const picture = svg && smallImage(svg, row.name || row.formula || "Material structure");
    if (picture) picture.ondblclick = () => edit(null, primary);
    const drawn = pending ? !!pending.ket : NB.isSketch(view.record, row.drawing);
    const control = (method, label) => h("button", { type: "button", class: "quiet noprint", "data-edit-material": row.id, "data-editor": method,
      disabled: !!(method === "draw" || drawn ? NB.drawReason() : NB.state.structureReason),
      title: method === "draw" || drawn ? NB.drawReason() : NB.state.structureReason,
      onclick: e => edit(method, e.currentTarget) }, label);
    const primary = control(drawn ? "draw" : "native", drawn ? "Edit in Draw" : "Edit in ChemDraw");
    return h("div", { class: "draw-picture" }, picture, primary,
      control(drawn ? "native" : "draw", drawn ? "Edit in ChemDraw" : "Edit in Draw"));
  };
  const prefix = role => ({ product: "P", agent: "A" })[role] || "R";
  NB.keyNotice = "Only the InChIKey goes to PubChem at the U.S. National Institutes of Health. It is a fingerprint of the structure. PubChem can identify compounds it already holds. The structure cannot be read back from the key, though someone who guessed it could confirm the guess.";
  NB.nameBasisText = basis => {
    if (!basis || basis.kind === "entered") return "";
    if (basis.kind === "generated") return "generated, not checked · " + basis.package + " " + basis.version;
    if (basis.kind === "notebook") return "In this notebook · " + basis.source +
      (basis.generated ? " · " + NB.nameBasisText(basis.generated) : "");
    if (basis.kind === "pubchem") return "PubChem CID " + basis.cid + " · " + basis.date;
    return "ChemDraw";
  };
  function clearChangedBottle(row, bottle) {
    const old = row.bottle;
    if (old && bottle && ["barcode", "product", "location", "name"].some(k => old[k] !== bottle[k])) {
      for (const k of ["assay", "density", "density_basis"]) delete row[k];
    }
  }
  NB.linkBottle = (row, item) => {
    const bottle = {};
    for (const k of ["name", "supplier", "product", "location", "barcode"]) if (item[k]) bottle[k] = item[k];
    if (item.remaining) bottle.remaining = [item.remaining, item.unit].filter(Boolean).join(" ");
    clearChangedBottle(row, bottle);
    row.bottle = bottle;
    if (!row.name) row.name = item.name;
    const assay = Number(String(item.assay || "").replace(/\s*%$/, ""));
    if (assay > 0 && assay <= 100) row.assay = assay;
    const density = Number(String(item.density || "").replace(/\s*g\s*\/\s*mL$/i, ""));
    if (density > 0 && Number.isFinite(density)) {
      row.density = density;
      row.density_basis = "Inventory bottle " + (item.barcode || item.product || item.name);
    }
  };
  const material = m => ({ name: m.label || "", smiles: m.smiles, inchikey: m.inchikey, formula: m.formula,
    ...(m.mw == null ? {} : { mw: m.mw }), ...m.selection });
  function chooseMatch(m, hit) {
    m.nameEdited = false;
    m.match = hit;
    m.selection = { name: hit?.name || "" };
    if (!hit) return;
    if (hit.cas) m.selection.cas = hit.cas;
    if (hit.bottle) NB.linkBottle(m.selection, hit.bottle);
    if (hit.name) m.selection.name_basis = { kind: "notebook", source: hit.source,
      ...(hit.generated ? { generated: hit.generated } : {}) };
  }
  function identifyRow(m, result) {
    m.nameEdited = false;
    m.identity = result;
    m.selection = m.label ? { name: m.label, name_basis: { kind: "entered" } } : { name: "" };
    m.saveCompound = ["new", "unsearched"].includes(result.state);
    if (result.state === "notebook") {
      const names = new Set(result.matches.map(hit => hit.name));
      const bottles = result.matches.filter(hit => hit.bottle);
      chooseMatch(m, names.size === 1 && bottles.length <= 1 ? bottles[0] || result.matches[0] : null);
    }
    if (result.state === "pubchem") {
      m.selection = { name: result.name, pubchem_cid: result.pubchem_cid };
      if (result.name) m.selection.name_basis = result.name_basis;
      if (result.cas) m.selection.cas = result.cas;
    }
    if (result.state === "conflict") m.selection = { name: "" };
  }
  const code = row => (row.role || String(row.id || "R")[0]).replace("S", "A");

  // A single unmatched pair of the same role can be shown as changed. Keep ambiguous additions/removals separate.
  function reconcile(existing, species, previous, target) {
    if (target && species.length === 1) {
      const old = existing.find(r => r.id === target.id);
      const m = species[0];
      return { pairs: [{ m, old, exact: !!old && (old.smiles === m.smiles || old.inchikey === m.inchikey) }],
        removed: [], keep: existing.filter(r => r !== old) };
    }
    const structured = existing.filter(row => previous?.some(m => (!m.id || m.id === row.id) && (m.role === "none" || code(row) === prefix(m.role)) &&
      (m.smiles === row.smiles || (row.inchikey && m.inchikey === row.inchikey))));
    const remaining = structured.slice();
    const pairs = species.map(m => {
      const i = remaining.findIndex(r => code(r) === prefix(m.role) && (r.inchikey === m.inchikey || r.smiles === m.smiles));
      return { m, old: i < 0 ? null : remaining.splice(i, 1)[0], exact: i >= 0 };
    });
    for (const pair of pairs.filter(p => !p.old)) {
      const i = remaining.findIndex(r => code(r) === prefix(pair.m.role));
      const sameRole = m => prefix(m.role) === prefix(pair.m.role);
      if (i >= 0 && remaining.filter(r => code(r) === prefix(pair.m.role)).length === 1 &&
          pairs.filter(p => !p.old && sameRole(p.m)).length === 1) pair.old = remaining.splice(i, 1)[0];
    }
    return { pairs, removed: remaining, keep: existing.filter(r => !structured.includes(r) && (r.name || r.formula || r.smiles || r.bottle || r.amount || r.note)) };
  }
  NB.importSpecies = function (existing, species, previous, plan, target) {
    const { pairs, keep } = reconcile(existing, species, previous, target);
    const used = new Set(existing.map(r => r.id));
    const next = role => {
      let n = 1;
      while (used.has(role + n)) n++;
      used.add(role + n);
      return role + n;
    };
    let first = true;
    return [...pairs.map(({ m, old, exact }) => {
      const role = prefix(m.role);
      const row = { ...old };
      if (old && !exact) {
        for (const key of ["drawing", "cas", "pubchem_cid", "bottle", "assay", "density", "density_basis", "name_basis"]) delete row[key];
        if (m.mw == null) delete row.mw;
        row.check_name = true;
      }
      if (m.selection && !m.selection.name_basis) delete row.name_basis;
      clearChangedBottle(row, m.selection?.bottle);
      Object.assign(row, material(m));
      if (old && !m.selection && !m.label) row.name = old.name || "";
      if (m.nameEdited || m.selection?.name && ["notebook", "pubchem", "chemdraw"].includes(m.selection.name_basis?.kind)) delete row.check_name;
      if (old && !exact) {
        if (!plan && !String(old.id).startsWith("S") && NB.plannedCharge) {
          const basis = existing.find(r => code(r) === "R" && r.equiv > 0 && r.mmol > 0);
          const mmol = old.mmol ?? (basis && old.equiv > 0 ? basis.mmol / basis.equiv * old.equiv : null);
          if (mmol > 0) {
            const charge = NB.plannedCharge({ ...row, role, equiv: 1, factor: 1 }, mmol);
            row.mmol = charge.mmol;
            if (charge.amount) row.amount = charge.amount; else delete row.amount;
          }
        }
      }
      if (plan) row.role = role;
      else row.id = old?.id || next(role);
      if (role === "R" && first) { if (row.equiv == null) row.equiv = 1; first = false; }
      if (role === "P" && plan) row.factor = row.factor || 1;
      return row;
    }), ...keep];
  };

  function dropZone(onText, reason) {
    const hint = "In ChemDraw choose Edit, Copy As, CDXML Text (or SMILES).";
    const status = h("p", { class: "small", role: "status" }, reason || hint);
    const input = h("input", { type: "file", accept: ".cdxml,.mol,.sdf,.rxn,.smi", disabled: !!reason, "aria-label": "Choose a structure file" });
    const zone = h("div", { class: "structure-drop", tabindex: reason ? -1 : 0, "aria-disabled": String(!!reason),
      "aria-label": "Paste structure text or drop a structure file" }, "Paste structure text here or drop a file.", input, status);
    async function readFile(file) {
      if (!file || !/\.(cdxml|mol|sdf|rxn|smi)$/i.test(file.name)) throw Error("Choose a CDXML, MOL, SDF, RXN or SMI file.");
      if (file.size > 2097152) throw Error("Structure text exceeds 2 MB.");
      await onText(await file.text(), file.name);
    }
    const run = async action => {
      if (reason) return;
      try { status.textContent = "Reading structures…"; await action(); status.textContent = hint; }
      catch (err) { status.textContent = err.message; }
    };
    input.onchange = () => { const file = input.files[0]; input.value = ""; run(() => readFile(file)); };
    zone.onpaste = e => {
      e.preventDefault();
      const text = e.clipboardData?.getData("text/plain");
      if (reason) return;
      if (!text) { status.textContent = "The clipboard has no structure text. " + hint; return; }
      run(() => onText(text, ""));
    };
    zone.ondragover = e => e.preventDefault();
    zone.ondrop = e => { e.preventDefault(); run(() => readFile(e.dataTransfer.files[0])); };
    return zone;
  }

  NB.structureBox = function (opts) {
    const preview = h("div", {}), activity = h("div", { role: "status" });
    const reason = NB.state.structureReason;
    const picture = h("div", { class: "draw-picture" });
    let lastDrawing, target, prior, nativeContext;
    const box = h("fieldset", {}, h("legend", {}, "Chemical structures"));
    let generation = 0, session, digest, timer, previous, previewDraft, pending = false;
    let naming, namingTimer;
    const sessionKey = "nb-chemdraw:" + NB.state.case + ":" + (opts.sessionKey || opts.id || "plan");
    const namingKey = sessionKey + ":name";
    const nameActivity = h("div", { role: "status" });
    async function closeNameCopy() {
      if (!naming) return;
      try { await post("discard", { session: naming }); }
      catch (err) { if (!err.message.includes("Unknown ChemDraw")) throw err; }
      endNameCopy();
    }
    function endNameCopy() {
      clearTimeout(namingTimer); naming = null; sessionStorage.removeItem(namingKey); NB.put(nameActivity);
    }
    async function nameInChemDraw(m, done) {
      if (naming) throw Error("Finish or discard the open naming copy first.");
      const gen = generation;
      naming = "opening";
      let token;
      try { ({ session: token } = await post("open", { id: opts.id || null, draft: m.smiles })); }
      catch (err) { endNameCopy(); throw err; }
      naming = token; sessionStorage.setItem(namingKey, token);
      if (generation !== gen) { await closeNameCopy(); return; }
      const discardName = button("Discard naming copy", closeNameCopy);
      let reviewed;
      const pollName = async () => {
        if (naming !== token || !box.isConnected) return;
        if (generation !== gen) { await closeNameCopy(); return; }
        try {
          const r = await post("poll", { session: token, digest: reviewed });
          if (naming !== token) return;
          if (r.changed) {
            reviewed = r.digest;
            const mols = r.preview.molecules, label = (mols[0]?.caption || mols[0]?.label)?.trim();
            const valid = !r.preview.errors.length && mols.length === 1 && mols[0].inchikey === m.inchikey && label;
            NB.put(nameActivity, valid ? NB.formula(label) : "Save one matching structure with its ChemDraw name.",
              valid ? button("Use ChemDraw name", async () => {
                const accepted = await post("accept", { session: token, digest: r.digest });
                endNameCopy();
                if (gen !== generation) return;
                m.selection = { ...m.selection, name: label, name_basis: { kind: "chemdraw" } };
                m.nameDrawing = accepted.text; done();
              }) : null, discardName);
          }
        } catch (err) { if (naming === token) NB.put(nameActivity, err.message, discardName); }
        if (naming === token) namingTimer = setTimeout(() => pollName().catch(NB.fail), 1500);
      };
      NB.put(nameActivity, "Use Convert Structure to Name in ChemDraw, then save and close the copy. ", discardName);
      namingTimer = setTimeout(() => pollName().catch(NB.fail), 1000);
    }
    const currentDraft = () => opts.drafts?.().slice(-1)[0];
    const schemeDraft = () => opts.drafts?.().slice().reverse().find(d => d.schemeState);
    function schemeState() {
      const rec = opts.record?.() || opts.view?.record;
      const saved = schemeDraft()?.schemeState || { smiles: rec?.reaction?.smiles,
        external: !!(opts.view?.derived.scheme && !opts.view.derived.scheme_options) };
      if (rec?.scheme_image && rec.scheme_image !== opts.view?.record.scheme_image) {
        const owned = rec.attachments?.some(a => a.path === rec.scheme_image && a.kind === "scheme" && a.note?.startsWith("RDKit reaction scheme. "));
        return { ...saved, external: !owned };
      }
      return saved;
    }
    const schemeSourceIsSketch = () => schemeDraft() ? !!(schemeDraft().target || schemeDraft().ket) :
      NB.isSketch(opts.view?.record, opts.view?.record.reaction?.drawing);
    const diff = (species, edited, previous, target) => {
      if (!edited || !opts.rows) return null;
      const { pairs, removed } = reconcile(opts.rows(), species, previous, target);
      const details = [];
      for (const { m, old, exact } of pairs) {
        if (!old) details.push("Added " + (m.label || m.formula) + " (" + m.role + "), " + m.formula + ", " + (m.mw ?? "—") + " g/mol.");
        else if (!exact || old.formula !== m.formula || Math.abs((old.mw || 0) - (m.mw || 0)) > 0.001)
          details.push("Changed " + (old.id || old.name || old.formula) + " · " + (old.formula || "—") + " → " + m.formula +
            ", " + (old.mw ?? "—") + " → " + (m.mw?.toFixed(3) ?? "—") + " g/mol.");
      }
      removed.forEach(r => details.push("Removed " + (r.name || r.id || r.formula) + ", " + r.formula + ", " + (r.mw ?? "—") + " g/mol."));
      const rec = opts.view?.record;
      for (const row of [...pairs.filter(p => p.old && !p.exact).map(p => p.old), ...removed]) {
        const data = [];
        const actuals = Object.entries(rec?.entries || {}).filter(([tag, value]) =>
          value && (tag.toLowerCase().includes("_" + String(row.id).toLowerCase() + "_") || tag.toLowerCase().endsWith("_" + String(row.id).toLowerCase())));
        if (actuals.length) data.push("measured entries " + actuals.map(([tag]) => tag).join(", "));
        if (rec?.runs?.some(r => r.measured != null)) data.push("measured run values");
        if (rec?.result?.text || rec?.runs?.some(r => r.result) || /%/.test(rec?.key_result || "") ||
            Object.keys(rec?.entries || {}).some(k => /yield|isolated/.test(k))) data.push("reported yield or result");
        if (rec?.characterization?.length) data.push("characterization");
        if (data.length) details.push((row.id || row.name) + " · Review the existing " + data.join(", ") + " before accepting.");
      }
      return h("div", { class: "note" }, details.length ? details.map(line => h("p", {}, NB.formula(line))) : "No structural changes to the selected materials.");
    };
    function clearSession() {
      sessionStorage.removeItem(sessionKey); sessionStorage.removeItem(sessionKey + ":context");
      session = digest = null;
      clearTimeout(timer);
      NB.put(activity);
    }
    async function discard() {
      await post("discard", { session });
      generation++;
      previewDraft = null;
      clearSession(); NB.put(preview);
    }
    async function show(parsed, draft, working) {
      const shownDigest = digest;
      const applyToDraft = opts.apply || opts.drawApply;
      const review = working || draft.review;
      const before = working ? nativeContext?.prior || previous : prior;
      const rowTarget = working ? nativeContext?.target : target;
      const kinds = ["reactant", "agent", "product"];
      const species = parsed.molecules.map(m => ({ ...m }));
      if (applyToDraft && (draft.ket || working) && !parsed.identities) {
        const gen = generation;
        const result = await post("parse", { text: draft.text, step: draft.step, sketch: !!draft.ket, speciesOnly: true, identify: "preview" });
        if (generation !== gen) return;
        parsed.identities = result.identities;
      }
      parsed.identities?.forEach((result, i) => identifyRow(species[i], result));
      const originalScheme = schemeState();
      let change;
      if (rowTarget && species.length === 1 && !parsed.reaction) {
        species[0].role = ({ P: "product", A: "agent" })[code(rowTarget)] || "reactant";
        species[0].lockedRole = true;
        const gen = generation;
        change = await post("material-change", { target: rowTarget.id, name: rowTarget.name, before: rowTarget.smiles, after: species[0].smiles,
          reaction: originalScheme.smiles, external: originalScheme.external });
        if (generation !== gen) return;
      }
      const order = [...species.keys()];
      const roles = () => Object.fromEntries(kinds.map(role => [role, order.filter(i => species[i].role === role)]));
      const checks = species.map(m => h("input", { type: "checkbox", checked: m.lockedRole || ["reactant", "product"].includes(m.role),
        disabled: !kinds.includes(m.role), "aria-label": "Add as material " + (m.label || m.formula) + ", species " + m.position }));
      const checked = () => order.filter(i => checks[i].checked).map(i => species[i]);
      const selectedFocus = r => ["reactant", "product"].map(role => r[role].find(i => checks[i].checked) ?? -1);
      const differences = h("div", {}), imageBox = h("div", {}), speciesTable = h("div", {});
      const notes = h("div", {}, (parsed.notes || []).map(note => h("p", { class: "note" }, note)));
      const replacement = h("div", {});
      const replace = h("input", { type: "checkbox", checked: !!(review && !rowTarget && opts.view?.derived.scheme_options) });
      let reaction = parsed.reaction, drawing = parsed.scheme, request = 0;
      let focus = selectedFocus(roles());
      let ready = true, searching = 0;
      const apply = applyToDraft && button(working ? "Accept ChemDraw changes" : review ? "Accept drawing changes" : opts.drawApply ? "Use selected material" : "Add to draft", async () => {
        if (!ready || searching) return;
        if (naming) throw Error("Use the ChemDraw name or discard its working copy first.");
        const accepted = working ? await post("accept", { session, digest: shownDigest }) : {};
        if (working) clearSession();
        previewDraft = { ...draft, ...accepted, roles: roles(), focus, replace: replace.checked };
        previewDraft.names = Object.fromEntries(checked().map(m => [m.position, m.selection?.name ?? m.label]));
        previewDraft.library = species.filter(m => m.saveCompound).map(m => ({ position: m.position, ...m.selection }));
        previewDraft.name_drawings = Object.fromEntries(species.filter(m => m.nameDrawing).map(m => [m.position, m.nameDrawing]));
        if (change?.smiles) previewDraft.schemeState = { smiles: change.smiles, external: false };
        else if (!rowTarget && reaction) previewDraft.schemeState = { smiles: reaction.smiles, external: originalScheme.external && !replace.checked };
        applyToDraft(checked(), previewDraft, review ? before : null, rowTarget);
        refreshEditButtons();
        if (change?.scheme) NB.put(savedScheme, previewScheme(change.scheme));
        lastDrawing = null; NB.put(picture);
        NB.put(preview, imageBox, change?.mismatch && h("p", { class: "note caution" }, change.message),
          h("p", { class: "muted" }, "Structure added to the draft. Save the experiment to keep the source."));
      });
      const transform = opts.transform && button("Use transformation", () => {
        const r = reaction.roles;
        opts.query(species[r.reactant[0]].smiles + ">>" + species[r.product[0]].smiles, true);
      });
      const display = () => {
        const png = data => data && "data:image/png;base64," + data;
        NB.put(imageBox, drawing ? scheme(png(drawing.plain), png(drawing.colour), drawing.reason,
          "Reaction preview", opts.apply ? () => draft.ket ? draw(drawButton, { initial: draft.ket, row: rowTarget, review }) : open().catch(NB.fail) : null) : null, reaction ? h("code", {}, reaction.smiles) : null);
        NB.put(differences, diff(checked(), review, before, rowTarget), change?.message ?
          h("p", { class: change.mismatch ? "note caution" : "note" }, change.message) : null);
        NB.put(replacement, !rowTarget && opts.hasScheme && drawing ? h("label", { class: "checkline" }, replace, "Use this drawing as the experiment scheme") :
          !rowTarget && review && opts.view?.derived.scheme_options && before?.some(m => m.role === "product") ? h("label", { class: "checkline" }, replace, "Remove the previous generated scheme") : null);
        if (apply) apply.disabled = !ready || !!searching || (!reaction && !checked().length) || !!(rowTarget && (checked().length !== 1 || reaction));
        if (transform) transform.disabled = !ready || !reaction;
      };
      const update = async () => {
        const current = ++request;
        const assigned = roles();
        focus = selectedFocus(assigned);
        previewDraft = { ...draft, roles: assigned, focus };
        drawing = reaction = null;
        ready = !assigned.reactant.length || !assigned.product.length;
        display();
        if (ready) return;
        NB.put(imageBox, "Updating reaction preview…");
        try {
          const updated = await post("parse", { text: draft.text, step: draft.step, roles: assigned, focus, sketch: !!draft.ket });
          if (current !== request) return;
          reaction = updated.reaction; drawing = updated.scheme; ready = true; display();
        } catch (err) { if (current === request) NB.put(imageBox, err.message); }
      };
      const setRole = (i, role) => {
        species[i].role = role;
        checks[i].disabled = role === "none";
        checks[i].checked = role === "reactant" || role === "product";
      };
      const saveToLibrary = async positions => {
        const result = await post("library", { ...draft, positions });
        NB.toast(result.added + " compounds added to this notebook.");
      };
      const move = (place, delta) => {
        const other = place + delta;
        const control = h("button", { type: "button", class: "quiet", disabled: other < 0 || other >= order.length,
          "aria-label": "Move species " + species[order[place]].position + (delta < 0 ? " up" : " down"), onclick: () => {
            [order[place], order[other]] = [order[other], order[place]];
            NB.put(notes); renderTable(); update();
          } }, delta < 0 ? "↑" : "↓");
        return control;
      };
      function knownAs(m) {
        const r = m.identity;
        if (!r) return "";
        const state = { notebook: "In this notebook", pubchem: "PubChem", new: "New compound",
          unsearched: "Not looked up", conflict: "PubChem formula conflict" }[r.state];
        const group = [h("strong", {}, state), r.date && h("div", { class: "small" }, r.date)];
        for (const hit of r.close) group.push(h("div", { class: "small" }, "Close match · ", NB.formula(hit.name),
          " · " + hit.source + " · " + hit.difference));
        if (r.reason) group.push(h("p", { class: "small" }, r.reason));
        if (r.matches) {
          const caption = hit => [hit.name || "(unnamed)", hit.cas, hit.source].filter(Boolean).join(" · ");
          if (r.matches.length === 1) group.push(h("div", {}, NB.formula(caption(r.matches[0]))));
          else group.push(h("select", { "aria-label": "Notebook source for species " + m.position, onchange: e => {
            chooseMatch(m, r.matches[e.target.value]); renderTable();
          } }, h("option", { value: "", selected: !m.match }, "Choose a notebook source"),
          r.matches.map((hit, i) => h("option", { value: i, selected: m.match === hit }, caption(hit)))));
        }
        if (r.state === "pubchem") group.push(h("div", {}, ["CID " + r.pubchem_cid, r.cas].filter(Boolean).join(" · ")));
        const proposal = r.proposal;
        if (proposal?.name) group.push(h("div", {}, NB.formula(proposal.name)),
          h("small", {}, NB.nameBasisText(proposal.name_basis)), button("Use generated name", () => {
            m.nameEdited = false; m.selection = { name: proposal.name, name_basis: proposal.name_basis }; renderTable();
          }));
        else if (proposal?.reason) group.push(h("div", { class: "small" }, proposal.reason));
        group.push(h("input", { value: m.selection.name, type: "text", "aria-label": "Name for species " + m.position,
          oninput: e => { m.nameEdited = true; m.selection.name = e.target.value; m.selection.name_basis = { kind: "entered" }; } }));
        if (r.state === "new" || r.state === "unsearched" || r.state === "conflict") group.push(
          button(r.state === "unsearched" ? "Look up in PubChem" : "Check again", async () => {
            const gen = generation;
            searching++; display();
            try {
              const found = await post("parse", { text: m.smiles, speciesOnly: true, identify: r.state === "unsearched" ? "once" : "refresh" });
              if (gen !== generation) return;
              const result = found.identities[0];
              if (["new", "unsearched"].includes(result.state) && ["new", "unsearched"].includes(r.state)) {
                m.identity = result;  // A second miss keeps the researcher's name and library choice.
              } else identifyRow(m, result);
              renderTable();
            } finally { searching--; display(); }
          }));
        group.push(button("Name it in ChemDraw", () => nameInChemDraw(m, renderTable)));
        return group;
      }
      function renderTable() {
        NB.put(speciesTable, table([applyToDraft ? "Add as material" : "Use structure", "Structure", ...(applyToDraft ? ["Known as"] : []), "Role", "Order", "Formula", "MW (g/mol)", "Neutral monoisotopic mass (Da)", "SMILES", "Library"],
          order.map((i, place) => {
            const m = species[i];
            const role = h("select", { disabled: !!m.lockedRole, "aria-label": "Role for species " + m.position, onchange: e => {
              setRole(i, e.target.value); NB.put(notes); update();
            } }, ["none", ...kinds].map(r => h("option", { value: r, selected: r === m.role }, r)));
            return [applyToDraft ? [checks[i], opts.drawApply && button("Filter library", () => opts.query(m.smiles, false))] : button("Use", () => opts.query(m.smiles, false)),
              [smallImage(m.svg, m.label || m.formula), NB.formula(m.label), h("span", { class: "small" }, "Species " + m.position)],
              ...(applyToDraft ? [knownAs(m)] : []),
              role, [move(place, -1), move(place, 1)], NB.formula(m.formula), m.mw?.toFixed(3) ?? m.warning,
              [m.mass?.toFixed(6) || "—", h("div", { class: "small muted" }, m.basis)], h("code", {}, m.smiles),
              applyToDraft ? h("label", {}, h("input", { type: "checkbox", checked: m.saveCompound,
                onchange: e => { m.saveCompound = e.target.checked; } }), "Save to library") : button("Save compound", () => saveToLibrary([m.position]))];
          })));
      }
      checks.forEach(c => { c.onchange = () => {
        if (selectedFocus(roles()).some((v, i) => v !== focus[i])) update(); else display();
      }; });
      if (parsed.proposal) {
        const suggestion = parsed.proposal;
        notes.append(h("p", {}, "Proposed roles by species number · ", kinds.map(r =>
          r + " " + (suggestion[r].map(i => species[i].position).join(", ") || "none")).join(" · ")),
          button("Confirm proposed roles", () => {
            for (const r of kinds) for (const i of suggestion[r]) setRole(i, r);
            NB.put(notes); renderTable(); return update();
          }));
      }
      display(); renderTable();
      const stepSelect = h("select", { "aria-label": "Reaction step", onchange: e => read(draft.text, draft.filename, Number(e.target.value), working).catch(NB.fail) },
        Array.from({ length: parsed.steps }, (_, i) => h("option", { value: i, selected: i === parsed.step }, "Step " + (i + 1))));
      NB.put(preview, parsed.steps > 1 ? stepSelect : null, notes, imageBox,
        parsed.errors.map(err => h("p", { class: "note caution" }, "Fragment " + err.position + " · " + err.reason)),
        speciesTable, differences, replacement, h("div", { class: "row" }, apply || null, transform || null,
          review && !working ? button("Discard drawing changes", removeDrawing) : null,
          species.length && !applyToDraft ? button("Save all to library", () => saveToLibrary(species.map(m => m.position))) : null));
      if (parsed.reaction && kinds.some(r => roles()[r].join(",") !== parsed.reaction.roles[r].join(","))) await update();
    }
    async function read(text, filename, step = 0, working = false) {
      if (session && !working) throw Error("Accept or discard the ChemDraw working copy first.");
      if (!working) { removeDrawing(); target = prior = null; }
      const gen = ++generation;
      const parsed = await post("parse", { text, step, identify: opts.apply || opts.drawApply ? "preview" : undefined });
      if (gen === generation) { previewDraft = { text, filename, step }; await show(parsed, previewDraft, working); }
    }
    const editing = () => NB.put(activity, "Editing in ChemDraw. Save there, then close it. ", button("Discard working copy", discard));
    async function poll() {
      if (!session || !box.isConnected || pending) return;
      pending = true;
      const active = session;
      try {
        const result = await post("poll", { session, digest });
        if (session === active && result.changed) {
          previous = result.previous;
          digest = result.digest;
          generation++;
          await show(result.preview, { text: result.text, step: 0 }, true);
        }
        if (session === active) editing();
      } catch (err) {
        if (session === active) {
          digest = null; NB.put(preview);
          if (err.message.includes("Unknown ChemDraw")) clearSession();
          NB.put(activity, err.message, session ? button("Discard working copy", discard) : null);
        }
      } finally {
        pending = false;
        if (session && box.isConnected) timer = setTimeout(poll, 1500);
      }
    }
    function removeDrawing() {
      generation++; lastDrawing = previewDraft = null; NB.put(preview); NB.put(picture);
      opts.remove?.();
    }
    function showPicture(result, context) {
      lastDrawing = { result, context };
      const edit = button("Edit", opener => draw(opener, { ...context, initial: result.ket }));
      const img = result.parsed.scheme ? h("img", { class: "molecule", alt: "Query reaction",
        src: "data:image/png;base64," + result.parsed.scheme.plain }) : smallImage(result.svg, "Drawn structure");
      NB.put(picture, img, edit, button("Remove", removeDrawing));
    }
    async function draw(opener, context = {}) {
      const route = NB.routeSeq;
      if (session) throw Error("Accept or discard the ChemDraw working copy first.");
      let initial = context.initial, note, before = context.prior;
      const row = context.row;
      if (context.review && initial == null) {
        const saved = await post("sketch-input", { id: opts.id || opts.from, material: row?.id });
        initial = saved.text;
        if (saved.fresh) note = "Draw has laid out the stored SMILES afresh. The original drawing stays on file.";
        if (row && row.smiles !== (opts.view?.record.materials || []).map(m => ({ ...m, smiles: m.smiles || opts.view.record.smiles?.[m.id] })).find(m => m.id === row.id)?.smiles && row.smiles) initial = row.smiles;
      }
      if (context.review && !before) {
        if (row) before = [{ ...row, role: "none" }];
        else {
          const smiles = schemeState().smiles;
          before = smiles ? (await post("parse", { text: smiles })).molecules : opts.rows?.().filter(m => m.smiles).map(m => ({ ...m, role: "none" }));
        }
      }
      if (route !== NB.routeSeq || opener?.isConnected === false) return;
      const storedSketch = schemeSourceIsSketch();
      NB.drawDialog({ opener, initial, note, search: opts.settings?.(), startNative: context.startNative,
        nativeSeed: !row && (schemeDraft() || storedSketch) ? async () =>
          (schemeDraft()?.target ? schemeState().smiles : schemeDraft()?.ket) || (await post("sketch-input", { id: opts.id || opts.from })).text : null,
        native: opts.apply ? source => open(source, { target: row, prior: before, scheme: context.review && !row }) : null,
        use: async (result, settings) => {
          generation++; target = row; prior = before;
          previewDraft = { text: result.text, ket: result.ket, step: 0, review: context.review,
            edited: !!context.review, replaces_reaction: !!context.review && !row && !!opts.view?.record.reaction };
          showPicture(result, { ...context, prior: before });
          if (opts.searchDrawing) opts.searchDrawing(result, settings);
          else await show(result.parsed, previewDraft, false);
        } });
    }
    const drawButton = h("button", { type: "button", class: "quiet", disabled: !!NB.drawReason(), title: NB.drawReason(),
      onclick: e => draw(e.currentTarget, lastDrawing ? { ...lastDrawing.context, initial: lastDrawing.result.ket } : {}).catch(NB.fail) }, "Draw");
    async function edit(row, method, opener) {
      const pendingDraft = row ? opts.drafts?.().slice().reverse().find(d => d.material_ids?.includes(row.id)) : schemeDraft();
      const sketch = row ? (pendingDraft ? !!pendingDraft.ket : NB.isSketch(opts.view?.record, row.drawing)) : schemeSourceIsSketch();
      if (method === "draw" || sketch) {
        if (NB.drawReason()) throw Error(NB.drawReason());
        let initial = pendingDraft?.ket || (pendingDraft && (row?.smiles || pendingDraft.text));
        if (!row && pendingDraft?.target) initial = pendingDraft.schemeState.smiles;
        if (initial && row && pendingDraft?.material_ids?.length > 1) initial = row.smiles;
        return draw(opener || drawButton, { row, review: true, initial, startNative: method === "native" });
      }
      return open(row ? (pendingDraft || !row.drawing ? { draft: row.smiles } : {}) : pendingDraft ? { draft: pendingDraft.text, roles: pendingDraft.roles, step: pendingDraft.step } : {}, { target: row, scheme: !row, prior: row && [{ ...row, role: "none" }] });
    }
    async function open(source = {}, context = {}) {
      if (reason) return NB.toast(reason, true);
      if (session) return;
      const draft = !source.draft && !context.target && !context.scheme ? (previewDraft || currentDraft()) : null;
      const result = await post("open", { id: opts.id || null, from: opts.from, draft: draft?.text || undefined,
        step: draft?.step, roles: draft?.roles, scheme: !!context.scheme, material: context.target?.id, ...source });
      nativeContext = context;
      sessionStorage.setItem(sessionKey + ":context", JSON.stringify(context));
      session = result.session;
      sessionStorage.setItem(sessionKey, session); editing(); timer = setTimeout(poll, 1000);
    }
    box.append(dropZone(read, reason));
    if (opts.apply || opts.drawApply) box.append(h("p", { class: "small" },
      NB.state.reference_lookup === "pubchem" ? "Look-up is on. Up to ten unknown species are checked per preview. " :
        "Look-up is off. Choose Look up in PubChem to check one species. ", NB.keyNotice));
    if (!opts.externalDraw) box.append(drawButton);
    if (NB.drawReason() && !reason && !opts.externalDraw) box.append(h("span", { class: "small" }, NB.drawReason()));
    const editButtons = h("span", { class: "row" });
    function refreshEditButtons() {
      if (!opts.apply || reason) return;
      const native = button("Edit in ChemDraw", opener => {
        if (!target && previewDraft && !opts.drafts?.().includes(previewDraft)) {
          if (previewDraft.ket) return draw(opener, { ...lastDrawing?.context, initial: previewDraft.ket, startNative: true });
          return open();
        }
        if (!opts.id && currentDraft()?.ket) return draw(opener, { initial: currentDraft().ket, startNative: true });
        return opts.id ? edit(null, "native", opener) : open();
      });
      if (schemeSourceIsSketch() && NB.drawReason()) { native.disabled = true; native.title = NB.drawReason(); }
      const drawScheme = opts.id && h("button", { class: "quiet", disabled: !!NB.drawReason(), title: NB.drawReason(),
        onclick: e => edit(null, "draw", e.currentTarget).catch(NB.fail) }, "Edit in Draw");
      NB.put(editButtons, ...NB.schemeEditButtons(schemeSourceIsSketch(), drawScheme || null, native));
    }
    if (opts.apply && !reason) {
      refreshEditButtons(); box.append(editButtons);
      session = sessionStorage.getItem(sessionKey);
      if (session) nativeContext = JSON.parse(sessionStorage.getItem(sessionKey + ":context") || "{}");
      if (session) { editing(); timer = setTimeout(poll, 500); }
    }
    const savedScheme = h("div", {});
    const editScheme = () => edit(null, null, drawButton).catch(NB.fail);
    const previewScheme = drawing => NB.recordScheme({ derived: { scheme_preview: drawing } }, editScheme);
    const restoredScheme = schemeDraft();
    if (restoredScheme?.target && restoredScheme.schemeState.smiles) {
      savedScheme.textContent = "Reading the edited scheme…";
      post("parse", { text: restoredScheme.schemeState.smiles }).then(result => {
        if (schemeDraft() === restoredScheme) NB.put(savedScheme, previewScheme(result.scheme));
      }).catch(err => { if (schemeDraft() === restoredScheme) savedScheme.textContent = err.message; });
    } else if (opts.view?.derived.scheme || opts.view?.derived.scheme_preview) savedScheme.append(NB.recordScheme(opts.view, editScheme));
    box.append(savedScheme);
    box.append(activity, nameActivity);
    naming = sessionStorage.getItem(namingKey);
    if (naming) NB.put(nameActivity, "A naming copy is still open. ", button("Discard naming copy", closeNameCopy));
    if (!opts.externalDraw) box.append(picture);
    box.append(preview);
    return { box, open, read, draw, edit, drawButton, picture, reset: removeDrawing, editing: () => !!session || !!naming };
  };

  NB.libraryPicker = function (host, pick) {
    const label = h("input", { type: "search", placeholder: "Filter by label", "aria-label": "Filter library by label" });
    const results = h("div", {}), fragment = h("input", { placeholder: "Substructure SMILES or SMARTS", "aria-label": "Library substructure" });
    let gen = 0;
    const find = async () => {
      const n = ++gen;
      try {
        const { rows } = await post("library-search", { q: label.value, fragment: fragment.value });
        if (n !== gen) return;
        NB.put(results, ...rows.map(row => h("div", { class: "row" }, button([smallImage(row.svg, row.name || row.formula), NB.formula(row.name || row.formula)], () => {
          const basis = row.name_basis;
          const generated = basis?.kind === "generated" ? basis : basis?.generated;
          pick({ ...material({ ...row, label: row.name }), ...(row.cas ? { cas: row.cas } : {}),
            name_basis: { kind: "notebook", source: "compound library " + row.id, ...(generated ? { generated } : {}) } }); NB.put(host);
        }), h("button", { class: "quiet", disabled: !!NB.drawReason(), title: NB.drawReason(), onclick: e =>
          paste.draw(e.currentTarget, { initial: row.sketch || row.smiles }).catch(NB.fail) }, "Edit in Draw"))), rows.length ? null : "No matching compounds.");
      } catch (err) { if (n === gen) NB.put(results, err.message); }
    };
    label.oninput = find;
    const paste = NB.structureBox({ externalDraw: true, query: smiles => { fragment.value = smiles; find(); },
      drawApply: (species, source) => {
        const choose = m => { pick(material(m), { ...source, position: m.position, materialOnly: true }); NB.put(host); };
        if (species.length === 1) choose(species[0]);
        else NB.put(results, "Choose a species for this material.", species.map(m => button([smallImage(m.svg, m.formula), NB.formula(m.formula)], () => choose(m))));
      } });
    NB.put(host, h("div", { class: "pop" }, h("h3", {}, "From library"), label, fragment, paste.drawButton, button("Filter", find), paste.picture, paste.box, results, button("Close", () => NB.put(host))));
    find(); label.focus();
  };

  NB.inventoryStructureSearch = function () {
    const title = h("legend", {}, "Search by structure");
    if (NB.state.structureReason) return h("fieldset", {}, title, h("p", {}, NB.state.structureReason));
    const query = h("input", { type: "text", "aria-label": "Inventory structure query", placeholder: "SMILES or SMARTS" });
    const mode = h("select", { "aria-label": "Bottle match mode" },
      ["exact", "substructure", "similarity"].map(v => h("option", { value: v }, v)));
    const threshold = h("input", { type: "number", min: 0, max: 1, step: 0.05, value: "0.7", "aria-label": "Tanimoto threshold" });
    const limit = h("label", { hidden: true }, "Tanimoto threshold ", threshold);
    const count = h("p", { class: "muted small", role: "status" });
    const reach = n => n + (n === 1 ? " bottle has" : " bottles have") + " a stored structure for substructure and similarity searches.";
    const output = h("div", { "aria-live": "polite" });
    let revision = 0, switches = [], sketch;
    const clear = () => { revision++; NB.put(output); };
    query.oninput = () => { sketch = null; switches = []; clear(); };
    mode.onchange = () => { limit.hidden = mode.value !== "similarity"; clear(); };
    threshold.oninput = clear;
    const search = async (lookup = false) => {
      const current = ++revision;
      NB.put(output, "Searching…");
      try {
        const r = await post("bottles", { query: query.value.trim(), mode: mode.value, threshold: Number(threshold.value), switches, lookup });
        if (current !== revision) return;
        count.textContent = reach(r.count);
        NB.put(output, h("p", {}, r.bottles.length + " matching " + (r.bottles.length === 1 ? "bottle" : "bottles")),
          r.bottles.length ? table(["Chemical", "CAS", "Group", "Location", "Left", "Match"], r.bottles.map(b =>
            [NB.formula(b.name), b.cas, b.group, b.location || b.path, [b.remaining, b.unit].filter(Boolean).join(" "),
              b.basis + (b.score == null ? "" : " · " + b.score.toFixed(3))])) : null,
          r.message && h("p", {}, r.message),
          r.offer_lookup && h("div", {}, h("p", { class: "muted small" }, NB.keyNotice), button("Look up in PubChem", () => search(true))));
      } catch (err) { if (current === revision) NB.put(output, err.message); }
    };
    query.onkeydown = e => { if (e.key === "Enter") search(); };
    const draw = h("button", { type: "button", class: "quiet", disabled: !!NB.drawReason(), title: NB.drawReason(),
      onclick: e => NB.drawDialog({ opener: e.currentTarget, initial: sketch || query.value,
        search: { bottlesOnly: true, scope: "inventory", mode: mode.value === "exact" ? "drawn" : mode.value,
          threshold: threshold.value, switches }, use: (result, settings) => {
          sketch = result.ket;
          query.value = result.pattern || result.parsed.molecules.map(m => m.smiles).join(".");
          mode.value = settings.mode === "drawn" ? "exact" : settings.mode;
          threshold.value = settings.threshold; switches = settings.switches; mode.onchange(); search();
        } }) }, "Draw");
    NB.capi("GET", "/structures/inventory").then(r => { count.textContent = reach(r.count); })
      .catch(err => { if (!(err instanceof NB.StaleRead)) count.textContent = err.message; });
    return h("fieldset", {}, title, h("div", { class: "draw-query" }, query, draw, button("Search", () => search())),
      h("div", { class: "row" }, mode, limit), NB.drawReason() && h("p", { class: "small" }, NB.drawReason()), count, output);
  };

  NB.routes.push([/^#\/structures(?:\/(draw))?$/, async function (autoDraw) {
    const query = h("input", { type: "text", "aria-label": "Structure query", placeholder: "SMILES, SMARTS, or A>>B" });
    const select = (label, values) => h("select", { "aria-label": label }, values.map(v => h("option", { value: v }, v)));
    const mode = select("Search mode", ["substructure", "exact", "drawn", "similarity", "transformation"]);
    const scope = select("Search in", NB.drawScopes);
    let switches = [], selectedDrawing = false, modeChosen = false, searchRequest = 0;
    const role = select("Material role", ["any", "reactant", "product"]);
    const threshold = h("input", { type: "number", min: 0, max: 1, step: 0.05, value: "0.7", "aria-label": "Tanimoto threshold" });
    const limit = h("label", {}, "Tanimoto threshold ", threshold);
    mode.onchange = e => { if (e) modeChosen = true; limit.hidden = mode.value !== "similarity"; role.disabled = mode.value === "transformation"; };
    mode.onchange();
    const count = h("p", { class: "muted" }), output = h("div", { "aria-live": "polite" });
    const search = async () => {
      const n = ++searchRequest;
      NB.put(output, "Searching…");
      try {
        const r = await post("search", { query: query.value.trim(), mode: mode.value, role: role.value, scope: scope.value, switches, threshold: Number(threshold.value) });
        if (n !== searchRequest) return;
        NB.put(output, h("h2", {}, r.hits.length + " experiment matches"), r.hits.length ? table(["Experiment", "Material", "Role", "Key result", "Similarity"],
          r.hits.map(hit => [h("a", { href: "#/exp/" + hit.id }, hit.id + " · ", NB.formula(hit.title)),
            [smallImage(hit.svg, hit.smiles), NB.formula(hit.name || hit.formula)], hit.role, hit.key_result, hit.score?.toFixed(3) || "—"])) : null,
          r.library?.length ? h("h2", {}, "Compound library") : null,
          (r.library || []).map(hit => h("p", {}, smallImage(hit.svg, hit.smiles), NB.formula(hit.name || hit.formula))),
          r.bottles.length ? h("h2", {}, "Matching bottles") : null, r.bottles.map(b => h("p", {}, smallImage(b.svg, b.smiles), NB.formula(b.name), " · " + b.cas + " · " + b.location)));
      } catch (err) { if (n === searchRequest) NB.put(output, err.message); }
    };
    const paste = NB.structureBox({ transform: true, externalDraw: true,
      settings: () => ({ mode: (selectedDrawing || modeChosen) && ["substructure", "similarity"].includes(mode.value) ? mode.value : "drawn", scope: scope.value,
        role: role.value, threshold: threshold.value, switches }),
      remove: () => { selectedDrawing = false; query.value = ""; switches = []; searchRequest++; NB.put(output); },
      searchDrawing: (result, settings) => {
        const mols = result.parsed.molecules;
        const side = role => mols.filter(m => m.role === role).map(m => m.smiles).join(".");
        query.value = result.pattern || (result.arrow ? ["reactant", "agent", "product"].map(side).join(">") : mols.map(m => m.smiles).join("."));
        selectedDrawing = true; scope.value = settings.scope; role.value = settings.role;
        mode.value = settings.mode; threshold.value = settings.threshold; switches = settings.switches; mode.onchange(); search();
      }, query: (s, reaction) => {
      query.value = s; if (reaction) mode.value = "transformation"; mode.onchange(); query.focus();
    } });
    const form = h("fieldset", { disabled: !!NB.state.structureReason }, h("legend", {}, "Search records"),
      h("div", { class: "draw-query" }, query, paste.drawButton, button("Search", search)), paste.picture,
      h("div", { class: "row" }, scope, mode, role, limit), NB.drawReason() ? h("p", { class: "small" }, NB.drawReason()) : null);
    query.oninput = () => { if (selectedDrawing) { const value = query.value; paste.reset(); query.value = value; } };
    query.onkeydown = e => { if (e.key === "Enter") search(); };
    NB.setView(NB.pageHead({ title: "Structures" }), form, count, paste.box, output);
    if (autoDraw && !NB.drawReason()) paste.draw(paste.drawButton).catch(NB.fail);
    if (!NB.state.structureReason) {
      const r = await NB.capi("GET", "/structures/inventory");
      count.textContent = r.count + " inventory bottles have a stored structure.";
    }
  }]);
})();
