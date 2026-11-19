"""Case-scoped chemical search. Cached graphs are shared by duplicate material rows."""
from collections import Counter
from functools import lru_cache
import hashlib
import re
import threading

from . import chem, reference, structure as st, yamlio


@lru_cache(maxsize=4096)
def _entry(smiles):
    mol = st.molecule(smiles)
    if mol is None or not mol.GetNumAtoms():
        return None
    return (mol, st.Chem.MolToInchiKey(mol), st.Chem.PatternFingerprint(mol), st.MORGAN.GetFingerprint(mol))


def material_role(m):
    prefix = str(m.get("id", ""))[:1]
    return {"R": "reactant", "P": "product", "S": "agent", "A": "agent"}.get(prefix, "other")


def main_materials(rec):
    materials = [m for m in rec.get("materials") or [] if isinstance(m, dict)]
    reactants = [m for m in materials if material_role(m) == "reactant"]
    limiting = next((m for m in reactants if m.get("equiv") == 1), next(iter(reactants), {}))
    product = next((m for m in materials if material_role(m) == "product"), {})
    return limiting, product


def material_key(rec, material):
    smiles = st.material_smiles(rec, material)
    entry = _entry(smiles) if not st.REASON and isinstance(smiles, str) else None
    return entry[1] if entry else material.get("inchikey")


def _summary(rec):
    rows = []
    for m in rec.get("materials") or []:
        if not isinstance(m, dict):
            continue
        m = dict(m, smiles=st.material_smiles(rec, m))
        role = material_role(m)
        if (isinstance(m.get("smiles"), str) and _entry(m["smiles"]) or
                isinstance(m.get("inchikey"), str) and reference.KEY.fullmatch(m["inchikey"])):
            rows.append((role, m))
    pair = [material_key(rec, m) for m in main_materials(rec)]
    rxn = (rec.get("reaction") or {}).get("smiles", "") if isinstance(rec.get("reaction"), dict) else ""
    # The saved drawing includes species the researcher did not add as charge rows.
    sides = rxn.split(">")
    reaction = ([side.split(".") if side else [] for side in sides] if len(sides) == 3 else
                [[m["smiles"] for role, m in rows if role == r and m["smiles"]] for r in st.ROLES])
    info = {k: str(rec.get(k) or "") for k in ("id", "title", "key_result", "started")}
    return info, rows, reaction, tuple(pair)


def _query(text, smarts=False):
    if not isinstance(text, str) or not text.strip():
        raise st.StructureError("Enter a search structure.")
    with st.rdBase.BlockLogs():
        mol = st.Chem.MolFromSmarts(text) if smarts else st.molecule(text)
    if mol is None or not mol.GetNumAtoms():
        raise st.StructureError("Enter valid SMARTS or SMILES for this mode.")
    return mol


def pattern_svg(text):
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf8")) > st.MAX_BYTES:
        raise st.StructureError("Enter a readable SMARTS pattern.")
    if ">" not in text:
        return st._draw(_query(text, True))
    from rdkit.Chem import rdChemReactions
    try:
        reaction = rdChemReactions.ReactionFromSmarts(text)
        if reaction is None or not (reaction.GetNumReactantTemplates() or reaction.GetNumProductTemplates()):
            raise ValueError
        drawer = st.Draw.MolDraw2DSVG(480, 180)
        drawer.DrawReaction(reaction)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except (RuntimeError, ValueError) as exc:
        raise st.StructureError("Unreadable reaction search pattern.") from exc


@lru_cache(maxsize=1024)
def _highlight(smiles, atoms, bonds):
    return st._draw(_entry(smiles)[0], atoms, bonds)


