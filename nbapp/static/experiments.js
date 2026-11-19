/* Experiment arrangements, selection and the reference in the record drawer. */
"use strict";
(() => {
  const h = NB.h;
  const exp = id => "Exp " + NB.expNo(id);
  const href = id => "#/exp/" + id;
  const button = (label, run, attrs = {}) => h("button", { type: "button", class: "quiet", onclick: run, ...attrs }, label);
  const clone = value => JSON.parse(JSON.stringify(value));
  const prefsKey = () => "nb-experiments:" + JSON.stringify([NB.state.root, NB.state.case]);
  function prefs() {
    try { return JSON.parse(localStorage.getItem(prefsKey())) || {}; } catch (_) { return {}; }
  }
  function remember(options) {
    try { localStorage.setItem(prefsKey(), JSON.stringify(options)); } catch (_) { /* still usable for this visit */ }
  }
  function dialog(title, content, initial) {
    const close = button("Cancel", NB.closeDialog);
    const box = h("dialog", { class: "command-dialog dark noprint", "aria-labelledby": "arrange-title" },
      h("header", { class: "menu-head" }, h("h2", { id: "arrange-title" }, title), close),
      h("div", { class: "arrange-dialog" }, content));
    NB.showDialog(box, initial || close);
  }
  function askTitle(label, initial, save) {
    const input = h("input", { required: true, value: initial, "aria-label": "Title" });
    dialog(label, h("form", { onsubmit: e => {
      e.preventDefault();
      if (!input.value.trim()) return input.focus();
      NB.closeDialog();
      return save(input.value.trim());
    } }, h("label", {}, "Title ", input), h("button", { type: "submit", class: "primary" }, "Save")), input);
  }

  async function persist(state, data, summary, notebook = NB.state.case) {
    const undo = data === null;
    const url = "/api/case/" + encodeURIComponent(notebook) + "/arrangement";
    const visible = () => NB.state.case === notebook && !NB.dirty &&
      /^#\/(?:experiments(?:\?.*)?|exp\/EXP-\d+)$/.test(location.hash);
    try {
      const result = await NB.api(undo ? "POST" : "PUT", url + (undo ? "/undo" : ""),
        { hash: state.hash, data, summary });
      if (NB.state.case !== notebook) return;
      if (visible()) await NB.route();
      NB.toast(result.message, false, result.undo ? { label: "Undo", run: () => persist(result, null, "", notebook) } : null);
    } catch (err) {
      if (err.status !== 409) return NB.fail(err);
      if (visible()) await NB.route();
      NB.toast(err.message, true);
    }
  }

  NB.sequenceLinks = function ({ record, derived }) {
    const parent = derived.parent;
    const lines = (derived.sequences || []).map(q => h("p", {}, h("strong", {}, q.title), " · ",
      q.stages.map((stage, i) => [i ? " → " : "", stage.map((id, j) => [j ? " / " : "",
        h("a", { href: href(id), "aria-current": id === record.id ? "step" : null }, exp(id))])])));
    if (parent) lines.push(h("p", {}, h("a", { href: "#/experiments?arrange=reaction" },
      parent.title, " · " + parent.members.length + (parent.members.length === 1 ? " sub-experiment" : " sub-experiments"))));
    return lines.length ? h("nav", { class: "sequence-links", "aria-label": "Related experiments" }, lines) : null;
  };

  NB.referenceCard = function ({ record, derived }) {
    const ref = derived.reference, best = ref?.best;
    async function choose(clear) {
      try {
        const idx = await NB.loadIndex();
        const state = idx.arrangement;
        const set = id => {
          const data = clone(state.data);
          if (id) data.references[record.id] = id;
          else delete data.references[record.id];
          return persist({ hash: derived.arrangement_hash }, data, id
            ? "chose " + exp(id) + " as reference for " + exp(record.id)
            : "restored automatic reference for " + exp(record.id));
        };
        if (clear) return set(null);
        const choices = h("div", { class: "menu-tools" });
        const input = h("input", { type: "search", "aria-label": "Filter experiments", placeholder: "Number or title", oninput: draw });
        function draw() {
          const query = input.value.trim().toLowerCase();
          const rows = idx.rows.filter(r => r.id !== record.id && [r.id, exp(r.id), r.title].join(" ").toLowerCase().includes(query));
          NB.put(choices, rows.map(r => button(exp(r.id) + " · " + r.title, () => { NB.closeDialog(); return set(r.id); })),
            rows.length ? null : h("p", {}, "No matching experiment."));
        }
        draw(); dialog("Choose an experiment", [input, choices], input);
      } catch (err) { NB.fail(err); }
    }
    return h("section", { class: "reference-card" }, h("h2", {}, "Reference experiment"),
      ref ? [h("p", {}, h("a", { href: href(ref.id) }, exp(ref.id) + " · ", NB.formula(ref.title)),
        " · " + (ref.chosen ? "chosen by you" : "automatic")),
        best ? [h("p", {}, [best.run && "Run " + best.run, best.conditions].filter(Boolean).join(" · ")),
          NB.yieldBar(best.result, best.basis, best), h("p", { class: "small" }, NB.formula(best.basis))]
          : h("p", {}, "No comparable result for this primary metric.")] : h("p", {}, "No earlier result for this reaction"),
      h("div", { class: "row noprint" }, button("Choose an experiment", () => choose(false)),
        ref?.chosen ? button("Use the automatic choice", () => choose(true)) : null));
  };

  NB.schemeUrl = (id, hash) => "/api/case/" + encodeURIComponent(NB.state.case) + "/record/" + id + "/scheme?v=" + hash;

  function thumbnail(row, enabled) {
    if (!enabled || !row?.scheme) return null;
    const link = h("a", { href: href(row.id) });
    link.append(h("img", { class: "scheme-thumb", loading: "lazy", decoding: "async",
      alt: row.scheme_alt || "Reaction scheme for " + exp(row.id),
      src: NB.schemeUrl(row.id, row.hash),
      onerror: () => link.remove() }));
    return link;
  }

  NB.routes.push([/^#\/experiments(?:\?(.*))?$/, async function (query) {
    const idx = await NB.loadIndex();
    NB.drawBar();
    const options = prefs(), params = new URLSearchParams(query || "");
    if (params.get("arrange") === "reaction") { options.mode = "reaction"; remember(options); }
    const modes = { number: "Number", reaction: "Reaction", sequence: "Sequence", created: "Created", modified: "Last modified" };
    let mode = Object.keys(modes).includes(options.mode) ? options.mode : "number";
    const f = NB.state.expFilter = NB.state.expFilter || { type: "all", planned: false, query: "", hits: null };
    const requested = NB.pendingSearch;
    NB.pendingSearch = null;
    if (requested != null) Object.assign(f, { type: "all", planned: false, query: requested, hits: null });
    const byId = Object.fromEntries(idx.rows.map(r => [r.id, r]));
    const state = idx.arrangement, parents = idx.parents || [], sequences = idx.sequences || [];
    const selected = new Set(), closed = new Set();
    let selecting = false;
    const toolbar = h("span", { class: "row" }), actions = h("div", { class: "toolbar", "aria-live": "polite" });
    const body = h("div", {}), info = h("p", { class: "muted small", "aria-live": "polite" });

    function change(summary, edit) {
      const data = clone(state.data);
      edit(data);
      return persist(state, data, summary);
    }
    function nextId(items, prefix) {
      return prefix + (1 + Math.max(0, ...items.map(g => Number(g.id.slice(1)))));
    }
    function assign(data, ids, target) {
      for (const group of data.groups) group.members = group.members.filter(id => !ids.includes(id));
      data.detached = data.detached.filter(id => !ids.includes(id));
      target.members.push(...ids);
    }
    function writableGroup(data, parent) {
      if (!parent.automatic) return data.groups.find(g => g.id === parent.id);
      const group = { id: nextId(data.groups, "G"), title: parent.title, members: [...parent.members] };
      data.groups.push(group);
      return group;
    }
    function moveTo(ids, current) {
      const choices = parents.filter(g => g.id !== current?.id).map(g => button(g.title, () => {
        NB.closeDialog();
        return change("moved " + ids.map(exp).join(", ") + ' to parent "' + g.title + '"', data =>
          assign(data, ids, writableGroup(data, g)));
      }));
      dialog("Add to parent", choices);
    }
    function createGroup(sequence) {
      const ids = [...selected];
      askTitle(sequence ? "New sequence" : "New parent experiment", "", title => change(
        "made " + (sequence ? "sequence" : "parent") + ' "' + title + '" from ' + ids.map(exp).join(", "), data => {
          if (sequence) data.sequences.push({ id: nextId(data.sequences, "Q"), title, steps: ids });
          else {
            const group = { id: nextId(data.groups, "G"), title, members: [] };
            data.groups.push(group);
            assign(data, ids, group);
          }
        }));
    }
    function memberControls(parent, id) {
      return h("div", { class: "row" }, button("Move out of parent", () => change("moved " + exp(id) + " out of its parent", data => {
        if (parent.automatic) data.detached.push(id);
        else {
          const g = writableGroup(data, parent);
          g.members = g.members.filter(m => m !== id);
        }
      }), { "aria-label": "Move out of parent: " + exp(id) }),
      button("Move to…", () => moveTo([id], parent), { disabled: !parents.some(g => g.id !== parent.id), "aria-label": "Move " + exp(id) + " to another parent" }));
    }
    function seqEdit(q, message, update) {
      return change(message, data => {
        const seq = data.sequences.find(s => s.id === q.id);
        update(seq);
        if (seq.steps.length < 2) data.sequences = data.sequences.filter(s => s !== seq);
      });
    }
    function stepControls(q, i, id) {
      const move = (delta, word) => button(delta < 0 ? "↑" : "↓", () => seqEdit(q, "moved " + exp(id) + " " + word + ' in "' + q.title + '"', s => {
        [s.steps[i], s.steps[i + delta]] = [s.steps[i + delta], s.steps[i]];
      }), { disabled: !q.stages[i + delta], "aria-label": "Move " + exp(id) + " " + word });
      return h("div", { class: "row" }, move(-1, "up"), move(1, "down"), button("Remove step", () =>
        seqEdit(q, q.stages.length === 2 ? 'removed two-step sequence "' + q.title + '"' :
          'removed ' + exp(id) + ' from "' + q.title + '"', s => s.steps.splice(i, 1)),
        { "aria-label": "Remove step " + exp(id) }));
    }
    function pick(id) {
      if (!selecting) return null;
      return h("label", { class: "row" }, h("input", { type: "checkbox", checked: selected.has(id), "aria-label": "Select " + exp(id),
        onchange: e => { if (e.target.checked) selected.add(id); else selected.delete(id); draw(); } }),
        selected.has(id) ? String([...selected].indexOf(id) + 1) : "");
    }
    function timeMode() { return mode === "created" || mode === "modified"; }
    function table(rows, parent) {
      const schemes = !parent && options.schemes !== false;
      const th = text => h("th", { scope: "col" }, text);
      return h("div", { class: "tablewrap" + (parent ? " sub-experiments" : "") }, h("table", {},
        h("thead", {}, h("tr", {}, selecting ? th("Select") : null, th("Experiment"), th(timeMode() ? modes[mode] : "Started"),
          th("Subject"), schemes ? th("Scheme") : null, th("Key result (basis)"), th("NMR"), th("Open flags"), parent ? th("Parent") : null)),
        h("tbody", {}, rows.map(r => h("tr", { class: "link", onclick: e => {
          if (!e.target.closest("a, button, input, label")) location.hash = href(r.id);
        } }, selecting ? h("td", {}, pick(r.id)) : null, h("td", {}, NB.vial(r, href(r.id))),
        h("td", {}, timeMode() ? NB.fmtTime(r[mode]) : r.started.replace(" (planned)", " (plan)") || "–"),
        h("td", {}, NB.formula(r.title), r.error ? h("div", { class: "chip blocking" }, "record unreadable") : null),
        schemes ? h("td", {}, thumbnail(r, true)) : null, h("td", {}, NB.formula(r.key_result)),
        h("td", { class: "num", title: "NMR samples / spectra" }, r.spectra ? r.samples + " / " + r.spectra : "–"),
        h("td", {}, NB.flagChips(r.flags)), parent ? h("td", {}, memberControls(parent, r.id)) : null)))));
    }
    function groupView(g, visible) {
      const all = g.members.map(id => byId[id]).sort((a, b) => a.n - b.n);
      const rows = all.filter(r => visible.has(r.id));
      if (!rows.length) return null;
      const dates = all.map(r => r.started?.slice(0, 10) || r.created?.slice(0, 10)).filter(Boolean).sort();
      const dateRange = [...new Set([dates[0], dates.at(-1)])].filter(Boolean).join(" – ");
      const best = Object.entries(g.best || {}).map(([kind, id]) => {
        const entry = byId[id].best;
        return h("div", {}, h("a", { href: href(id) }, [kind, exp(id), entry.run && "Run " + entry.run].filter(Boolean).join(" · ")),
          NB.yieldBar(entry.result, entry.basis, entry), h("span", { class: "muted small" }, NB.formula(entry.basis)));
      });
      return h("section", {}, h("div", { class: "toolbar parent-heading" },
        h("h2", {}, button((closed.has(g.id) ? "▸ " : "▾ ") + g.title, () => { if (closed.has(g.id)) closed.delete(g.id); else closed.add(g.id); draw(); },
          { "aria-expanded": String(!closed.has(g.id)), "aria-label": g.title })),
        h("span", {}, all.length + (all.length === 1 ? " sub-experiment" : " sub-experiments")), h("span", {}, dateRange), best,
        thumbnail(all.find(r => r.scheme), options.schemes !== false),
        button("Rename", () => askTitle("Rename parent", g.title, title => change('renamed parent "' + g.title + '" to "' + title + '"',
          data => { writableGroup(data, g).title = title; }))),
        !g.automatic ? button("Remove parent", () => change('removed parent "' + g.title + '"',
          data => { data.groups = data.groups.filter(p => p.id !== g.id); })) : null),
        closed.has(g.id) ? null : table(rows, g));
    }
    function sequenceView(q, visible) {
      if (!q.stages.some(stage => stage.some(id => visible.has(id)))) return null;
      const prior = new Set();
      const stages = q.stages.map((stage, i) => {
        const rows = stage.filter(id => visible.has(id)).map(id => byId[id]);
        const names = [...new Set(rows.flatMap(r => r.previous.filter(link => prior.has(link.id)).map(link => link.name)))];
        stage.forEach(id => prior.add(id));
        return rows.length ? h("div", { class: "sequence-stage" },
          h("p", { class: "muted small" }, "Step " + (i + 1), names.length ? " · " + names.join(", ") : ""),
          h("div", { class: "row" }, rows.map(r => h("div", { class: "sequence-experiment" },
            pick(r.id), NB.vial(r, href(r.id)), h("a", { href: href(r.id) }, NB.formula(r.title)),
            thumbnail(r, options.schemes !== false), q.automatic ? null : stepControls(q, i, r.id))))) : null;
      });
      return h("section", {}, h("div", { class: "row" }, h("h2", {}, q.title), q.automatic ? null : [
        button("Rename", () => askTitle("Rename sequence", q.title, title =>
          seqEdit(q, 'renamed sequence "' + q.title + '" to "' + title + '"', s => { s.title = title; }))),
        button("Remove sequence", () => change('removed sequence "' + q.title + '"',
          data => { data.sequences = data.sequences.filter(s => s.id !== q.id); }))]), stages);
    }
    function draw() {
      const previousFocus = document.activeElement;
      const focus = previousFocus?.getAttribute("aria-label");
      const q = f.query.trim().toLowerCase();
      const rows = idx.rows.filter(r => (!f.planned || r.status === "planned") && (f.type === "all" || NB.typeClass(r.type) === "t-" + f.type) &&
        (f.hits ? f.hits.includes(r.id) : [r.id, exp(r.id), r.legacy_id, r.title, r.key_result, r.status, r.type].join(" ").toLowerCase().includes(q)));
      const visible = new Set(rows.map(r => r.id));
      const toggle = (label, enabled, run) => button(label, run, { class: enabled ? "on quiet" : "quiet", "aria-label": label, "aria-pressed": String(enabled) });
      NB.put(toolbar, toggle("Planned", f.planned, () => { f.planned = !f.planned; draw(); }),
        toggle("Schemes", options.schemes !== false, () => { options.schemes = options.schemes === false; remember(options); draw(); }),
        toggle("Select", selecting, () => { selecting = !selecting; selected.clear(); draw(); }),
        timeMode() ? button(options.oldest ? "Oldest first" : "Newest first", () => { options.oldest = !options.oldest; remember(options); draw(); }) : null,
        button(state?.undo ? "Undo: " + state.undo : "Undo", () => persist(state, null, ""), { disabled: !state?.undo }));
      NB.put(actions, selected.size ? [h("span", {}, [...selected].map((id, i) => (i + 1) + ". " + exp(id)).join(" · ")),
        button("New parent experiment", () => createGroup(false)), button("Add to parent…", () => moveTo([...selected]), { disabled: !parents.length }),
        selected.size >= 2 ? button("New sequence", () => createGroup(true)) : null] : null);
      actions.hidden = !selected.size;
      if (!rows.length) NB.put(body, h("p", { class: "empty" }, "No experiment matches these filters."));
      else if (mode === "reaction" || mode === "sequence") {
        const reaction = mode === "reaction";
        const used = new Set(reaction ? parents.flatMap(g => g.members) : sequences.flatMap(s => s.stages.flat()));
        const left = rows.filter(r => !used.has(r.id));
        NB.put(body, reaction ? parents.map(g => groupView(g, visible)) : sequences.map(s => sequenceView(s, visible)),
          left.length ? [h("h2", {}, reaction ? "Not grouped" : "Not in a sequence"), table(left)] : null);
      } else {
        if (timeMode()) rows.sort((a, b) => (Date.parse(b[mode]) - Date.parse(a[mode]) || b.n - a.n) * (options.oldest ? -1 : 1));
        NB.put(body, table(rows));
      }
      info.textContent = rows.length === idx.rows.length ? "" : rows.length + " of " + idx.rows.length + " shown" +
        (f.hits ? " (full text of the records contains “" + f.query + "”)" : "");
      if (focus && !previousFocus.isConnected) [...toolbar.querySelectorAll("[aria-label]"), ...body.querySelectorAll("[aria-label]")]
        .find(el => el.getAttribute("aria-label") === focus)?.focus();
    }
    async function fullText() {
      const text = f.query;
      if (!text.trim()) return;
      try {
        const result = await NB.capi("GET", "/search?q=" + encodeURIComponent(text));
        if (text === f.query) { f.hits = result.hits.map(x => x.id); draw(); }
      } catch (err) { NB.fail(err); }
    }
    const search = h("input", { type: "search", placeholder: "Number, ID, title or result", "aria-label": "Find experiments", value: f.query,
      oninput: e => { f.query = e.target.value; f.hits = null; draw(); }, onkeydown: e => { if (e.key === "Enter") fullText(); } });
    draw();
    NB.setView(NB.pageHead({ title: "Experiments", actions: h("a", { class: "btn primary", href: "#/new" }, "Plan an experiment"), status: info }),
      h("div", { class: "toolbar" }, search, button("Search full text", fullText),
        h("select", { "aria-label": "Type", onchange: e => { f.type = e.target.value; draw(); } },
          ["all", "synthesis", "screening", "computational", "other"].map(v => h("option", { value: v, selected: f.type === v },
            v === "all" ? "All types" : v[0].toUpperCase() + v.slice(1)))),
        h("label", {}, "Arrange by ", h("select", { "aria-label": "Arrange by", onchange: e => {
          options.mode = mode = e.target.value; remember(options);
          if (params.has("arrange")) location.hash = "#/experiments"; else draw();
        } }, Object.entries(modes).map(([value, name]) => h("option", { value, selected: value === mode }, name)))), toolbar),
      actions, (state?.warnings || []).map(w => h("p", { class: "note caution" }, w)), body);
    if (requested != null) await fullText();
  }]);
})();
