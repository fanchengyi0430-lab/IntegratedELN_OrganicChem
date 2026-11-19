/* Render the app's bundled Markdown guides with text and DOM nodes. */
"use strict";

function helpInline(text) {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\((?:MANUAL|DEMO|README|SCHEMA|THIRD_PARTY_NOTICES)\.md\))/g).map(part => {
    if (part.startsWith("`") && part.endsWith("`")) return h("code", {}, part.slice(1, -1));
    if (part.startsWith("**") && part.endsWith("**")) return h("strong", {}, part.slice(2, -2));
    const link = part.match(/^\[([^\]]+)\]\(((?:MANUAL|DEMO|README|SCHEMA|THIRD_PARTY_NOTICES)\.md)\)$/);
    if (link) return h("a", { href: link[2] === "MANUAL.md" ? "#/help" : "#/help/" + link[2] }, link[1]);
    return part;
  });
}

function helpDocument(markdown) {
  const heading = /^(#{1,6})\s+(.+)$/;
  const bullet = /^[-*]\s+(.+)$/;
  const numbered = /^\d+\.\s+(.+)$/;
  const fence = /^```/;
  const tableRow = /^\|.*\|$/;
  const tableRule = /^\|(?:\s*:?-+:?\s*\|)+$/;
  const lines = markdown.split(/\r?\n/).map(line => line.trimEnd());
  const article = h("article", { class: "prose help" });
  const tableCells = (line, tag) => line.slice(1, -1).split("|").map(cell => h(tag, {}, helpInline(cell.trim())));
  const take = test => {
    const group = [];
    while (index < lines.length && test(lines[index])) group.push(lines[index++]);
    return group;
  };
  let index = 0;
  while (index < lines.length) {
    const line = lines[index++];
    if (!line.trim()) continue;
    const head = line.match(heading);
    if (head) {
      article.append(h("h" + head[1].length, {}, helpInline(head[2])));
    } else if (fence.test(line)) {
      const code = take(next => !fence.test(next));
      index++;
      article.append(h("pre", {}, h("code", {}, code.join("\n"))));
    } else if (bullet.test(line) || numbered.test(line)) {
      const pattern = numbered.test(line) ? numbered : bullet;
      const items = [line, ...take(next => pattern.test(next))];
      article.append(h(pattern === numbered ? "ol" : "ul", {}, items.map(item => h("li", {}, helpInline(item.match(pattern)[1])))));
    } else if (tableRow.test(line) && tableRule.test(lines[index] || "")) {
      index++;
      article.append(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, tableCells(line, "th"))),
        h("tbody", {}, take(next => tableRow.test(next)).map(row => h("tr", {}, tableCells(row, "td")))))));
    } else {
      const continuation = take(next => next.trim() && ![heading, bullet, numbered, fence, tableRow].some(pattern => pattern.test(next)));
      article.append(h("p", {}, helpInline([line, ...continuation].join(" "))));
    }
  }
  return article;
}

NB.routes.push([/^#\/help(?:\/(DEMO\.md|README\.md|SCHEMA\.md|THIRD_PARTY_NOTICES\.md))?$/, async function (name) {
  const markdown = await NB.api("GET", "/help/" + (name || "MANUAL.md"));
  const about = NB.state.about;
  const article = helpDocument(markdown);
  const title = article.querySelector("h1");
  if (title) {
    const next = title.nextElementSibling;
    article.prepend(NB.pageHead({ title, status: next && next.tagName === "P" ? next : null }));
  }
  NB.setView(article, h("p", { class: "muted small" },
    (about.packaged ? "Packaged runtime" : "System runtime") + " · Python " + about.python + " · numpy " + about.numpy + " · RDKit " + about.rdkit + " · Ketcher " + (NB.state.sketcher?.version || "not installed")));
}]);
