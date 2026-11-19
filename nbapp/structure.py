"""Local molecular identity, ChemDraw import and conservative reaction depictions."""
import base64
from functools import lru_cache
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

if __name__ == "__main__":
    # The embedded interpreter does not put the script directory on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nbapp import chem, runtime_info
else:
    from . import chem, runtime_info

MAX_BYTES = 2 * 1024 * 1024
MAX_MOLECULES = 200
PARSE_SECONDS = 15
NAME_SECONDS = 2
NAME_MAX_ATOMS = 100
ROLES = ("reactant", "agent", "product")
CHANGED = (102/255, 51/255, 138/255)  # --changed, also embedded in printable images
rdkit, REASON = runtime_info.rdkit_support()
if rdkit:
    from rdkit import Chem, DataStructs, rdBase
    from rdkit.Chem import rdFMCS, rdMolDescriptors, rdFingerprintGenerator
    from rdkit.Chem.Draw import rdMolDraw2D as Draw
    MORGAN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


class StructureError(ValueError):
    pass


class QueryFeature(StructureError):
    pass


def require():
    if REASON:
        raise StructureError(REASON)


def molecule(text):
    require()
    if not isinstance(text, str) or not text.strip():
        return None
    params = Chem.SmilesParserParams()
    params.parseName = False
    with rdBase.BlockLogs():
        return Chem.MolFromSmiles(text, params)


def material_smiles(rec, row):
    """Older notebooks keyed structural SMILES by material ID in a record-level map."""
    legacy = rec.get("smiles")
    return row.get("smiles") or (legacy.get(row.get("id")) if isinstance(legacy, dict) else None)


def reaction_sides(smiles):
    """Ordered SMILES and molecular identities on each side of a readable reaction."""
    if not isinstance(smiles, str) or len(smiles.encode("utf8")) > MAX_BYTES:
        return None
    fields = smiles.split(">")
    if len(fields) != 3 or not fields[0] or not fields[2]:
        return None
    sides = {}
    for role, field in zip(ROLES, fields):
        sides[role] = []
        for value in field.split(".") if field else ():
            mol = molecule(value)
            if mol is None:
                return None
            sides[role].append((value, Chem.MolToInchiKey(mol)))
    return sides


def formula(mol):
    require()
    return rdMolDescriptors.CalcMolFormula(mol, separateIsotopes=True)


def _propose_name(smiles):
    """Run only in the disposable worker. The single-name API does no OPSIN verification."""
    if REASON or sys.version_info < (3, 11):
        return dict(reason="Naming package unavailable")
    if len(smiles) > 4096:
        return dict(reason="Structure exceeds naming size limit")
    mol = molecule(smiles)
    if mol is None:
        return dict(reason="Unreadable structure")
    atoms = list(mol.GetAtoms())
    if len(atoms) > NAME_MAX_ATOMS:
        return dict(reason="Structure exceeds naming size limit")
    reasons = []
    if any(a.GetIsotope() for a in atoms):
        reasons.append("isotope label")
    if any(a.GetNumRadicalElectrons() for a in atoms):
        reasons.append("radical electrons")
    # Nonmetals, metalloids and noble gases. Treat borderline Po conservatively.
    nonmetals = {1, 2, 5, 6, 7, 8, 9, 10, 14, 15, 16, 17, 18, 32, 33, 34, 35, 36,
                 51, 52, 53, 54, 85, 86, 117, 118}
    if any(a.GetAtomicNum() not in nonmetals for a in atoms):
        reasons.append("metal")
    if reasons:
        return dict(reason="No generated name (" + ", ".join(reasons) + ")")
    try:
        import openclatura
    except ImportError:
        return dict(reason="Naming package unavailable")
    try:
        name = openclatura.name_smiles(smiles)
    except Exception:
        return dict(reason="Naming package failed")
    if not isinstance(name, str) or not name.strip():
        return dict(reason="Naming package returned no name")
    return dict(name=name.strip(), name_basis=dict(kind="generated", package="openclatura", version=openclatura.__version__))