def _match(row, mode, query, screen, threshold, graph=None):
    smiles = row.get("smiles")
    entry = graph or (_entry(smiles) if isinstance(smiles, str) else None)
    if not entry:
        return None
    mol, key, pattern, fp = entry
    score = None
    if mode == "exact":
        if key != screen:
            return None
        atoms = tuple(range(mol.GetNumAtoms()))
        bonds = tuple(range(mol.GetNumBonds()))
    elif mode == "similarity":
        score = st.DataStructs.TanimotoSimilarity(fp, screen)
        if score < threshold:
            return None
        # Show the matching Morgan environments on the hit, including partial matches.
        extra = st.rdFingerprintGenerator.AdditionalOutput()
        extra.AllocateBitInfoMap()
        st.MORGAN.GetFingerprint(mol, additionalOutput=extra)
        aa, bb = set(), set()
        for bit, environments in extra.GetBitInfoMap().items():
            if not screen[bit]:
                continue
            for center, radius in environments:
                aa.add(center)
                for idx in st.Chem.FindAtomEnvironmentOfRadiusN(mol, radius, center):
                    b = mol.GetBondWithIdx(idx)
                    aa.update((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))
                    bb.add(idx)
        atoms, bonds = tuple(sorted(aa)), tuple(sorted(bb))
    else:
        if not st.DataStructs.AllProbeBitsMatch(screen, pattern):
            return None
        atoms = mol.GetSubstructMatch(query, useChirality=True)
        if not atoms:
            return None
        bonds = tuple(mol.GetBondBetweenAtoms(atoms[b.GetBeginAtomIdx()], atoms[b.GetEndAtomIdx()]).GetIdx()
                      for b in query.GetBonds())
    if graph:
        # Highlights belong to the original bottle or material, including its isotopes and counterions.
        original = _entry(smiles)[0]
        indices = [atom.GetIntProp("_sourceIndex") for atom in mol.GetAtoms()]
        atoms = tuple(indices[i] for i in atoms)
        bonds = tuple(original.GetBondBetweenAtoms(indices[b.GetBeginAtomIdx()], indices[b.GetEndAtomIdx()]).GetIdx()
                      for b in (mol.GetBondWithIdx(i) for i in bonds))
    return dict(name=row.get("name", ""), formula=row.get("formula", ""), smiles=smiles, score=score,
                svg=_highlight(smiles, atoms, bonds))


SWITCHES = {"stereo", "salts", "isotopes", "charge"}


@lru_cache(maxsize=2048)
def _normal_parts(smiles, flags):
    from rdkit.Chem.MolStandardize import rdMolStandardize
    mol = st.molecule(smiles)
    if mol is None:
        return ()
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
        atom.SetIntProp("_sourceIndex", atom.GetIdx())
    parts = st.Chem.GetMolFrags(mol, asMols=True)
    charges = [st.Chem.GetFormalCharge(part) for part in parts]
    salt = "salts" in flags and min(charges) < 0 < max(charges)
    forms = []
    for part in parts:
        if "isotopes" in flags:
            for atom in part.GetAtoms():
                atom.SetIsotope(0)
            part = st.Chem.RemoveHs(part)
        if "stereo" in flags:
            st.Chem.RemoveStereochemistry(part)
        if "charge" in flags or salt:
            part = rdMolStandardize.Uncharger().uncharge(part)
        forms.append(part)
    return tuple(forms)


@lru_cache(maxsize=8192)
def _forms(smiles, flags):
    return tuple(sorted(st.Chem.MolToSmiles(p) for p in _normal_parts(smiles, flags)))


def _combined(parts):
    mol = parts[0]
    for part in parts[1:]:
        mol = st.Chem.CombineMols(mol, part)
    if len(parts) > 1:
        st.Chem.GetSymmSSSR(mol)  # CombineMols invalidates the ring information needed for fingerprints.
    return mol


@lru_cache(maxsize=2048)
def _graphs(smiles, flags, mode):
    parts = _normal_parts(smiles, flags)
    if not parts:
        return ()
    candidates = [_combined(parts)]
    if "salts" in flags and len(parts) > 1 and mode == "similarity":
        candidates.extend(parts)
    return [(m, None, st.Chem.PatternFingerprint(m) if mode == "substructure" else None,
             st.MORGAN.GetFingerprint(m) if mode == "similarity" else None) for m in candidates]


