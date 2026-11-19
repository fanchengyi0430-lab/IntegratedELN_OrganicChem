"""Formula parsing, molecular weights, quantity checks and hazard prompts."""
import os
import re

from . import yamlio

# Standard atomic weights (IUPAC abridged values).
ELEMENTS = {
    "H": 1.008, "D": 2.014, "Li": 6.94, "Be": 9.0121831, "B": 10.81, "C": 12.011, "N": 14.007, "O": 15.999,
    "F": 18.998403, "Na": 22.989769, "Mg": 24.305, "Al": 26.981538, "Si": 28.085, "P": 30.973762, "S": 32.06,
    "Cl": 35.45, "K": 39.0983, "Ca": 40.078, "Sc": 44.955908, "Ti": 47.867, "V": 50.942, "Cr": 51.996,
    "Mn": 54.938043, "Fe": 55.845, "Co": 58.933194, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38, "Ga": 69.723,
    "Ge": 72.630, "As": 74.921595, "Se": 78.971, "Br": 79.904, "Rb": 85.468, "Sr": 87.62, "Y": 88.90584,
    "Zr": 91.224, "Mo": 95.95, "Ru": 101.07, "Rh": 102.90549, "Pd": 106.42, "Ag": 107.87, "Cd": 112.41,
    "In": 114.82, "Sn": 118.71, "Sb": 121.76, "Te": 127.60, "I": 126.90447, "Cs": 132.905452, "Ba": 137.33,
    "La": 138.91, "Ce": 140.12, "Sm": 150.36, "Yb": 173.05, "W": 183.84, "Re": 186.21, "Os": 190.23,
    "Ir": 192.22, "Pt": 195.08, "Au": 196.96657, "Hg": 200.59, "Tl": 204.38, "Pb": 207.2, "Bi": 208.98040,
}

_TOKEN = re.compile(r"([A-Z][a-z]?)|(\d+(?:\.\d+)?)|([()\[\]])|([·.*])")


def parse_formula(formula):
    """Element counts for a formula such as C16H8F12N2, Ca(OH)2 or CuSO4·5H2O.

    Raises ValueError for anything it cannot read, so a bad formula is never silently ignored.
    """
    text = str(formula or "").replace(" ", "").replace("·", "·")
    # RDKit appends a formal charge (e.g. NH4+ or Fe+2) to the composition.
    text = re.sub(r"[+-]\d*$", "", text)
    if not text:
        raise ValueError("empty formula")
    total = {}
    for part in re.split(r"[·*]|(?<=[A-Za-z0-9)\]])\.(?=\d*[A-Z(])", text):
        if not part:
            continue
        lead = re.match(r"^(\d+)(?=[A-Z(\[])", part)
        mult = int(lead.group(1)) if lead else 1
        if lead:
            part = part[lead.end():]
        stack = [{}]
        pos = 0
        while pos < len(part):
            m = _TOKEN.match(part, pos)
            if not m:
                raise ValueError("cannot read formula at '%s'" % part[pos:])
            el, num, br, _dot = m.groups()
            pos = m.end()
            if el:
                if el not in ELEMENTS:
                    raise ValueError("unknown element '%s'" % el)
                n = re.match(r"\d+(?:\.\d+)?", part[pos:])
                count = float(n.group()) if n else 1
                if n:
                    pos += n.end()
                stack[-1][el] = stack[-1].get(el, 0) + count
            elif br in ("(", "["):
                stack.append({})
            elif br in (")", "]"):
                if len(stack) < 2:
                    raise ValueError("unbalanced bracket")
                group = stack.pop()
                n = re.match(r"\d+(?:\.\d+)?", part[pos:])
                count = float(n.group()) if n else 1
                if n:
                    pos += n.end()
                for k, v in group.items():
                    stack[-1][k] = stack[-1].get(k, 0) + v * count
            else:
                raise ValueError("cannot read formula at '%s'" % part[pos - 1:])
        if len(stack) != 1:
            raise ValueError("unbalanced bracket")
        for k, v in stack[0].items():
            total[k] = total.get(k, 0) + v * mult
    return total


def same_formula(a, b):
    if a == b:
        return True
    try:
        return (parse_formula(a) == parse_formula(b) and
                re.findall(r"[+-]\d*$", str(a)) == re.findall(r"[+-]\d*$", str(b)))
    except ValueError:
        return False


def mol_weight(formula):
    return sum(ELEMENTS[el] * n for el, n in parse_formula(formula).items())


_AMOUNT = re.compile(r"(-?\d+(?:\.\d+)?)\s*(mg|g|kg|µL|uL|μL|mL|L)\b")


def parse_amount(text):
    """First mass and first volume in an amount string -> (mg or None, mL or None)."""
    mg = ml = None
    for val, unit in _AMOUNT.findall(str(text or "")):
        v = float(val)
        if unit in ("mg", "g", "kg") and mg is None:
            mg = v * {"mg": 1, "g": 1000, "kg": 1e6}[unit]
        elif unit in ("µL", "uL", "μL", "mL", "L") and ml is None:
            ml = v * {"µL": 0.001, "uL": 0.001, "μL": 0.001, "mL": 1, "L": 1000}[unit]
    return mg, ml