def _draw(mol, atoms=(), bonds=(), png=False):
    drawer = (Draw.MolDraw2DCairo if png else Draw.MolDraw2DSVG)(240, 150)
    opts = drawer.drawOptions()
    opts.useBWAtomPalette()
    opts.setHighlightColour(CHANGED)
    opts.highlightBondWidthMultiplier = 14
    drawer.DrawMolecule(mol, list(atoms), list(bonds))
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def _species(mol, label):
    if mol is None or not mol.GetNumAtoms():
        raise StructureError("RDKit could not read this fragment.")
    if any(a.GetAtomicNum() == 0 or a.HasQuery() or a.HasProp("molFileAlias") for a in mol.GetAtoms()):
        if any(a.HasProp("molFileAlias") for a in mol.GetAtoms()):
            raise StructureError("Unresolved abbreviation.")
        raise QueryFeature("Unresolved abbreviation, wildcard or query atom. A material needs a complete structure.")
    if any(b.HasQuery() or b.GetBondType() == Chem.BondType.UNSPECIFIED for b in mol.GetBonds()):
        raise QueryFeature("Query bond. A material needs a complete structure.")
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)  # reaction bookkeeping is not part of molecular identity
    Chem.SanitizeMol(mol)
    f = formula(mol)
    try:
        mw, warning = round(chem.mol_weight(f), 3), ""  # three decimals, as for a typed formula
    except ValueError as exc:
        mw, warning = None, str(exc)
    key = Chem.MolToInchiKey(mol)
    if not key:
        raise StructureError("RDKit could not generate an InChIKey.")
    charged = Chem.GetFormalCharge(mol) != 0
    return dict(smiles=Chem.MolToSmiles(mol), inchikey=key, formula=f, mw=mw, warning=warning,
                mass=None if charged else rdMolDescriptors.CalcExactMolWt(mol),
                basis="Neutral mass unavailable for a charged species." if charged else "calculated, RDKit " + rdkit.__version__,
                label=label or (mol.GetProp("_Name").strip() if mol.HasProp("_Name") else ""), svg=_draw(mol))


def changed_groups(reactant, product):
    """Return only assignments common to every maximum graph and embedding."""
    require()
    params = rdFMCS.MCSParameters()
    params.Timeout = 2
    params.StoreAll = True
    params.BondTyper = rdFMCS.BondCompare.CompareOrderExact
    params.AtomCompareParameters.MatchFormalCharge = True
    for opts in (params.AtomCompareParameters, params.BondCompareParameters):
        opts.RingMatchesRingOnly = opts.CompleteRingsOnly = True
    deadline = time.monotonic() + 2
    result = rdFMCS.FindMCS([reactant, product], params)
    if result.canceled:
        return {"reason": "The common-substructure search timed out."}
    if result.numAtoms * 2 < product.GetNumHeavyAtoms():
        return {"reason": "The common part covers less than half of the product."}
    queries = list(result.degenerateSmartsQueryMolDict.values())
    if not queries and result.numAtoms == 1:
        # StoreAll omits bondless solutions. Check every possible common element.
        queries = [Chem.MolFromSmarts("[#%d%s]" % (z, ";R" if ring else ";!R"))
                   for z, ring in {(a.GetAtomicNum(), a.IsInRing()) for a in reactant.GetAtoms()}
                   if any(a.GetAtomicNum() == z and a.IsInRing() == ring for a in product.GetAtoms())]
    if not queries:
        return {"reason": "No unique common part could be assigned."}
    changes = {}
    for role, mol in (("reactant", reactant), ("product", product)):
        previous = None
        for query in queries:
            matches = mol.GetSubstructMatches(query, uniquify=False, maxMatches=2049)
            if len(matches) >= 2049:
                return {"reason": "Too many equivalent mappings to identify the change."}
            for match in matches:
                if time.monotonic() >= deadline:
                    return {"reason": "The common-substructure search timed out."}
                shared = {mol.GetBondBetweenAtoms(match[b.GetBeginAtomIdx()], match[b.GetEndAtomIdx()]).GetIdx()
                          for b in query.GetBonds()}
                group = (sorted(set(range(mol.GetNumAtoms())) - set(match)),
                         sorted(set(range(mol.GetNumBonds())) - shared))
                if previous is not None and previous != group:
                    return {"reason": "Equally good mappings colour different atoms or bonds."}
                previous = group
        if previous is None:
            return {"reason": "No unique common part could be assigned."}
        changes[role] = dict(atoms=previous[0], bonds=previous[1])
    if not any(group["atoms"] or group["bonds"] for group in changes.values()):
        if Chem.MolToSmiles(reactant) != Chem.MolToSmiles(product):
            return {"reason": "The common connectivity does not locate the stereochemical or isotopic change."}
    return dict(changes, reason="")