def _drawn_matcher(text, switches):
    flags = switches
    mol = _query(text)
    query = _forms(st.Chem.MolToSmiles(mol), flags)
    ionic_query = any(a.GetFormalCharge() for a in mol.GetAtoms())
    needed = Counter(query)
    def match(row):
        smiles = row.get("smiles")
        if not smiles or not _entry(smiles):
            return None
        forms = _forms(smiles, flags)
        match_flags = flags
        if "salts" in flags:
            if needed - Counter(forms):
                # An explicitly charged query can match the ion as it exists in the salt.
                if not ionic_query:
                    return None
                match_flags = tuple(f for f in flags if f != "salts")
                if Counter(_forms(text, match_flags)) - Counter(_forms(smiles, match_flags)):
                    return None
        elif query != forms:
            return None
        remaining = Counter(_forms(text, match_flags))
        atoms = []
        for part in _normal_parts(smiles, match_flags):
            form = st.Chem.MolToSmiles(part)
            if remaining[form]:
                atoms.extend(a.GetIntProp("_sourceIndex") for a in part.GetAtoms())
                remaining[form] -= 1
        selected = set(atoms)
        bonds = tuple(b.GetIdx() for b in _entry(smiles)[0].GetBonds()
                      if b.GetBeginAtomIdx() in selected and b.GetEndAtomIdx() in selected)
        return dict(name=row.get("name", ""), formula=row.get("formula", ""), smiles=smiles, score=None,
                    svg=_highlight(smiles, tuple(atoms), bonds))
    return match


def matcher(text, mode, threshold=0.7, switches=None):
    st.require()
    switches = [] if switches is None else switches
    if not isinstance(switches, list) or any(not isinstance(s, str) or s not in SWITCHES for s in switches):
        raise st.StructureError("Choose supported match options.")
    flags = tuple(sorted(set(switches)))
    if mode == "drawn" or (mode == "exact" and flags):
        return _drawn_matcher(text, flags)
    if mode not in ("exact", "similarity", "substructure"):
        raise st.StructureError("Choose a structure search mode.")
    if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
        raise st.StructureError("Similarity threshold must be between 0 and 1.")
    query = _query(text, mode == "substructure")
    screen = (st.Chem.MolToInchiKey(query) if mode == "exact" else st.MORGAN.GetFingerprint(query)
              if mode == "similarity" else st.Chem.PatternFingerprint(query))
    if not flags:
        return lambda row: _match(row, mode, query, screen, threshold)
    parts = _normal_parts(text, flags)
    relaxed = _combined(parts) if parts else query
    if mode == "substructure" and parts:
        relaxed = _query(st.Chem.MolToSmiles(relaxed), True)
    relaxed_screen = (st.MORGAN.GetFingerprint(relaxed) if mode == "similarity" else st.Chem.PatternFingerprint(relaxed))
    def match(row):
        best = _match(row, mode, query, screen, threshold)
        if best and mode == "substructure":
            return best
        for graph in _graphs(row["smiles"], flags, mode):
            hit = _match(row, mode, relaxed, relaxed_screen, threshold, graph)
            if hit and (not best or mode == "similarity" and hit["score"] > best["score"]):
                best = hit
        return best
    return match


def _count(side, query, screen):
    total = 0
    for smiles in side:
        entry = _entry(smiles)
        if entry and st.DataStructs.AllProbeBitsMatch(screen, entry[2]):
            total += len(entry[0].GetSubstructMatches(query, useChirality=True, maxMatches=0))
    return total


