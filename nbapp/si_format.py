"""Reporting typography and SI paragraphs from recorded facts only."""
import re

from .formatting import chemical, markup, plain, SUP

SOLVENTS = {
    "chloroform-d": "CDCl3", "dmso-d6": "(CD3)2SO", "dimethyl sulfoxide-d6": "(CD3)2SO",
    "methanol-d4": "CD3OD", "benzene-d6": "C6D6", "acetone-d6": "(CD3)2CO",
    "acetonitrile-d3": "CD3CN", "dichloromethane-d2": "CD2Cl2", "water-d2": "D2O",
    "deuterium oxide": "D2O", "thf-d8": "C4D8O", "tetrahydrofuran-d8": "C4D8O",
    "toluene-d8": "C7D8", "pyridine-d5": "C5D5N",
}
_NUC = re.compile(r"^\s*\^?([0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s*([A-Z][a-z]?)\s*(?:[- ]?NMR\b\s*|(?=\(|δ|\d[\d.]*\s*MHz))", re.I)
_NUM = r"[−+-]?\d+(?:\.\d+)?"
_SIGNAL = re.compile(r"(?:^|[,;])\s*(" + _NUM + r")(?:\s*[–—]\s*(" + _NUM + r"))?\s*(?:\(([^()]*)\))?")
_UNSUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_J = re.compile(r"\bJ\s*(?:[=:]\s*|(?=\d))(" + _NUM + r"(?:\s*,\s*" + _NUM + r"(?!(?:[\d.]|\s*H\b)))*)\s*(Hz\b)?", re.I)


def characterization(line):
    """Return method order, display runs and review notes without altering recorded digits."""
    line = str(line).strip()
    m = _NUC.match(line)
    if not m:
        order = 0 if re.match(r"R[_ ]?f\b", line, re.I) else 5 if re.match(r"HRMS\b", line, re.I) else 6
        return order, chemical(line), []
    mass = m[1].translate(_UNSUP)
    element = m[2].capitalize()
    nucleus = mass + element
    order = {"1H": 1, "13C": 2, "19F": 3}.get(nucleus, 4)
    label = mass.translate(SUP) + element
    runs = [("sup", mass), ("", element + " NMR")]
    notes = []
    rest = line[m.end():].strip()
    # Extract a parenthesized header, including solvents containing parentheses.
    bare = re.match(r"^([\d.]+\s*MHz)\s*,\s*([^,δ]+?)\s*(?:,\s*|(?=δ))(?=[δ−+\d-])", rest, re.I)
    if bare:
        rest = "(" + bare[1] + ", " + bare[2] + ") " + rest[bare.end():]
    head = re.match(r"^\((.*?)\)\s*(?=δ|delta|[:;]|[+−\d-]|$)", rest, re.I)
    if head:
        fields = [s.strip() for s in head[1].split(",")]
        frequency = next((s for s in fields if re.fullmatch(r"[\d.]+\s*MHz", s, re.I)), None)
        solvent = next((s for s in fields if s != frequency), None)
        if frequency and solvent and len(fields) == 2:
            runs.append(("", " (" + re.sub(r"\s*MHz", " MHz", frequency, flags=re.I) + ", "))
            solvent = SOLVENTS.get(solvent.lower(), solvent).translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
            runs.extend(chemical(solvent))
            runs.append(("", ")"))
        else:
            runs.extend(chemical(" " + head[0].strip()))
            notes.append("check frequency and solvent")
        rest = rest[head.end():]
    else:
        notes.append("check frequency and solvent")
    body = re.sub(r"^\s*[:,;]?\s*(?:δ|delta)?\s*(?:\(\s*ppm\s*\)|ppm)?\s*[:=]?\s*", "", rest, flags=re.I)
    body = re.sub(r"(?<=\d)\s*[-–—−]\s*(?=[−+-]?\d)", "–", body)
    body = re.sub(r"(?<!\w)-(?=\d)", "−", body).rstrip(". ")
    if not body:
        return order, runs, [label + ": " + "; ".join(notes + ["missing shift list"]) + "."]
    # Only scan top-level shifts. Commas inside a multiplet belong to its annotation.
    signals = list(_SIGNAL.finditer(body))
    shifts, decimals, counts = [], {"1H": 2, "13C": 1}.get(nucleus), True
    for signal in signals:
        for val in signal.group(1, 2):
            if val is None:
                continue
            shifts.append(float(val.replace("−", "-")))
            if decimals and len(val.partition(".")[2]) != decimals:
                warning = "report shifts with %d decimal place%s" % (decimals, "s" if decimals > 1 else "")
                if warning not in notes:
                    notes.append(warning)
        counts &= bool(re.search(r"\b\d+(?:\.\d+)?\s*H\b", signal[3] or "", re.I))
    if not signals:
        notes.append("check the shift list")
    if any(b > a for a, b in zip(shifts, shifts[1:])):
        notes.append("shifts are not descending")
    if nucleus == "1H" and not counts:
        notes.append("missing proton count")
    runs.append(("", " δ "))
    if nucleus == "1H" and any(not re.match(r"(?:br\.?\s*)?(?:s|d|t|q|m|p|quint|sext|sept|hept|oct|[dtq]{2,4})\b", s[3] or "", re.I) for s in signals):
        notes.append("check the multiplicity")
    for signal in signals:
        detail = signal[3] or ""
        if re.match(r"(?:d|t|q|dd|dt|td|ddd)\b", detail, re.I) and not _J.search(detail):
            notes.append("missing coupling in Hz")
            break
    pos = 0
    for j in _J.finditer(body):
        runs.extend(chemical(body[pos:j.start()]))
        other_unit = re.match(r"(?:kHz|MHz|ppm)\b", body[j.end():], re.I)
        if other_unit:
            notes.append("check coupling units")
        runs.extend([("i", "J"), ("", " = " + j[1] + (" " if other_unit else " Hz"))])
        pos = j.end()
    runs.extend(chemical(body[pos:] + "."))
    return order, runs, [label + ": " + "; ".join(notes) + "."] if notes else []


