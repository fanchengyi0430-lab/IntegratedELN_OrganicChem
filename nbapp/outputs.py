"""Derived outputs: the cross-experiment screening table and draft SI text.

Nothing here writes to records. SI drafts are assembled only from what the record and the
processed spectra contain; anything not recorded is listed as missing instead of filled in.
"""
import csv
import io
import re

from . import chem, nmr, si_format
from .store import METRIC_KINDS, expno, is_screening, measured_processing, run_result

# 1H positions of common contaminants in CDCl3 (ppm), used only to set peaks aside for review.
CDCL3_IMPURITIES = [(1.56, "water"), (0.07, "silicone grease"), (0.86, "grease or hexanes"), (0.88, "grease or hexanes"),
                    (1.26, "grease, hexanes or EtOAc"), (2.05, "EtOAc"), (2.17, "acetone"), (4.12, "EtOAc"),
                    (5.30, "dichloromethane"), (0.00, "TMS")]


_PERCENT = re.compile(r"([<>~≈≤≥]?)\s*(\d+(?:\.\d+)?)\s*%")
_PERCENT_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*(?:[-−–—]|\bto\b)\s*(\d+(?:\.\d+)?)\s*%", re.I)
_ISOLATED_PERCENT = re.compile(r"(?<![\w.])(?<!\d,)" + _PERCENT.pattern)
_RANGE_END = re.compile(r"(?:\s*[-−–—]\s*|\s+to\s+)\d+(?:\.\d+)?\s*%", re.I)


_CONVERSION = re.compile(r"([<>~≈≤≥]?)\s*(\d+(?:\.\d+)?)(?:\s*%?\s*(?:[-−–—]|\bto\b)\s*(\d+(?:\.\d+)?))?\s*%\s*conv", re.I)
_ISOLATED_RESULT = re.compile(_PERCENT_RANGE.pattern + "|" + _ISOLATED_PERCENT.pattern, re.I)


def parse_result(text, isolated=False, metric_kind=None):
    """Yield and conversion (percent) from a run's result text, where it states them."""
    t = str(text or "").strip()
    low = t.lower()
    out = {"yield": None, "conv": None, "kind": "text", "qualifier": ""}
    if not t:
        out["kind"] = "none"
    elif low.startswith("nr"):
        out["kind"] = "nr"
    elif low.startswith("nd") or low.startswith("no product") or low.startswith("not detected"):
        out["kind"] = "nd"  # not detected is not a measured zero
    else:
        if isolated:
            match = _ISOLATED_RESULT.search(t)
            if match:
                t = t[match.start():]
        interval = _PERCENT_RANGE.match(t)
        if interval:
            out.update({"yield": min(map(float, interval.groups())), "kind": "yield"})
        elif (m := _PERCENT.match(t)):
            out.update({"yield": float(m.group(2)), "kind": "yield", "qualifier": m.group(1)})
    c = _CONVERSION.search(low)
    if c:
        out["conv"] = min(float(c[2]), float(c[3] or c[2]))
        if metric_kind == "conversion":
            out["qualifier"] = c[1]
    elif "full conv" in low:
        out["conv"] = 100.0
        if metric_kind == "conversion":
            out["qualifier"] = ""
    elif metric_kind == "conversion":
        out["conv"] = out["yield"]
    return out


def high_yield_warning(text, where, isolated=False):
    """Flag a stated yield over 100%, preserving the number as recorded."""
    text = str(text or "").strip()
    match = _ISOLATED_PERCENT.search(text) if isolated else _PERCENT.match(text)
    if match is None or _RANGE_END.match(text, match.end()):
        return None
    if isolated:
        before = text[:match.start()].rstrip()
        if before.endswith(("+", "-", "−")) or re.search(r"\d(?:\s*[–—]|\s+to)$", before, re.I):
            return None  # a signed value or the end of a range
    parsed = parse_result(match.group() if isolated else text)
    if parsed["yield"] is not None and parsed["yield"] > 100 and parsed["qualifier"] in ("", "~", "≈"):
        return ("%s: yield %s%% is above 100%%. Check for residual solvent or water in the weighed product, "
                "the limiting reagent, and the purity of the standard.") % (where, match.group(2))
    return None