class Index:
    def __init__(self):
        self.records = {}
        self.lock = threading.Lock()

    def snapshot(self, case):
        st.require()
        with self.lock:
            current = {}
            for rid in case.layout.ids(occupied=True):
                try:
                    data = case.layout.record_path(rid).read_bytes()
                except FileNotFoundError:
                    continue  # unsaved working-copy folder, or a record just removed
                digest = hashlib.sha256(data).digest()
                cached = self.records.get(rid)
                if cached is None or cached[0] != digest:
                    try:
                        rec = yamlio.load(data)
                        if not isinstance(rec, dict) or rec.get("id") != rid:
                            continue
                        cached = digest, _summary(rec)
                    except (ValueError, yamlio.YAMLError):
                        continue
                current[rid] = cached
            self.records = current
            return [value for _, value in current.values()]

    def same_step(self, case, rid):
        entries = self.snapshot(case)
        pair = next((pair for info, _, _, pair in entries if info["id"] == rid), ())
        if not pair or not all(pair):
            return []
        hits = [info for info, _, _, other in entries if other == pair and info["id"] != rid]
        def rank(hit):
            result = re.search(r"(\d+(?:\.\d+)?)\s*%", hit["key_result"])
            return (float(result[1]) if result else -1, hit["started"], hit["id"])
        return sorted(hits, key=rank, reverse=True)

    def search(self, case, text, mode, role="any", threshold=0.7, scope="experiments", switches=None):
        st.require()
        if role not in ("any", "reactant", "product"):
            raise st.StructureError("Choose a material role.")
        hits = []
        if mode == "transformation":
            fields = text.split(">") if isinstance(text, str) else []
            if len(fields) != 3:
                raise st.StructureError("Enter fragment A>>fragment B.")
            queries = [_query(fields[i], True) for i in (0, 2)]
            screens = [st.Chem.PatternFingerprint(q) for q in queries]
            matched_product = matcher(fields[2], "substructure")
            for info, _, sides, _ in self.snapshot(case):
                left, right = [[_count(side, q, fp) for q, fp in zip(queries, screens)] for side in (sides[0], sides[2])]
                if left[0] > right[0] and left[1] < right[1]:
                    match = next(m for s in sides[2] if (m := matched_product(dict(smiles=s))))
                    hits.append(dict(info, **match, role="product"))
            return hits
        if ">" in text:
            parts = text.split(">")
            if len(parts) != 3 or not any(parts):
                raise st.StructureError("Enter a reaction with its species on the arrow sides.")
            # Match all requested species on their respective sides, including repeated species.
            queries = []
            for part in parts:
                patterns = part.split(".") if part else []
                if part and mode == "substructure":
                    # SMARTS can join two dotted segments with a ring closure (e.g. Ketcher R-group labels).
                    patterns = [st.Chem.MolToSmarts(f) for f in st.Chem.GetMolFrags(
                        _query(part, True), asMols=True, sanitizeFrags=False)]
                queries.append([matcher(s, mode, threshold, switches) for s in patterns])
            for info, _, sides, _ in self.snapshot(case):
                matches = [_match_side(q, side) for q, side in zip(queries, sides)]
                if all(group is not None for group in matches):
                    for r, group in zip(st.ROLES, matches):
                        if group and role in ("any", r):
                            hits.append(dict(info, **group[0], role=r))
                            break
            return hits
        match = matcher(text, mode, threshold, switches)
        for info, rows, sides, _ in self.snapshot(case):
            if scope == "reactions":
                if not sides[0] or not sides[2]:
                    continue
                rows = [(r, dict(smiles=s)) for r, side in zip(st.ROLES, sides) for s in side]
            elif scope == "all" and sides[0] and sides[2]:
                present = {(r, m["smiles"]) for r, m in rows}
                rows = rows + [(r, dict(smiles=s)) for r, side in zip(st.ROLES, sides) for s in side if (r, s) not in present]
            for side, row in rows:
                if role == "any" or role == side:
                    hit = match(row)
                    if hit:
                        hits.append(dict(info, **hit, role=side, material=row.get("id")))
        if mode == "similarity":
            hits.sort(key=lambda hit: hit["score"], reverse=True)
        return hits


def _match_side(queries, smiles):
    if len(queries) > len(smiles):
        return None
    candidates = [[(i, hit) for i, s in enumerate(smiles) if (hit := match(dict(smiles=s)))] for match in queries]
    owners = {}
    def assign(q, seen):
        for i, hit in candidates[q]:
            if i in seen:
                continue
            seen.add(i)
            if i not in owners or assign(owners[i][0], seen):
                owners[i] = (q, hit)
                return True
        return False
    if all(assign(q, set()) for q in range(len(queries))):
        return [hit for _, hit in owners.values()]
    return None


