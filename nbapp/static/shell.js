/* Notebook navigation, full-screen menu and command search. */
"use strict";
(() => {
  const groups = [
    ["Bench", [["#/", "Today"], ["#/new", "Plan an experiment"], ["#/followups", "Schedule and supplies"]]],
    ["Records", [["#/experiments", "Experiments"], ["#/structures", "Structures"], ["#/flags", "Open flags"]]],
    ["Results", [["#/screening", "Screening results"], ["#/si", "SI drafts"]]],
    ["Reference", [["#/inventory", "Inventory"], ["#/changes", "Change log"], ["#/help", "Help"]]],
  ];
  const pages = groups.flatMap(([group, links]) => links.map(([href, label]) => ({ group, href, label })));
  const start = { group: "Tools", href: "#/start", label: "Start a notebook" };
  const destinations = [...pages, { href: "#/structures/draw", label: "Draw a structure", group: "Records" }, start];
  const recordHref = id => "#/exp/" + id;
  const rows = () => NB.state.index?.rows || [];
  const blockingCount = () => rows().reduce((n, row) => n + row.flags.blocking, 0);
  const caseTitle = () => NB.state.index?.title || NB.state.cases.find(c => c.name === NB.state.case)?.title || NB.state.case;
  const enabled = href => href !== "#/followups" || NB.state.schedule_and_supplies;
  NB.shellPage = function (hash = location.hash || "#/") {
    const [, section, id] = hash.split("?")[0].split("/");
    if (["exp", "nmr", "si", "spectrum"].includes(section) && /^EXP-\d+$/.test(id || "")) {
      return { href: "#/experiments", group: "Experiments", label: "Exp " + NB.expNo(id), id };
    }
    return destinations.find(p => p.href === "#/" + section) || { href: hash, group: "", label: "Page not found" };
  };

  // Native dialogs make the underlying notebook inert and return focus when dismissed.
  let dialog = null;
  function dismiss() {
    if (!dialog) return;
    const current = dialog;
    dialog = null;
    current.close();
    current.remove();
  }
  function showDialog(element, initial) {
    dismiss();
    dialog = element;
    element.addEventListener("cancel", e => { e.preventDefault(); dismiss(); });
    element.addEventListener("keydown", e => {
      if (e.key !== "Tab") return;
      const controls = element.querySelectorAll("a[href], button:enabled, select:enabled, input:enabled");
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    document.body.append(element);
    element.showModal();
    initial.focus();
  }
  window.addEventListener("hashchange", dismiss);
  NB.showDialog = showDialog;
  NB.closeDialog = dismiss;

  function switchNotebook(item) {
    dismiss();
    if (item.name === NB.state.case || !NB.confirmLeave()) return;
    NB.dirty = false;
    NB.openCase(item, NB.routeSeq);
  }

  function showNotebooks() {
    const close = h("button", { onclick: dismiss }, "Close");
    const notebooks = [...NB.state.cases].sort((a, b) => (a.title || a.name).localeCompare(b.title || b.name));
    const choices = notebooks.map(item => h("button", { "aria-current": item.name === NB.state.case ? "true" : null,
      onclick: () => switchNotebook(item) }, item.title || item.name));
    const list = h("dialog", { class: "command-dialog dark noprint", "aria-labelledby": "notebook-title" },
      h("header", { class: "menu-head" }, h("h2", { id: "notebook-title" }, "Switch notebook"), close),
      h("div", { class: "menu-tools" }, choices, h("a", { href: start.href, onclick: dismiss }, start.label),
        h("button", { onclick: e => { dismiss(); NB.openDemo(e); } }, "Open a demo notebook")));
    showDialog(list, choices.find(b => b.getAttribute("aria-current")) || close);
  }

  function stepLink(id, label, symbol) {
    return id ? h("a", { href: recordHref(id), class: "btn", title: label, "aria-label": label }, symbol)
      : h("button", { disabled: true, title: label, "aria-label": label }, symbol);
  }
  NB.drawBar = function () {
    const bar = document.getElementById("bar"), page = NB.shellPage();
    if (!NB.state.case) {
      NB.put(bar, h("strong", {}, "Integrated Notebook for Organic Chemistry"), h("a", { href: "#/help", "aria-current": page.href === "#/help" ? "page" : null }, "Help"));
      return;
    }
    const experiments = rows(), i = experiments.findIndex(r => r.id === page.id);
    const record = page.id && NB.recordShell?.id === page.id ? NB.recordShell : null;
    const prev = record ? record.prev : experiments[i - 1]?.id;
    const next = record ? record.next : i >= 0 ? experiments[i + 1]?.id : null;
    const drawer = record?.toggle && location.hash === recordHref(page.id);
    const count = blockingCount();
    const flagsText = [h("span", { class: "flags-label" }, "Flags "), h("b", {}, count)];
    const flagsAttrs = { class: "bar-flags", "aria-label": "Flags " + count };
    const flags = drawer
      ? h("button", { class: "bar-flags", "aria-controls": "record-drawer", "aria-expanded": String(record.open), onclick: record.toggle }, "Review")
      : h("a", { ...flagsAttrs, class: "btn bar-flags", href: "#/flags" }, flagsText);
    const refocusFlags = document.activeElement?.classList.contains("bar-flags");
    NB.put(bar,
      h("button", { class: "bar-menu", "aria-haspopup": "dialog", onclick: showMenu }, h("span", { "aria-hidden": "true" }, "☰ "), "Menu"),
      h("button", { class: "bar-notebook", "aria-label": "Switch notebook: " + caseTitle(), title: caseTitle(),
        "aria-haspopup": "dialog", onclick: showNotebooks }, caseTitle()),
      h("div", { class: "crumb" }, h("span", { class: "crumb-prefix" }, page.group ? page.group + " / " : ""), h("strong", {}, page.label)),
      page.id ? h("span", { class: "bar-steps" }, stepLink(prev, "Previous", "‹"), stepLink(next, "Next", "›")) : null,
      h("button", { class: "bar-command", "aria-label": "Search or jump to…", "aria-haspopup": "dialog", "aria-keyshortcuts": "Control+K", onclick: showCommands },
        h("span", { class: "command-long" }, "Search or jump to…"), h("span", { class: "command-short" }, "Search"), h("kbd", {}, "Ctrl K")),
      NB.state.index?.stale ? h("span", { class: "bar-build" },
        h("span", { class: "build-dot", "aria-hidden": "true" }), h("span", { class: "build-text" }, "Records changed since the last build"),
        h("button", { title: "Records changed since the last build", onclick: NB.rebuild }, "Rebuild")) : null,
      flags);
    if (refocusFlags) flags.focus({ preventScroll: true });
  };

  NB.setupDrawer = function (drawer, hasResponse) {
    const record = NB.recordShell;
    let open = hasResponse;
    try {
      const saved = localStorage.getItem("nb-drawer");
      if (!hasResponse) open = saved === "open";
    } catch (e) { /* use the record default if storage is unavailable */ }
    drawer.dataset.open = String(open);
    const close = drawer.querySelector(".drawer-heading button");
    function toggle() {
      if (NB.recordShell !== record) return;
      open = !open;
      try { localStorage.setItem("nb-drawer", open ? "open" : "closed"); } catch (e) { /* the toggle still works */ }
      drawer.dataset.open = String(open);
      record.open = open;
      NB.drawBar();
      const target = open ? close : document.querySelector('#bar [aria-controls="record-drawer"]');
      if (target) target.focus({ preventScroll: true });
    }
    close.addEventListener("click", toggle);
    Object.assign(record, { open, toggle });
  };

  function showMenu() {
    const page = NB.shellPage(), index = NB.state.index, experiments = rows(), n = blockingCount();
    const isPlanned = r => r.status === "planned";
    const started = r => Date.parse(String(r.started || "").replace(/\s*\(planned\)$/i, "")) || 0;
    const recent = [...experiments].sort((a, b) =>
      Number(isPlanned(b)) - Number(isPlanned(a)) || started(b) - started(a) || b.n - a.n).slice(0, 5);
    const attention = h("div", { "aria-live": "polite" }, n ? "Loading…" : "No blocking flags");
    const close = h("button", { onclick: dismiss }, "Close ", h("kbd", {}, "Esc"));
    const tool = (label, run, extra, disabled = false) => h("button", { disabled, onclick: e => { dismiss(); run(e); } }, label, extra);
    const menu = h("dialog", { class: "shell-menu dark noprint", "aria-labelledby": "menu-title" },
      h("header", { class: "menu-head" }, h("h2", { id: "menu-title" }, "Integrated Notebook for Organic Chemistry · " + caseTitle()), close),
      h("div", { class: "menu-columns" },
        h("nav", { class: "menu-navigation", "aria-labelledby": "menu-nav" },
          h("h2", { class: "menu-label", id: "menu-nav" }, "Navigation"),
          groups.map(([group, items]) => [h("h3", {}, group), items.filter(([href]) => enabled(href)).map(([href, label]) =>
            h("a", { href, class: "menu-link", "aria-current": page.href === href ? "page" : null },
              h("span", {}, label), href === "#/flags" && n ? h("small", {}, n + " blocking") : null))])),
        h("section", {}, h("h2", { class: "menu-label" }, "Experiments", h("a", { href: "#/experiments" }, "All " + experiments.length)),
          recent.map(r => h("a", { class: "menu-card", href: recordHref(r.id) }, NB.vial(r), h("strong", {}, NB.formula(r.title)),
            h("small", {}, isPlanned(r) && r.started ? "Planned for " + String(r.started).replace(/\s*\(planned\)$/i, "") : r.key_result))),
          h("h2", { class: "menu-label" }, "Needs attention"), attention),
        h("section", { class: "menu-tools" }, h("h2", { class: "menu-label" }, "Tools"),
          tool("Rebuild Word notebook", NB.rebuild, index?.stale ? h("small", {}, "records changed") : null),
          tool("Open the Word notebook", () => NB.openNative(index.notebook), null, !index?.notebook),
          tool("Open the notebook folder", () => NB.openNative(".")),
          h("a", { href: start.href, "aria-current": page.href === start.href ? "page" : null }, start.label),
          tool("Open a demo notebook", NB.openDemo),
          tool("Switch notebook", showNotebooks))),
      h("footer", { class: "menu-foot" }, "Records are the source of truth. Every save is logged."));
    menu.addEventListener("click", e => {
      const link = e.target.closest("a[href]");
      if (!link || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      dismiss();
      location.hash = link.hash;
    });
    showDialog(menu, close);
    if (n) NB.capi("GET", "/flags").then(res => {
      if (!menu.open) return;
      const flags = res.flags.filter(f => f.tier === "blocking").slice(0, 3);
      NB.put(attention, flags.length ? flags.map(f => h("div", { class: "menu-flag flag blocking" },
        h("a", { href: recordHref(f.exp) }, h("strong", { class: "chip blocking" }, "blocking " + f.id), " ", f.text))) : "No blocking flags");
    }).catch(e => { if (menu.open) attention.textContent = e.message; });
  }

  function commandMatches(text) {
    const query = text.trim().toLowerCase();
    const notebooks = NB.state.cases.filter(c => c.name !== NB.state.case)
      .map(c => ({ notebook: c, label: "Switch to " + (c.title || c.name) }));
    const matches = [...destinations.filter(p => enabled(p.href)), ...notebooks].filter(p => p.label.toLowerCase().includes(query));
    const exactNumber = /^\d+$/.test(query) ? Number(query) : null;
    for (const r of rows()) {
      const label = "Exp " + r.n + " · " + r.title;
      if (r.n !== exactNumber && ![label, r.id, r.legacy_id, r.key_result].some(value => String(value || "").toLowerCase().includes(query))) continue;
      const match = { href: recordHref(r.id), label };
      if (r.n === exactNumber) matches.unshift(match);
      else matches.push(match);
    }
    return [...matches.slice(0, 7), { label: 'Search all records for "' + text + '"', query: text }];
  }
  function showCommands() {
    if (dialog?.classList.contains("command-dialog")) return;
    let items, selected;
    const list = h("div", { class: "command-results", id: "command-results", role: "listbox", "aria-label": "Results" });
    const input = h("input", { type: "text", role: "combobox", autocomplete: "off", "aria-autocomplete": "list",
      "aria-expanded": "true", "aria-controls": list.id, "aria-labelledby": "command-title", placeholder: "Search or jump to…" });
    function select(i) {
      selected = i;
      Array.from(list.children).forEach((option, j) => option.setAttribute("aria-selected", String(j === selected)));
      input.setAttribute("aria-activedescendant", list.children[i].id);
      list.children[i].scrollIntoView({ block: "nearest" });
    }
    function choose(i) {
      const item = items[i];
      dismiss();
      if (item.notebook) switchNotebook(item.notebook);
      else if (item.href === "#/structures/draw" && location.hash === item.href) NB.route();
      else if (item.href) location.hash = item.href;
      else NB.searchAllRecords(item.query);
    }
    function update() {
      items = commandMatches(input.value);
      NB.put(list, items.map((item, i) => h("div", { role: "option", id: "command-option-" + i, onclick: () => choose(i) }, NB.formula(item.label))));
      select(0);
    }
    input.addEventListener("input", update);
    input.addEventListener("keydown", e => {
      if (e.isComposing || !["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "Enter") choose(selected);
      else select((selected + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length);
    });
    const command = h("dialog", { class: "command-dialog dark noprint", "aria-labelledby": "command-title" },
      h("header", { class: "menu-head" }, h("h2", { id: "command-title" }, "Search or jump to…"), h("button", { onclick: dismiss }, "Close ", h("kbd", {}, "Esc"))),
      input, list);
    showDialog(command, input);
    update();
  }
  document.addEventListener("keydown", e => {
    if (!NB.state.case || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== "k") return;
    if (document.querySelector("dialog[open]") && !dialog) return;
    e.preventDefault();
    showCommands();
  });
})();