def basis_kind(basis):
    b = str(basis or "").strip().lower()
    if b.startswith("measured"):
        return "measured"
    if "slide" in b:
        return "slides"
    for kind in ("target", "literature"):
        if b.startswith(kind):
            return kind
    return "other" if b else "none"


_RATIO = re.compile(r"^(?:(?:dr|er|regioselectivity)\s*[:=]?\s*)?([<>~≈≤≥]?)\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\b", re.I)


def _entries(rec):
    if rec.get("runs"):
        for run in rec["runs"]:
            if isinstance(run, dict):
                yield (str(run.get("run", "")), run.get("variable") or rec.get("conditions", ""),
                       run_result(rec, run), run.get("basis") or rec.get("results_basis", ""))
    elif isinstance(rec.get("result"), dict):
        result = rec["result"]
        yield "", rec.get("conditions", ""), result.get("text", ""), result.get("basis", "")


def best_entry(rec):
    kind = rec.get("metric_kind") or "yield"
    if kind not in METRIC_KINDS or kind == "other":
        return None
    best = None
    for label, conditions, text, basis in _entries(rec):
        basis_type = basis_kind(basis)
        if str(basis).strip().lower().startswith(("target", "literature")):
            continue
        text = str(text)
        parsed = parse_result(text, isolated=not rec.get("runs"), metric_kind=kind)
        if parsed["kind"] in ("nd", "nr"):
            continue
        qualifier = parsed["qualifier"]
        value = parsed["conv" if kind == "conversion" else "yield"]
        perfect = False
        if kind in ("dr", "er", "regioselectivity"):
            ratio = _RATIO.match(text.strip())
            if not ratio:
                continue
            qualifier = ratio[1]
            a, b = float(ratio[2]), float(ratio[3])
            if not a + b:
                continue
            perfect = b == 0
            value = a / b if b else 0
            width = 100 * a / (a + b)
        else:
            # More than 100% is a result to question (wet solid, wrong basis), not one to hold up as the best.
            if value is None or value > 100:
                continue
            width = value
        rank = [qualifier not in ("<", "≤"), perfect, value]
        if best is None or rank > best["rank"]:
            best = dict(run=str(label), conditions=conditions, result=text, basis=basis, basis_kind=basis_type,
                        metric_kind=kind, rank=rank, width=width, qualifier=qualifier)
    return best


def screening_rows(case):
    rows = []
    for rec in case.all():
        runs = rec.get("runs") or ([{}] if is_screening(rec) else [])
        metric_kind = rec.get("metric_kind") or ""
        for run in runs:
            if not isinstance(run, dict):
                continue
            result = run_result(rec, run)
            parsed = parse_result(result, metric_kind=metric_kind)
            if parsed["kind"] == "yield" and metric_kind in METRIC_KINDS and metric_kind != "yield":
                parsed.update({"yield": None, "kind": "text"})
            sample = case.run_sample(rec, run.get("run")) if "run" in run else None
            rows.append({
                "exp": rec["id"], "n": expno(rec["id"]), "legacy_id": rec.get("legacy_id", ""), "title": rec.get("title", ""),
                "run": str(run.get("run", "")), "variable": run.get("variable", ""), "result": result,
                "yield": parsed["yield"], "conv": parsed["conv"], "kind": parsed["kind"], "qualifier": parsed["qualifier"],
                "basis": run.get("basis", ""), "basis_kind": basis_kind(run.get("basis")),
                "nmr_source": measured_processing(run.get("measured")).get("source", ""),
                "has_spectrum": bool(sample and sample["spectra"] and sample["exists"]),
                "metric_kind": metric_kind, "metric": rec.get("metric") or "",
            })
    return rows