def sources(case, index, inventory_rows):
    from .structure_files import library_rows
    for row in library_rows(case):
        yield row, "compound library", "library"
    for info, rows, _, _ in index.snapshot(case):
        for _, row in rows:
            yield row, info["id"] + " " + row["id"], "record"
    for row in inventory_rows():
        yield row, "inventory " + row.get("location", ""), "bottle"


def resolve(text, case, index, inventory_rows):
    st.require()
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 4096:
        raise st.StructureError("Enter one name, label, CAS number, SMILES or InChI.")
    text = text.strip()
    with st.rdBase.BlockLogs():
        mol = st.Chem.MolFromInchi(text) if text.startswith("InChI=") else st.molecule(text)
    if mol and mol.GetNumAtoms() and all(a.GetAtomicNum() for a in mol.GetAtoms()):
        return [dict(smiles=st.Chem.MolToSmiles(mol), molfile=st.Chem.MolToMolBlock(mol), source="InChI" if text.startswith("InChI=") else "SMILES")]
    found = {}
    for row, source, _ in sources(case, index, inventory_rows):
        if any(str(row.get(k, "")).casefold() == text.casefold() for k in ("name", "id", "compound_id", "cas", "label")):
            entry = _entry(row["smiles"]) if row.get("smiles") else None
            if entry:
                found.setdefault(st.Chem.MolToSmiles(entry[0]), dict(smiles=row["smiles"], molfile=st.Chem.MolToMolBlock(entry[0]),
                                                                      name=row.get("name"), source=source))
    return list(found.values())


def _difference(smiles, other):
    if not other:
        return "different InChIKey suffix (source has no structure to compare)"
    def layers(value):
        inchi = st.Chem.MolToInchi(_entry(value)[0])
        return {k: re.findall(r"/[" + letters + r"][^/]*", inchi)
                for k, letters in (("stereochemistry", "btms"), ("isotope labelling", "i"), ("charge or protonation", "qp"))}
    a, b = layers(smiles), layers(other)
    return ", ".join(k for k in a if a[k] != b[k]) or "different InChI layers"


def identify(case, index, inventory_rows, species, provider, propose, client=None, *, once=False, refresh=False):
    """Identify the parsed species in drawing order. Only a validated key reaches the client."""
    if once and len(species) != 1:
        raise st.StructureError("Choose one species for this look-up.")
    local = {}
    wanted = {m["inchikey"][:14] for m in species}
    for row, source, kind in sources(case, index, inventory_rows):
        entry = _entry(row["smiles"]) if isinstance(row.get("smiles"), str) else None
        key = entry[1] if entry else row.get("inchikey")
        if not isinstance(key, str) or key[:14] not in wanted:
            continue
        name = "" if row.get("check_name") else row.get("name") or ""
        if kind == "library":
            source += " " + str(row.get("id", ""))
        hit = dict(name=name, source=source, kind=kind)
        if row.get("cas"):
            hit["cas"] = row["cas"]
        basis = row.get("name_basis") if isinstance(row.get("name_basis"), dict) else {}
        if basis.get("kind") == "generated" or basis.get("generated"):
            hit["generated"] = basis.get("generated") or basis
        if kind == "bottle":
            hit["source"] = "Bottle " + " · ".join(str(row[k]) for k in ("barcode", "product", "location") if row.get(k))
            hit["bottle"] = {k: v for k, v in row.items() if not k.startswith("_")}
        local.setdefault(key[:14], []).append((key, hit, row.get("smiles") if entry else None))
    results, lookups = {}, {}
    for m in species:
        key = m["inchikey"]
        # Two structures can share a standard key. Apply naming guards and formula checks to each structure.
        identity = key, m["smiles"]
        if identity in results:
            continue
        exact, close = [], []
        for other, hit, smiles in local.get(key[:14], []):
            if key == other:
                exact.append(hit)
            else:
                close.append(dict(name=hit["name"], source=hit["source"], difference=_difference(m["smiles"], smiles)))
        result = results[identity] = dict(close=close)
        if exact:
            uses = Counter(h["name"].casefold() for h in exact if h["kind"] == "record")
            result.update(state="notebook", matches=sorted(exact, key=lambda h: -uses[h["name"].casefold()]))
            continue
        result["state"] = "unsearched"
        if once or provider == "pubchem" and (key in lookups or len(lookups) < 10):
            if key not in lookups:
                try:
                    lookups[key] = reference.lookup_key(case.layout.project_root, key, refresh, client)
                except reference.LookupError as exc:
                    lookups[key] = str(exc)
            record = lookups[key]
            if isinstance(record, str):
                result.update(reason=record)
            else:
                ident = record["identity"]
                result["date"] = record["retrieved"]
                if ident is None:
                    result["state"] = "new"
                elif not chem.same_formula(ident.get("MolecularFormula"), m["formula"]):
                    result.update(state="conflict", reason="PubChem formula %s differs from the drawn formula %s." %
                                  (ident.get("MolecularFormula") or "(unavailable)", m["formula"]))
                else:
                    result.update(state="pubchem", name=ident.get("Title") or ident.get("IUPACName") or "",
                                  pubchem_cid=ident["CID"], cas=record.get("cas"),
                                  name_basis=dict(kind="pubchem", cid=ident["CID"], date=record["retrieved"]))
        if result["state"] in ("new", "unsearched"):
            result["proposal"] = propose(m["smiles"])
    return [results[m["inchikey"], m["smiles"]] for m in species]