def make_entry(rec, product, sources):
    missing = []
    name = product.get("name", "")
    cid = product.get("compound_id") or rec.get("compound_id")  # a row id such as P1 is not a compound number
    paragraphs = []
    if name:
        text = plain(chemical(name))
        html = "<strong>" + markup(chemical(name)) + "</strong>"
        if cid:
            tail = " (" + str(cid) + ")"
            text += tail
            html += markup([("", tail)])
        paragraphs.append((text, html))
    else:
        missing.append("compound name")

    def append(runs):
        paragraphs.append((plain(runs), markup(runs)))

    prep = " ".join(str(x) for x in rec.get("procedure") or [])
    if prep:
        append(chemical(prep))
    else:
        missing.append("preparation or general-procedure reference")
    planned = rec.get("status") == "planned" or str(rec.get("procedure_basis", "")).lower().startswith("planned")
    if planned or not re.search(r"\b[\d.]+\s*(?:mmol|mol|µmol|μmol|mg|g)\b", prep, re.I):
        missing.append("actual scale")
    if planned or not re.search(r"purifi|chromatograph|column|recrystalli|distill|triturat|precipitat", prep, re.I):
        missing.append("purification")

    result = rec.get("result") or {}
    observation = str(result.get("text") or "").strip().rstrip(".")
    external = re.match(r"(?:target|planned|literature|slides?)\b", str(result.get("basis") or "").strip(), re.I)
    measured = observation and not external and not re.fullmatch(r"not recorded|pending|unknown|n/?a", observation, re.I)
    if not measured or not re.search(r"\d\s*(?:[µμm]?g|kg)\b", observation):
        missing.append("isolated mass")
    if not measured or not re.search(r"\d\s*mmol\b", observation):
        missing.append("isolated mmol")
    if not measured or not re.search(r"\d\s*%", observation):
        missing.append("yield")
    appearance = r"\b(?:solid|oil|powder|crystals?|liquid|foam|wax)\b"
    if not ((measured and re.search(appearance, observation, re.I)) or (not planned and re.search(r"(?:obtained|afforded|isolated|yielded)[^.]*" + appearance, prep, re.I))):
        missing.append("appearance")
    if measured:
        # Preserve qualifiers and competing percentages in free-text results.
        quantity = r"[~<>≈≤≥]?\s*\d+(?:\.\d+)?\s*(?:[µμm]?g|mmol|%)"
        fields = [s.strip() for s in observation.strip("() ").replace(" (", ", ").rstrip(")").split(",")]
        quantities = [s for s in fields if re.fullmatch(quantity, s)]
        looks = [s for s in fields if re.fullmatch(r"(?:[a-z]+[ -])*" + appearance, s, re.I)]
        if name and len(quantities) + len(looks) == len(fields) and len(looks) <= 1:
            sentence = name + " was obtained"
            if looks:
                description = re.sub(r"^(?:as )?(?:an? )?", "", looks[0], flags=re.I)
                article = "" if description.lower().endswith("crystals") else "an " if description[0].lower() in "aeiou" else "a "
                sentence += " as " + article + description
            if quantities:
                sentence += " (" + ", ".join(quantities) + ")"
            sentence += "."
        elif name and re.match(r"^[~<>≈≤≥]?\d", observation):
            sentence = name + " was obtained (" + observation + ")."
        else:
            sentence = observation + "."
        append(chemical(sentence))

    reviewed = sorted((characterization(x) for x in rec.get("characterization") or [] if str(x).strip()), key=lambda x: x[0])
    if not reviewed:
        missing.append("measured characterization")
    notes = ["Result basis: " + str(result["basis"]) + ". Reported result: " + observation] if external else []
    for _, runs, warnings in reviewed:
        append(runs)
        for warning in warnings:
            notes.append(warning + " Line: " + plain(runs))
            for detail in ("missing shift list", "missing proton count", "missing coupling in Hz", "check frequency and solvent"):
                if detail in warning:
                    missing.append(warning.split(":")[0] + " " + {"missing shift list": "shift list",
                                   "missing proton count": "proton count", "missing coupling in Hz": "coupling in Hz",
                                   "check frequency and solvent": "frequency or solvent"}[detail])
    append([("", "Source notebook and sample IDs " + sources)])
    if missing or any(f.get("tier") == "blocking" for f in rec.get("flags") or []):
        paragraphs.insert(0, ("Draft, not reviewed", "Draft, not reviewed"))
    return {"plain": "\n".join(p for p, _ in paragraphs),
            "html": "".join("<p>" + h + "</p>" for _, h in paragraphs)}, missing, notes