def check_material(m):
    """Deterministic consistency notes for one materials row (never changes the row)."""
    notes = []
    mw = m.get("mw")
    if m.get("formula"):
        try:
            calc = mol_weight(m["formula"])
            if isinstance(mw, (int, float)) and abs(calc - mw) > 0.06:
                notes.append("%s: MW %.3f in the record, %.3f from the formula %s" % (m.get("id"), mw, calc, m["formula"]))
        except ValueError as e:
            notes.append("%s: formula %s not readable (%s)" % (m.get("id"), m["formula"], e))
    name = str(m.get("name", ""))
    amount = str(m.get("amount", ""))
    has_assay = "%" in name or "wt" in name.lower() or "theoretical" in amount
    mmol = m.get("mmol")
    if isinstance(mw, (int, float)) and isinstance(mmol, (int, float)) and mmol > 0 and not has_assay:
        mg, _ = parse_amount(amount)
        if mg:
            expect = mmol * mw
            if abs(mg - expect) / expect > 0.05:  # wider than rounding of the printed mmol
                notes.append("%s: %s recorded, %.4g mg expected from %.4g mmol x MW %.2f" % (m.get("id"), amount.split(",")[0], expect, mmol, mw))
    return notes


_SOLUTION = re.compile(
    r"\d+(?:\.\d+)?\s*(?:wt\s*)?%|\b(?:aq|aqueous|solution|soln)\b|\bconc\."
    r"|\b\d+(?:\.\d+)?\s*[MN]\b"
    r"|\bin\s+(?:THF|Et2O|hexanes?|heptane|toluene|dioxane|water|MeOH|EtOH|DCM|pentane|cyclohexane)\b",
    re.I,
)


def assay_warning(material):
    """Check the recorded formulation when a reagent charge has been calculated."""
    if str(material["id"]).startswith("S") or material.get("assay") not in (None, ""):
        return None
    if material.get("equiv") is None and material.get("mmol") is None:
        return None
    if any(_SOLUTION.search(str(material.get(k, ""))) for k in ("name", "note", "amount")):
        return ("%s %s: looks like a solution or a reagent below full strength, but no assay is recorded. "
                "Enter wt%% or molarity, and say whether the figure refers to the active reagent or to the whole "
                "formulation, so the charge is calculated on the active reagent.") % (material["id"], material["name"])
    return None


# ---------------------------------------------------------------- hazard prompts
_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_rules_cache = {}


def _table(filename):
    path = os.path.join(_DATA, filename)
    mtime = os.stat(path).st_mtime_ns
    if _rules_cache.get(filename, (None,))[0] != mtime:
        with open(path, encoding="utf-8") as fh:
            _rules_cache[filename] = (mtime, yamlio.load(fh.read()))
    return _rules_cache[filename][1]


def hazard_rules():
    return _table("hazards.yaml")


def plan_text(record):
    procedure = record.get("procedure") or []
    steps = procedure if isinstance(procedure, list) else [procedure]
    return " ".join(str(p) for p in [record.get("conditions", "")] + steps)


def _temps(text):
    return [float(t.replace("−", "-")) for t in re.findall(r"([-−]?\d+(?:\.\d+)?)\s*°\s*C", text or "")]


def _hot_solvents(names, text):
    hottest = max(_temps(text), default=None)
    if hottest is None or not names:
        return
    for sol in _table("solvents.yaml")["solvents"]:
        if hottest > sol["bp_c"] and any(re.search(p, n, re.I) for p in sol["match"] for n in names):
            yield sol, hottest


_VESSEL = re.compile(r"\b(?:sealed|pressure[- ](?:tube|vial|vessel|flask)s?|screw[- ]cap(?:ped)?|crimp\w*"
                     r"|autoclave\w*|microwave[- ]vials?|reflux\w*|condensers?)\b", re.I)


def vessel_warnings(materials, text):
    if _VESSEL.search(text):
        return
    names = [str(m.get("name", "")) for m in materials or []
             if isinstance(m, dict) and str(m.get("id", "")).startswith("S")]
    for sol, hottest in _hot_solvents(names, text):
        yield ("Conditions reach %g °C, above the boiling point of %s (%g °C; %s). "
               "State the vessel (sealed tube, pressure vial) or reflux in the conditions or procedure."
               % (hottest, sol["name"], sol["bp_c"], sol["bp_source"]))


def hazard_prompts(materials, text=""):
    """Prompts from a short, editable rule list. They are reminders, not a safety assessment."""
    data = hazard_rules()
    names = [str(m.get("name", "")) for m in materials or []]
    joined = " | ".join(names).lower()
    out = []
    for rule in data.get("rules", []):
        need_all = rule.get("all", [])
        need_any = rule.get("any", [])
        ok_all = all(re.search(p, joined, re.I) for p in need_all)
        ok_any = (not need_any) or any(re.search(p, joined, re.I) for p in need_any)
        if (need_all or need_any) and ok_all and ok_any:
            out.append({"id": rule["id"], "level": rule.get("level", "caution"), "text": rule["text"]})
    for sol, hottest in _hot_solvents(names, text):
        basis = sol["bp_source"]
        if sol["retrieved"]:
            basis += ", " + str(sol["retrieved"])
        if not sol["reviewed"]:
            basis += "; not yet reviewed"
        out.append({"id": "above-bp-" + sol["name"], "level": "warning",
                    "text": ("%s boils at %g °C (%s) and the plan reaches %g °C: use a pressure-rated "
                             "sealed vessel behind a shield, and cool before opening."
                             % (sol["name"], sol["bp_c"], basis, hottest))})
    seen = set()
    uniq = []
    for p in out:
        if p["id"] not in seen:
            seen.add(p["id"])
            uniq.append(p)
    order = {"warning": 0, "caution": 1, "waste": 2}
    return sorted(uniq, key=lambda p: order.get(p["level"], 3))