def _stored_smiles(row, cached):
    smiles = row.get("smiles")
    if smiles and _entry(smiles):
        return smiles
    identity = cached.get(row.get("cas"))
    if not identity:
        return None
    for field in ("SMILES", "IsomericSMILES", "ConnectivitySMILES", "CanonicalSMILES"):
        smiles = identity.get(field)
        if smiles and _entry(smiles):
            return smiles
    return None


def bottles(root, inventory):
    st.require()
    cached = reference.cached_cas_identities(root)
    return [dict({k: v for k, v in row.items() if not k.startswith("_")}, smiles=smiles)
            for row in inventory if (smiles := _stored_smiles(row, cached))]


def search_inventory(case, index, rows, query, mode, threshold, switches, lookup=False, client=None):
    """Match bottle graphs and, for an exact query, resolve one identity to CAS numbers."""
    if mode not in ("exact", "substructure", "similarity") or not isinstance(query, str) or ">" in query:
        raise st.StructureError("Enter one molecule and choose a bottle search mode.")
    match = matcher(query, mode, threshold, switches)
    root = case.layout.project_root
    cached = reference.cached_cas_identities(root)
    cas_numbers = set()
    if mode == "exact":
        key = _entry(query)[1]
        for row, _, _ in sources(case, index, list):
            cas = row.get("cas")
            if not isinstance(cas, str) or not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas):
                continue
            entry = _entry(row["smiles"]) if row.get("smiles") else None
            if (entry[1] if entry else row.get("inchikey")) == key:
                cas_numbers.add(cas)
        cas_numbers.update(cas for cas, ident in cached.items() if ident.get("InChIKey") == key)
    hits, unresolved = [], []
    count = 0
    for row in rows:
        smiles = _stored_smiles(row, cached)
        if smiles:
            count += 1
            hit = match(dict(row, smiles=smiles))
            if hit:
                hits.append(dict({k: v for k, v in row.items() if not k.startswith("_")}, **hit, basis="stored structure"))
                continue
        if mode == "exact":
            unresolved.append(row)
    offer_lookup = mode == "exact" and not cas_numbers and not hits
    message = ""
    if offer_lookup and lookup:
        try:
            result = reference.lookup_key(root, key, client=client, include_cas=True)
            cas_numbers.update(result.get("cas_numbers", []))
            if result.get("cas"):
                cas_numbers.add(result["cas"])
            offer_lookup = False
            if not cas_numbers:
                message = "PubChem returned no CAS number for this structure."
        except reference.LookupError as exc:
            message = str(exc)
    for row in unresolved:
        if row.get("cas") in cas_numbers:
            hits.append(dict({k: v for k, v in row.items() if not k.startswith("_")}, basis="CAS of the drawn structure"))
    if mode == "similarity":
        hits.sort(key=lambda row: row["score"], reverse=True)
    return dict(bottles=hits, count=count, offer_lookup=offer_lookup, message=message)
