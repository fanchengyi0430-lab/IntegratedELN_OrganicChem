"use strict";
// Offsets refer to the original name so a search highlight can cross a subscript.
NB.chemicalRuns = function (text, rules) {
  const lexeme = new RegExp(rules.lexeme, "gy"), runs = [];
  for (const token of String(text ?? "").split(/([\s,;/]+)/)) {
    if (!token) continue;
    let body = token.replace(/[.:!?]+$/, "");
    const suffix = token.slice(body.length), charge = body.match(/(?:\^\d+)?[+−-]$/);
    if (charge) body = body.slice(0, charge.index);
    const parts = [], stack = [];
    let unit = false, end = 0;
    if (/[0-9+−-]/.test(token) && !rules.exceptions.includes(body) && !/^[RSP]\d+$/.test(body)) {
      lexeme.lastIndex = 0;
      while (end < body.length) {
        const m = lexeme.exec(body);
        if (!m) break;
        const part = m[0], first = part[0];
        if (".·".includes(first)) {
          if (!unit || stack.length) break;
          unit = false;
        } else if ("([".includes(first)) {
          if (part.length !== 1) break;
          stack.push(first); unit = false;
        } else {
          if (")]".includes(first) && (!unit || stack.pop() !== (first === ")" ? "(" : "["))) break;
          unit = true;
        }
        const digits = unit && part.match(/\d+$/);
        if (digits) parts.push(["", part.slice(0, digits.index)], ["sub", digits[0]]);
        else parts.push(["", part]);
        end = lexeme.lastIndex;
      }
    }
    if (end === body.length && unit && !stack.length) {
      if (charge) parts.push(["sup", charge[0].replace("^", "").replace("-", "−")]);
      if (suffix) parts.push(["", suffix]);
      runs.push(...parts);
    } else runs.push(["", token]);
  }
  return runs;
};
NB.chemicalPlain = function (text, rules = NB.state.formula_rules) {
  const superscript = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  return NB.chemicalRuns(text, rules).map(([kind, s]) => {
    if (kind === "sub") return s.replace(/\d/g, d => "₀₁₂₃₄₅₆₇₈₉"[Number(d)]);
    if (kind === "sup") return s.replace(/[\d+−]/g, d => d === "+" ? "⁺" : d === "−" ? "⁻" : superscript[Number(d)]);
    return s;
  }).join("");
};
NB.formula = function (text, highlights = []) {
  const frag = document.createDocumentFragment();
  let offset = 0;
  for (const [kind, value] of NB.chemicalRuns(text, NB.state.formula_rules)) {
    const end = offset + value.length;
    const cuts = [offset, ...highlights.flat().filter(n => n > offset && n < end), end];
    for (let i = 1; i < cuts.length; i++) {
      const s = value.slice(cuts[i-1] - offset, cuts[i] - offset);
      const node = kind ? h(kind, {}, s) : s;
      frag.append(highlights.some(([a,b]) => cuts[i-1] >= a && cuts[i] <= b) ? h("mark", {}, node) : node);
    }
    offset = end;
  }
  return frag;
};