def screening_csv(case):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["experiment", "legacy_id", "run", "conditions", "result", "qualifier", "yield_percent", "detection",
                "conversion_percent", "basis", "metric_kind", "metric", "nmr_source", "basis_kind"])
    for r in screening_rows(case):
        w.writerow([r["exp"], r["legacy_id"], r["run"], r["variable"], r["result"], r["qualifier"],
                    "" if r["yield"] is None else "%g" % r["yield"], r["kind"] if r["kind"] in ("nd", "nr") else "",
                    "" if r["conv"] is None else "%g" % r["conv"], r["basis"], r["metric_kind"], r["metric"], r["nmr_source"], r["basis_kind"]])
    return buf.getvalue()


# ---------------------------------------------------------------- SI drafts
def _cluster(peaks, gap):
    """Group picked lines closer than `gap` ppm: [(centre, lo, hi, tallest)]."""
    out = []
    for ppm, h in sorted(peaks, reverse=True):
        if out and out[-1][1] - ppm <= gap:
            c = out[-1]
            out[-1] = [c[0], ppm, c[2], max(c[3], h), c[4] + [ppm]]
        else:
            out.append([ppm, ppm, ppm, h, [ppm]])
    return [((c[1] + c[2]) / 2.0, c[1], c[2], c[3]) for c in out]


def _spectrum_line(acq_dir):
    """One draft characterization line from a processed spectrum, plus review notes."""
    spec = nmr.Spectrum(acq_dir)
    nuc = spec.nucleus
    label = {"1H": "¹H", "13C": "¹³C", "19F": "¹⁹F"}.get(nuc, nuc)
    notes = []
    picked = nmr.peaklist(acq_dir)
    source = "TopSpin peak list"
    if not picked:
        picked = spec.pick(spec.lo, spec.offset, 0.02)
        source = "peaks picked from the processed spectrum"
    ref = spec.solvent_shift()
    corr = ref["correction"] if ref else 0.0
    if ref and abs(corr) >= 0.005:
        notes.append("%s: re-referenced by %+.2f ppm so that %s is at %.2f (found at %.2f)." % (label, corr, ref["solvent"], ref["target"], ref["found"]))
    elif not ref and nuc in ("1H", "13C"):
        notes.append("%s: no clear solvent peak found; shifts are as processed and not re-referenced." % label)
    peaks = [(p + corr, h) for p, h in picked]
    solvent_at = ref["target"] if ref else None
    half = {"1H": 0.03, "13C": 0.45}.get(nuc, 0)
    is_solvent = lambda p: solvent_at is not None and abs(p - solvent_at) <= half
    body = [(p, h) for p, h in peaks if not is_solvent(p)]
    aside = []
    if nuc == "1H" and "CDCl3" in spec.solvent:
        keep = []
        for p, h in body:
            tag = next((name for pos, name in CDCL3_IMPURITIES if abs(p - pos) <= 0.03), None)
            (aside if tag else keep).append((p, h, tag) if tag else (p, h))
        body = keep
    if not body:
        return {"nucleus": nuc, "line": "", "notes": notes + ["%s: no peaks above the picking threshold." % nuc]}
    top = max(h for _, h in body)
    floor = {"1H": 0.03, "13C": 0.05}.get(nuc, 0.03) * top
    body = [(p, h) for p, h in body if h >= floor]
    mhz = int(round(spec.sfo1))
    head = "%s NMR (%d MHz, %s) δ " % (label, mhz, spec.solvent)
    if nuc == "1H":
        groups = _cluster(body, 0.035)
        areas = [max(spec.integrate(lo - corr - 0.03, hi - corr + 0.03), 0.0) for _, lo, hi, _ in groups]
        unit = min([a for a in areas if a > 0] or [1.0])
        parts = ["%.2f (rel. int. %.1f)" % (c, a / unit) for (c, _, _, _), a in zip(groups, areas)]
        notes.append("¹H: one entry per group of picked lines, with relative integrals. Multiplicity, J and proton counts are not assigned.")
    elif nuc == "13C":
        parts = ["%.1f" % p for p, _ in sorted(body, reverse=True)]
        notes.append("¹³C: picked lines as they are; C–F multiplets are not grouped into quartets.")
    else:
        parts = ["%.1f" % c for c, _, _, _ in _cluster(body, 0.05)]
        if nuc == "19F":
            notes.append("¹⁹F: shifts as processed (no internal reference).")
    if aside:
        notes.append("¹H peaks set aside as possible contaminants: " + ", ".join("%.2f (%s)" % (p, tag) for p, _, tag in sorted(aside, reverse=True)) + ".")
    return {"nucleus": nuc, "line": head + ", ".join(parts).replace("-", "\u2212") + ".", "notes": notes, "source": source}


