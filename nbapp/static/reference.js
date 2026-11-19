/* One explicit query, then separate choices for values to copy into a material draft. */
"use strict";

NB.referencePanel = function (onAccept) {
  const enabled = NB.state.reference_lookup === "pubchem";
  const panel = h("div", {});
  if (!enabled) NB.put(panel, h("p", { class: "muted small" }, "Reference look-up is off. See ",
    h("a", { href: "#/help" }, "Help"), " under PubChem look-up."));
  // The surrounding editors watch bubbling form events to save drafts. A reference search is independent.
  for (const event of ["click", "input", "change"]) panel.addEventListener(event, e => e.stopPropagation());
  const open = row => {
    const key = row.inchikey;
    const query = h("input", { type: "search", readonly: !!key, "aria-label": key ? "InChIKey" : "Compound name or CAS number",
      value: key || row.cas || (row.bottle || {}).cas || row.name || "" });
    const results = h("div", { "aria-live": "polite" });
    const status = h("p", { class: "muted small", role: "status" });
    let generation = 0;
    const use = (label, values) => h("button", { class: "quiet", onclick: () => {
      if (onAccept(row, values) === false) {
        NB.put(panel, h("p", { class: "muted small" }, "This material row has been removed."));
        return;
      }
      status.textContent = label.slice(4) + " added to the material draft.";
    } }, label);
    const search = async refresh => {
      const current = ++generation;
      const name = query.value.trim();
      if (!name) return NB.put(results, "Enter one compound name or CAS number.");
      NB.put(results, "Looking up " + name + "…");
      status.textContent = "";
      try {
        const r = await NB.api("POST", "/api/lookup", key ? { inchikey: key, refresh } : { query: name, refresh });
        if (generation !== current) return;
        const ident = r.identity, smiles = ident.SMILES || ident.IsomericSMILES || ident.ConnectivitySMILES;
        const formula = ident.MolecularFormula;
        if (key && row.formula && row.formula !== formula)
          return NB.put(results, "PubChem's formula differs from this material's formula.");
        NB.put(results, h("h3", {}, NB.formula(ident.IUPACName || name)),
          h("p", { class: "small" }, "PubChem CID " + r.cid + " · " + (r.cached ? "Cached, retrieved " : "Retrieved ") + r.retrieved),
          h("p", {}, formula ? NB.formula(formula) : null, formula ? " · " : "", [r.cas, smiles, ident.InChIKey].filter(Boolean).join(" · ")),
          h("p", {}, "Molecular weight (g/mol) · PubChem " + (ident.MolecularWeight ?? "unavailable") +
            " · notebook formula calculation " + (r.formula_mw === null ? "unavailable" : r.formula_mw.toFixed(3))),
          r.mw_warning ? h("p", { class: "note caution" }, "The molecular weights differ by more than 0.05 g/mol.") : null,
          h("div", { class: "row" },
            formula ? use("Use formula", { formula, mw: r.formula_mw }) : null,
            use("Use PubChem CID", { pubchem_cid: r.cid }), r.cas ? use("Use CAS", { cas: r.cas }) : null,
            smiles ? use("Use SMILES", { smiles }) : null),
          Object.entries(r.candidates).map(([heading, candidates]) => [
            h("h3", {}, heading),
            candidates.length ? h("ul", { class: "plain" }, candidates.map(c => h("li", {},
              c.text + " · " + c.source, c.value !== null ? " (" + c.value + " " + c.unit + ")" : "",
              heading === "Density" && c.unit === "g/mL" && c.value > 0
                ? use("Use density", { density: c.value, density_basis: "literature: " + c.source + " via PubChem CID " +
                    r.cid + ", retrieved " + r.retrieved + " (" + c.text + ")" }) : null)))
              : h("p", { class: "muted small" }, "No candidates listed.")]),
          h("button", { class: "quiet", onclick: () => search(true) }, "Refresh from PubChem"));
      } catch (err) {
        if (generation === current) NB.put(results, h("p", { class: "note caution" }, err.message));
      }
    };
    query.addEventListener("input", () => { generation++; NB.put(results); status.textContent = ""; });
    const close = () => { generation++; NB.put(panel); };
    NB.put(panel, h("div", { class: "pop" }, h("h3", {}, "Look up ", NB.formula(row.name || "material")),
      h("p", { class: "small" }, key ? NB.keyNotice : "Only the compound name or CAS number is sent to PubChem (U.S. National Institutes of Health). Leave unpublished compounds out of searches because PubChem has no entry for them."),
      h("div", { class: "row" }, query, h("button", { onclick: () => search(false) }, "Search PubChem"),
        h("button", { class: "quiet", onclick: close }, "Close")), results, status));
    query.focus();
  };
  return { panel, button: row => enabled ? h("button", { class: "quiet", onclick: e => {
    e.stopPropagation(); open(row);
  } }, "Look up") : null };
};

NB.applyReference = function (row, values) {
  if (values.smiles && values.smiles !== row.smiles) delete row.inchikey;
  for (const [key, value] of Object.entries(values)) {
    if (value === null) delete row[key];
    else row[key] = value;
  }
};
