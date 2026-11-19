"""Display runs shared by SI, the clipboard and Word. Records keep their original text."""
import html
import json
import re
from pathlib import Path

RULES = json.loads((Path(__file__).parent / "data/formula.json").read_text(encoding="utf-8"))
_symbols = sorted(set(RULES["symbols"].split() + RULES["groups"]), key=lambda s: (-len(s), s))
# Share the lexical grammar with the browser. Counts are attached to a complete unit.
RULES["lexeme"] = "(?:" + "|".join(map(re.escape, _symbols)) + r"|[\[\]()])[\d]*|[·.]\d*"
LEXEME = re.compile(RULES["lexeme"], re.ASCII)
SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
SUP = str.maketrans("0123456789+-−", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻")


def token_runs(token):
    body = token.rstrip(".:!?")
    suffix = token[len(body):]
    charge = re.search(r"(?:\^\d+)?[+−-]$", body)
    if charge:
        body = body[:charge.start()]
    if body in RULES["exceptions"] or re.fullmatch(r"[RSP]\d+", body):
        return [("", token)]
    parts, stack, end, unit = [], [], 0, False
    for m in LEXEME.finditer(body):
        part = m.group()
        if m.start() != end:
            break
        end = m.end()
        first = part[0]
        if first in ".·":
            if not unit or stack:
                break
            unit = False
        elif first in "([":
            if len(part) != 1:
                break
            stack.append(first)
            unit = False
        else:
            if first in ")]" and (not unit or not stack or stack.pop() != {")": "(", "]": "["}[first]):
                break
            unit = True
        digits = re.search(r"\d+$", part) if unit else None
        if digits:
            parts.extend([("", part[:digits.start()]), ("sub", digits.group())])
        else:
            parts.append(("", part))
    else:
        if end == len(body) and unit and not stack:
            if charge:
                parts.append(("sup", charge.group().lstrip("^").replace("-", "−")))
            if suffix:
                parts.append(("", suffix))
            return parts
    return [("", token)]


def chemical(text):
    runs = []
    for token in re.split(r"([\s,;/]+)", str(text or "")):
        if token:
            parts = token_runs(token) if re.search(r"[0-9+−-]", token) else [("", token)]
            for kind, value in parts:
                if runs and not kind and not runs[-1][0]:
                    runs[-1] = ("", runs[-1][1] + value)
                else:
                    runs.append((kind, value))
    return runs


def plain(runs):
    return "".join(s.translate(SUB) if k == "sub" else s.translate(SUP) if k == "sup" else s for k, s in runs)


def markup(runs):
    return "".join("<%s>%s</%s>" % (k, html.escape(s), k) if k else html.escape(s) for k, s in runs)