NUCLEUS_ELEMENT = {"1H": "H", "13C": "C", "19F": "F", "31P": "P", "11B": "B"}


def si_draft(case, rec):
    """Draft SI block for the isolated product of a synthesis record.

    Reviewed characterization is only what the record states in `characterization`. Peak lists read
    from the spectra are unassigned observations, and a list for a nucleus the formula does not
    contain is kept apart: those signals are not from the compound."""
    products = [m for m in rec.get("materials") or [] if str(m.get("id", "")).startswith("P")]
    name = products[0]["name"] if products else rec.get("title", rec["id"])
    formula = products[0].get("formula") if products else None
    try:
        atoms = chem.parse_formula(formula) if formula else None
    except ValueError:
        atoms = None
    result = rec.get("result") or {}
    prep = " ".join(rec.get("procedure") or [])
    lines, excluded, notes = [], [], []
    for a in case.acquisitions(rec):
        for s in a["spectra"]:
            acq_dir = case.layout.acquisition(a["folder"], s["acq"])
            try:
                got = _spectrum_line(acq_dir)
            except (nmr.NmrError, OSError, ValueError) as e:
                notes.append("%s acq %s (%s): %s" % (a["sample"], s["acq"], s["nucleus"], e))
                continue
            if got["line"]:
                row = {"sample": a["sample"], "acq": s["acq"], "nucleus": got["nucleus"], "text": got["line"]}
                element = NUCLEUS_ELEMENT.get(got["nucleus"])
                (excluded if atoms is not None and element and element not in atoms else lines).append(row)
            for n in got["notes"]:
                if n not in notes:
                    notes.append(n)
    reviewed = [str(x) for x in rec.get("characterization") or []]
    flags = rec.get("flags") or []
    blocking = [f for f in flags if f.get("tier") == "blocking"]
    ids = [rec["id"], rec.get("eln"), rec.get("legacy_id")]
    ids.extend(a.get("sample") for a in rec.get("nmr") or [])
    src = ", ".join(dict.fromkeys(str(x) for x in ids if x and str(x).lower() != "not yet assigned"))
    entry, missing, convention = si_format.make_entry(rec, products[0] if products else {}, src)
    names_to_check = []
    for row in rec.get("materials") or []:
        basis = row.get("name_basis")
        if isinstance(basis, dict) and (basis.get("kind") == "generated" or basis.get("generated")) and row.get("name"):
            names_to_check.append(dict(id=row["id"], name=row["name"], basis=basis.get("generated") or basis))
    notes.extend(convention)
    return {"id": rec["id"], "compound": name, "formula": formula, "preparation": prep, "basis": rec.get("procedure_basis", ""),
            "result": result, "proton_possible": atoms is None or "H" in atoms, "lines": lines, "excluded": excluded, "reviewed": reviewed,
            "reviewed_basis": rec.get("characterization_basis", ""), "notes": notes, "missing": missing,
            "blocking": blocking, "sources": src, "entry": entry, "flags": flags, "names_to_check": names_to_check}