def _scheme(rows, roles, focus=None):
    from PIL import Image, ImageDraw
    sides = [[(i, rows[i]) for i in roles[r]] for r in ROLES]
    if not sides[0] or not sides[2]:
        return None
    left, right = focus if focus is not None else (roles["reactant"][0], roles["product"][0])
    primary = {"reactant": left, "product": right}
    if left in roles["reactant"] and right in roles["product"]:
        change = changed_groups(molecule(rows[left]["smiles"]), molecule(rows[right]["smiles"]))
    else:
        change = {"reason": "Select a limiting reactant and main product in this step to colour the change."}
    # Keep canonical atom order identical in the MCS and image.
    def render(colour):
        cols = [max(1, math.ceil(math.sqrt(len(side)))) for side in sides]
        heights = [math.ceil(len(side) / width) * 150 for side, width in zip(sides, cols)]
        heights[1] += 45
        height = max(heights)
        img = Image.new("RGB", (sum(cols) * 240, height), "white")
        x = 0
        for side, width, group_height, role in zip(sides, cols, heights, ROLES):
            y = (height - group_height) // 2
            for j, (idx, row) in enumerate(side):
                mark = change.get(role, {}) if colour and idx == primary.get(role) else {}
                tile = _draw(molecule(row["smiles"]), **mark, png=True)
                img.paste(Image.open(io.BytesIO(tile)), (x + j % width * 240, y + j // width * 150))
            if role == "agent":
                mid = x + 120 * width
                line = y + group_height - 24
                pen = ImageDraw.Draw(img)
                pen.line((mid - 46, line, mid + 46, line), fill="black", width=3)
                pen.polygon([(mid+46, line), (mid+33, line-6), (mid+33, line+6)], fill="black")
            x += 240 * width
        data = io.BytesIO()
        img.save(data, format="PNG")
        return base64.b64encode(data.getvalue()).decode("ascii")
    return dict(plain=render(False), colour=render(True) if not change["reason"] else None, reason=change["reason"])


def _point(value):
    try:
        x, y, *_ = map(float, (value or "").split())
        if math.isfinite(x) and math.isfinite(y):
            return x, y
    except ValueError:
        pass
    return None


def _arrow_roles(arrow, fragments, bond_length):
    """Work in arrow coordinates. Only unambiguously separated fragment bounds qualify."""
    start, end = _point(arrow.get("Tail3D")), _point(arrow.get("Head3D"))
    if start is None or end is None:
        box = arrow.get("BoundingBox", "").split()
        if len(box) != 4:
            return None
        end, start = _point(" ".join(box[:2])), _point(" ".join(box[2:]))
    if start is None or end is None:
        return None
    dx, dy = end[0]-start[0], end[1]-start[1]
    length = math.hypot(dx, dy)
    if not length or not math.isfinite(length):
        return None
    ux, uy = dx/length, dy/length
    reach = min(3*bond_length, 1.5*length)
    roles = {role: [] for role in ROLES}
    near = ambiguous = False
    head = arrow.get("ArrowheadHead")
    tail = arrow.get("ArrowheadTail")
    if tail not in (None, "None") and head in ("None", None):
        ux, uy, start = -ux, -uy, end
    for index, points in fragments:
        along = [(x-start[0])*ux + (y-start[1])*uy for x, y in points]
        across = [-(x-start[0])*uy + (y-start[1])*ux for x, y in points]
        lo, hi = min(along), max(along)
        bot, top = min(across), max(across)
        if hi < -reach or lo > length+reach or bot > 3*bond_length or top < -3*bond_length:
            continue
        near = True
        aligned = bot <= bond_length and top >= -bond_length
        if aligned and hi < 0:
            role = "reactant"
        elif aligned and lo > length:
            role = "product"
        elif 0 <= lo <= hi <= length and (bot > 0 or top < 0):
            role = "agent"
        else:
            ambiguous = True
            continue
        roles[role].append(index)
    if (head == "None" and tail in (None, "None") or
            head not in (None, "None") and tail not in (None, "None") or
            arrow.get("ArrowType") in ("Equilibrium", "Resonance", "RetroSynthetic")):
        ambiguous = True
    return near, None if ambiguous else roles


def _geometry(root, arrows, fragments):
    # Without coordinates on a common page we cannot disqualify another nearby arrow.
    try:
        bond_length = float(root.get("BondLength", "30"))
    except ValueError:
        return None
    if len(list(root.iter("page"))) != 1 or not math.isfinite(bond_length) or bond_length <= 0:
        return None
    # Table cell coordinates may use their own origin.
    if any(any(n.tag in ("fragment", "arrow") or n.get("ArrowType") for n in table.iter()) for table in root.iter("table")):
        return None
    positioned = []
    for frag, index in fragments:
        points = [_point(n.get("p")) for n in frag.findall("n")]
        if index is None or not points or None in points:
            return None
        positioned.append((index, points))
    candidates = []
    for arrow in arrows:
        if len(arrows) > 1 and arrow.get("AngularSize", "0") != "0":
            return None  # A curved shaft can pass near a molecule far from the straight chord.
        result = _arrow_roles(arrow, positioned, bond_length)
        if result is None:
            return None
        near, roles = result
        if near:
            if len(arrows) > 1:
                heads = [arrow.get(end) for end in ("ArrowheadHead", "ArrowheadTail")]
                directional = sum(h in ("Full", "HalfLeft", "HalfRight") for h in heads) == 1
                if (arrow.tag != "arrow" or not directional or
                        any(_point(arrow.get(end)) is None for end in ("Tail3D", "Head3D"))):
                    return None
            if not roles or not roles["reactant"] or not roles["product"]:
                return None
            candidates.append(roles)
            if len(candidates) > 1:
                return None
    return candidates[0] if candidates else None


def _cdxml(text, add):
    # ChemDraw commonly includes a SYSTEM doctype. Discard it before either parser.
    if re.search(r"<!ENTITY|<!DOCTYPE[^>]*\[", text, re.I):
        raise StructureError("XML entity declarations and internal subsets are unsupported.")
    root = ET.fromstring(re.sub(r'<!DOCTYPE\s+CDXML(?:\s+SYSTEM\s+("[^"]*"|\'[^\']*\'))?\s*>', "", text))
    if root.tag != "CDXML":
        raise StructureError("Expected a CDXML document.")
    fragments = []
    def visit(node):
        if node.tag == "fragment" and (node.find("n") is not None or node.find("b") is not None):
            # Nested fragments expand abbreviations inside this molecule.
            fragments.append(node)
            return
        for child in node:
            visit(child)
    visit(root)
    if len(fragments) > MAX_MOLECULES:
        raise StructureError("Import at most 200 molecules at once.")
    def read_fragment(frag):
        shell = ET.Element("CDXML", root.attrib)
        ET.SubElement(shell, "page").append(frag)
        with rdBase.CaptureErrorLog() as log:
            mols = Chem.MolsFromCDXML(ET.tostring(shell, encoding="utf-8"))
        if len(mols) != 1:
            details = " ".join(log.messages).strip()
            raise StructureError(details or "RDKit could not expand or read the fragment.")
        return mols[0]
    # Structure-to-name can add a standalone text object below its single molecule.
    # Atom labels inside fragments (and captions in multi-species drawings) are ambiguous.
    caption = ""
    if len(fragments) == 1:
        embedded = set(fragments[0].iter())
        texts = ["".join(s.text or "" for s in t.iter("s")).strip() for t in root.iter("t") if t not in embedded]
        if len(texts) == 1:
            caption = texts[0]
    indexed = [(frag, add(lambda: read_fragment(frag), frag.get("Name", ""), caption)) for frag in fragments]
    ids = {frag.get("id"): index for frag, index in indexed}
    nodes = {n.get("id"): n for n in root.iter() if n.get("id")}
    def references(step, attr):
        out = []
        for key in step.get(attr, "").split():
            children = [key] if key in ids else [f.get("id") for f in nodes[key].iter("fragment")] if key in nodes else []
            out.extend(ids[k] for k in children if k in ids and ids[k] is not None)
        return out
    groups = []
    steps = list(root.iter("step"))
    if steps and (None in ids or len(ids) != len(fragments)):
        return [], None, ["Reaction roles could not be read because fragment IDs are missing or ambiguous."]
    for step in steps:
        groups.append(dict(reactant=references(step, "ReactionStepReactants"),
                           product=references(step, "ReactionStepProducts"),
                           agent=references(step, "ReactionStepObjectsAboveArrow") + references(step, "ReactionStepObjectsBelowArrow")))
    arrows = [a for a in root.iter() if a.tag == "arrow" or a.tag == "graphic" and a.get("ArrowType")]
    if groups or not arrows or not fragments:
        return groups, None, []
    candidate = _geometry(root, arrows, indexed)
    if len(arrows) == 1 and candidate:
        return [candidate], None, []
    return [], candidate, ["Reaction roles could not be read from the drawing. Assign them in the preview."]


def editable_cdxml(parsed, worker=None):
    """Convert a text import to a working drawing; verify identity and roles before launch."""
    require()
    if not Chem.HasChemDrawCDXSupport() or parsed["errors"]:
        raise StructureError("This source cannot be converted safely. Paste or drop a CDXML drawing.")
    root = ET.Element("CDXML", BondLength="30")
    page = ET.SubElement(root, "page", id="1")
    ids = iter(range(2, 10000000))
    roles = {r: [] for r in ROLES}
    offsets = dict(reactant=20, agent=320, product=600, none=20)
    counts = dict.fromkeys(offsets, 0)
    rows = parsed["molecules"]
    if parsed["reaction"]:
        order = [i for r in ROLES for i in parsed["reaction"]["roles"][r]]
        rows = [rows[i] for i in order] + [row for row in rows if row["role"] == "none"]
    for row in rows:
        doc = ET.fromstring(Chem.MolToCDXMLBlock(molecule(row["smiles"])))
        frag = doc.find(".//fragment")
        if frag is None:
            raise StructureError("Cannot make a ChemDraw copy. Paste or drop CDXML.")
        mapping = {n.get("id"): str(next(ids)) for n in frag.iter() if n.get("id")}
        role = row["role"]
        points = [list(map(float, n.get("p").split())) for n in frag.iter() if n.get("p")]
        xmin = min((p[0] for p in points), default=0)
        ymin = min((p[1] for p in points), default=0)
        for node in frag.iter():
            for attr in ("id", "B", "E"):
                if node.get(attr) in mapping:
                    node.set(attr, mapping[node.get(attr)])
            if node.get("p"):
                x, y = map(float, node.get("p").split())
                node.set("p", "%.3f %.3f" % (x-xmin+offsets[role], y-ymin+counts[role]+20))
        if row["label"]:
            frag.set("Name", row["label"])
        counts[role] += max((p[1]-ymin for p in points), default=0)+70
        if role in roles:
            roles[role].append(frag.get("id"))
        page.append(frag)
    if parsed["reaction"]:
        y = counts["agent"]+40
        arrow = ET.SubElement(page, "arrow", id=str(next(ids)), ArrowheadHead="Full", ArrowheadType="Solid",
                              Tail3D="350 %d 0" % y, Head3D="490 %d 0" % y)
        ET.SubElement(ET.SubElement(page, "scheme", id=str(next(ids))), "step", id=str(next(ids)),
                      ReactionStepReactants=" ".join(roles["reactant"]), ReactionStepProducts=" ".join(roles["product"]),
                      ReactionStepObjectsAboveArrow=" ".join(roles["agent"]), ReactionStepArrows=arrow.get("id"))
    text = ET.tostring(root, encoding="unicode")
    checked = parse(text, worker=worker)
    def identities(species):
        return [(m["smiles"], m["label"]) for m in species]
    # A partial assignment remains in the draft. Its working drawing has no reaction arrow.
    expected = parsed["reaction"]["smiles"] if parsed["reaction"] else None
    actual = checked["reaction"]["smiles"] if checked["reaction"] else None
    if checked["errors"] or identities(checked["molecules"]) != identities(rows) or actual != expected:
        raise StructureError("The CDXML conversion changed a structure. Paste or drop the original CDXML.")
    return text


def _parse(text, step, focus=None, assignments=None, sketch=False, species_only=False):
    rows, errors, groups, notes = [], [], [], []
    proposal = None
    position = 0
    def add(reader, label="", caption=""):
        nonlocal position
        position += 1
        if position > MAX_MOLECULES:
            raise StructureError("Import at most 200 molecules at once.")
        try:
            mol = reader()
            row = _species(mol, label)
            if caption:
                row["caption"] = caption
            if sketch:
                row["molfile"] = Chem.MolToMolBlock(mol)
        except (ValueError, RuntimeError, OverflowError) as exc:
            errors.append(dict(position=position, reason=str(exc), query=isinstance(exc, QueryFeature)))
            return None
        rows.append(dict(row, position=position, role="none"))
        return len(rows)-1

    t = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if t.lstrip().startswith("<"):
        kind = "cdxml"
        groups, proposal, notes = _cdxml(t.lstrip(), add)
    elif t.lstrip().startswith("$RXN"):
        kind = "rxn"
        roles = {r: [] for r in ROLES}
        if t.lstrip().startswith("$RXN V3000"):
            for side, role in (("REACTANT", "reactant"), ("PRODUCT", "product"), ("AGENT", "agent")):
                match = re.search(r"M  V30 BEGIN "+side+r"\n(.*?)M  V30 END "+side, t, re.S)
                if match:
                    for ctab in re.findall(r"M  V30 BEGIN CTAB.*?M  V30 END CTAB", match[1], re.S):
                        block = "\n  RDKit\n\n  0  0  0     0  0            999 V3000\n"+ctab+"\nM  END\n"
                        roles[role].append(add(lambda: Chem.MolFromMolBlock(block)))
        else:
            head, *blocks = re.split(r"(?m)^\$MOL[ \t]*\n", t.lstrip())
            counts = head.rstrip().splitlines()[-1]
            nums = [int(counts[i:i+3].strip() or 0) for i in (0, 3, 6)]
            order = [role for role, count in zip(("reactant", "product", "agent"), nums) for _ in range(count)]
            if len(order) != len(blocks):
                raise StructureError("RXN molecule count does not match its blocks.")
            for role, block in zip(order, blocks):
                roles[role].append(add(lambda: Chem.MolFromMolBlock(block)))
        groups = [roles]
    elif re.search(r"(?m)^M  END|V[23]000\s*$", t):
        kind = "sdf" if "$$$$" in t else "mol"
        for block in re.split(r"(?m)^\$\$\$\$[ \t]*(?:\n|$)", t):
            if block.strip():
                mol = Chem.MolFromMolBlock(block, sanitize=not sketch)
                if sketch and mol is not None:
                    for fragment in Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False):
                        add(lambda: fragment)
                else:
                    add(lambda: mol)
    else:
        kind = "smi"
        if ">" in t:
            fields = t.strip().split(">")
            if len(fields) != 3 or not fields[0] or not fields[2]:
                raise StructureError("Use reactants>agents>products for a reaction.")
            groups = [{role: [add(lambda: molecule(s)) for s in field.split(".")] if field else []
                       for role, field in zip(ROLES, fields)}]
        else:
            for line in t.splitlines():
                if line.strip():
                    parts = line.split(None, 1)
                    add(lambda: molecule(parts[0]), parts[1].strip() if len(parts) == 2 else "")
    if not position:
        if kind != "cdxml":
            raise StructureError("No structures found.")
        notes.append("No structures found in this drawing.")
    if type(step) is not int or not 0 <= step < max(1, len(groups)):
        raise StructureError("Choose a step from this drawing.")
    reaction = scheme = None
    roles = {r: [i for i in groups[step][r] if i is not None] if groups else [] for r in ROLES}
    if assignments is not None:
        roles = dict(zip(ROLES, assignments))
        if any(i >= len(rows) for indices in roles.values() for i in indices):
            raise StructureError("A role refers to a species outside this preview.")
        proposal, notes = None, []
    if groups or assignments is not None:
        for role, indices in roles.items():
            for i in indices:
                rows[i]["role"] = role
        if roles["reactant"] and roles["product"]:
            reaction = dict(smiles=">".join(".".join(rows[i]["smiles"] for i in roles[r]) for r in ROLES), roles=roles)
            if not species_only:
                scheme = _scheme(rows, roles, focus)
        elif assignments is None:
            errors.append(dict(position="step %d" % (step+1), reason="The arrow needs a readable reactant and product."))
    svg = None
    if sketch and not reaction and len(rows) > 1:
        svg = _draw(molecule(".".join(row["smiles"] for row in rows)))
    return dict(kind=kind, molecules=rows, svg=svg, roles=roles, proposal=proposal, notes=notes, errors=errors, steps=len(groups), step=step, reaction=reaction, scheme=scheme)


def parse(text, step=0, focus=None, roles=None, sketch=False, *, worker=None, species_only=False):
    require()
    if not isinstance(text, str) or not text.strip():
        raise StructureError("Paste structure text first.")
    if "\x00" in text:
        raise StructureError("Use structure text without embedded NUL bytes.")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise StructureError("Structure text exceeds 2 MB.")
    if type(step) is not int:
        raise StructureError("Choose a numeric reaction step.")
    if focus is not None and (not isinstance(focus, (tuple, list)) or len(focus) != 2 or any(type(i) is not int or not -1 <= i < MAX_MOLECULES for i in focus)):
        raise StructureError("Choose focus species from the reaction step.")
    assignments = None
    if roles is not None:
        if not isinstance(roles, dict) or set(roles) != set(ROLES) or not all(isinstance(roles[r], list) for r in ROLES):
            raise StructureError("Supply ordered reactant, agent and product lists.")
        indices = [i for r in ROLES for i in roles[r]]
        if (len(indices) > MAX_MOLECULES or any(type(i) is not int or not 0 <= i < MAX_MOLECULES for i in indices)
                or len(set(indices)) != len(indices)):
            raise StructureError("Assign each species to at most one role.")
        assignments = tuple(tuple(roles[r]) for r in ROLES)
    run = worker.request if worker is not None else _bounded_parse
    return run(text, step, tuple(focus) if focus is not None else None, assignments, sketch, species_only)


class ParserWorker:
    """One serial pipe to a disposable RDKit process. Only the server owns this worker."""
    def __init__(self):
        self.process = None
        self.closed = False
        self.io_lock = threading.Lock()
        self.state_lock = threading.Lock()

    def _start(self):
        return subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _release(self):
        # Called with the I/O lock after all reads and writes have stopped.
        with self.state_lock:
            proc, self.process = self.process, None
        if proc is not None:
            proc.kill()
            proc.wait()
            proc.stdin.close()
            proc.stdout.close()

    def close(self):
        with self.state_lock:
            self.closed = True
            if self.process is not None:
                self.process.kill()  # also unblocks an in-flight pipe operation
        with self.io_lock:
            self._release()

    def propose(self, smiles):
        try:
            return self.request({"name": smiles}, timeout=NAME_SECONDS)
        except (OSError, StructureError) as exc:
            return dict(reason="Naming timed out" if "timed out" in str(exc) else "Naming package failed")

    def request(self, *args, timeout=None):
        with self.io_lock:
            if self.process is not None and self.process.poll() is not None:
                self._release()
            with self.state_lock:
                if self.closed:
                    raise StructureError("The notebook server is stopping.")
                if self.process is None:
                    self.process = self._start()
                proc = self.process
            expired = threading.Event()
            def stop():
                expired.set()
                proc.kill()
            watchdog = threading.Timer(PARSE_SECONDS if timeout is None else timeout, stop)
            watchdog.start()
            try:
                proc.stdin.write(json.dumps(args).encode("ascii") + b"\n")
                proc.stdin.flush()
                result = json.loads(proc.stdout.readline())
            except (OSError, ValueError):
                result = None
            finally:
                watchdog.cancel()
                watchdog.join()  # an old timer must never kill the next request
            if expired.is_set() or result is None:
                self._release()
                raise StructureError("Structure parsing timed out." if expired.is_set() else "RDKit could not read this drawing.")
            if "error" in result:
                raise StructureError(result["error"])
            return result


@lru_cache(maxsize=4)
def _bounded_parse(text, step, focus, assignments, sketch, species_only=False):
    # Native calls can block without returning to Python. A killed worker owns no notebook files.
    try:
        proc = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), str(step), json.dumps(focus),
                               json.dumps(assignments), str(int(sketch)), str(int(species_only))],
                              input=text.encode("utf-8"), capture_output=True, timeout=PARSE_SECONDS,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise StructureError("Structure parsing timed out.")
    if proc.returncode:
        raise StructureError("RDKit could not read this drawing.")
    result = json.loads(proc.stdout)
    if "error" in result:
        raise StructureError(result["error"])
    return result


def _reply(*args):
    try:
        if len(args) == 1 and isinstance(args[0], dict):
            return _propose_name(args[0]["name"])
        return _parse(*args)
    except (ValueError, RuntimeError, ET.ParseError, RecursionError, IndexError) as exc:
        return dict(error=str(exc))


if __name__ == "__main__":
    if sys.argv[1] == "--worker":
        for line in sys.stdin.buffer:
            result = _reply(*json.loads(line))
            sys.stdout.buffer.write(json.dumps(result).encode("ascii") + b"\n")
            sys.stdout.buffer.flush()
    else:
        result = _reply(sys.stdin.buffer.read(MAX_BYTES+1).decode("utf-8"), int(sys.argv[1]),
                        json.loads(sys.argv[2]) if len(sys.argv) > 2 else None, json.loads(sys.argv[3]) if len(sys.argv) > 3 else None,
                        len(sys.argv) > 4 and sys.argv[4] == "1", len(sys.argv) > 5 and sys.argv[5] == "1")
        sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))
