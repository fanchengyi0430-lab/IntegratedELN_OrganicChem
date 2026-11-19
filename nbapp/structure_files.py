"""Notebook-owned structure assets, compound library, and native working copies."""
import base64
import contextlib
import datetime
import hashlib
import json
from pathlib import Path
import secrets
import threading
import uuid

from . import chem, store, structure, structure_search, yamlio

SCHEME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".svg": "image/svg+xml", ".webp": "image/webp", ".bmp": "image/bmp", ".avif": "image/avif"}


def scheme_image(case, rec):
    try:
        named = case.scheme(rec)
        if named:
            path = case.layout.case_file(named)
            if path.suffix.lower() in SCHEME_TYPES:
                return path
    except store.StoreError:
        pass  # A bad stored path does not prevent a preview from the structures.
    return None


def scheme_folder(case, rid):
    case.layout.experiment_dir(rid)  # validate ID in both layouts
    return case.layout.attachment_dir(rid, "chemdraw")


def _stored_path(case, rid, rel, extensions):
    folder = scheme_folder(case, rid)
    path = case.layout.attachment_path(rid, rel)
    if path.parent != folder or path != (case.layout.root / rel).absolute() or path.suffix.lower() not in extensions:
        raise store.StoreError("Choose a supported file directly inside this experiment's scheme folder.")
    return path


def source_path(case, rid, rel):
    return _stored_path(case, rid, rel, {".cdxml"})


def _record_scheme(rec, parsed, text, step=0, focus=None, sketch=False, worker=None):
    roles = parsed["reaction"]["roles"]
    initial = focus or [roles["reactant"][0], roles["product"][0]]
    selected = list(initial)
    materials = rec.get("materials") or []
    if not isinstance(materials, list):
        raise store.StoreError("Materials must be a list.")
    materials = [m for m in materials if isinstance(m, dict)]
    reactants = [m for m in materials if structure_search.material_role(m) == "reactant"]
    limiting = next((m for m in reactants if m.get("equiv") == 1), next(iter(reactants), None))
    product = next((m for m in materials if structure_search.material_role(m) == "product"), None)
    for i, (role, material) in enumerate((("reactant", limiting), ("product", product))):
        if material is not None:
            mol = structure.molecule(structure.material_smiles(rec, material))
            key = structure.Chem.MolToInchiKey(mol) if mol else material.get("inchikey")
            selected[i] = next((j for j in roles[role] if parsed["molecules"][j]["inchikey"] == key), -1)
    return (parsed if selected == initial else structure.parse(text, step, selected, roles, sketch, worker=worker))["scheme"]


def preview_sources(rec, materials=True):
    if structure.REASON:
        return
    reaction = rec.get("reaction")
    if isinstance(reaction, dict) and isinstance(reaction.get("smiles"), str) and ">" in reaction["smiles"]:
        yield reaction["smiles"]
    if not materials:
        return
    sides = {role: [] for role in structure.ROLES}
    for m in rec.get("materials") or []:
        if isinstance(m, dict):
            role = structure_search.material_role(m)
            smiles = structure.material_smiles(rec, m)
            if role in sides and isinstance(smiles, str) and structure_search._entry(smiles):
                sides[role].append(smiles)
    if sides["reactant"] and sides["product"]:
        yield ">".join(".".join(sides[r]) for r in structure.ROLES)
    elif any(sides.values()):
        yield ".".join(smiles for role in structure.ROLES for smiles in sides[role])


def record_preview(rec, worker=None, *, materials=False):
    for text in preview_sources(rec, materials):
        try:
            if ">" not in text:
                mol = structure.molecule(text)
                if mol is not None:
                    png = base64.b64encode(structure._draw(mol, png=True)).decode("ascii")
                    return dict(plain=png, colour=None, reason="")
            parsed = structure.parse(text, worker=worker)
            if parsed["reaction"] and not parsed["errors"]:
                return _record_scheme(rec, parsed, text, worker=worker)
        except structure.StructureError:
            continue
    return None


def _sketch(draft):
    text = draft.get("ket")
    if text is None:
        return None
    if not isinstance(text, str) or len(text.encode("utf8")) > structure.MAX_BYTES:
        raise store.StoreError("A Ketcher sketch must fit in 2 MB.")
    try:
        nodes = json.loads(text)["root"]["nodes"]
        if not isinstance(nodes, list) or not nodes:
            raise ValueError
    except (TypeError, KeyError, ValueError, RecursionError):
        raise store.StoreError("Expected a Ketcher drawing with structure nodes.") from None
    return text


def sketch_input(case, rid, material=None):
    """Open only the experiment's source. Extract a single species for a material row."""
    rec, _ = case.read(rid)
    row = (rec.get("reaction") or {}) if material is None else next(
        (m for m in rec.get("materials", []) if m["id"] == material), {})
    rel = row.get("drawing", "")
    smiles = structure.material_smiles(rec, row) if material else row.get("smiles")
    if not material and not smiles:
        sides = [".".join(s for m in rec.get("materials", []) if structure_search.material_role(m) == role
                          and (s := structure.material_smiles(rec, m))) for role in structure.ROLES]
        smiles = ">".join(sides) if sides[0] and sides[2] else ".".join(s for s in sides if s)
    entries = {a["path"] for a in rec.get("attachments", []) if a.get("kind") == "sketch"}
    if not material and rel.endswith(".rxn") and rel in entries:
        path = _stored_path(case, rid, rel, {".rxn"})
        return dict(text=WorkingCopies._read(path).decode("utf8"), fresh=False)
    if not rel.endswith(".ket"):
        return dict(text=smiles or "", fresh=bool(smiles))
    path = _stored_path(case, rid, rel, {".ket"})
    if rel not in entries:
        raise store.StoreError("The stored sketch is missing from the attachments.")
    if material:
        for ext in (".rxn", ".mol"):
            companion = path.with_suffix(ext)
            if case.layout.relative(companion) in entries:
                parsed = structure.parse(WorkingCopies._read(companion).decode("utf8"), sketch=True)
                if len(parsed["molecules"]) != 1 or parsed["kind"] == "rxn":
                    for m in parsed["molecules"]:
                        if m["smiles"] == smiles or m["inchikey"] == row.get("inchikey"):
                            return dict(text=m["molfile"], fresh=False)
                    return dict(text=smiles or "", fresh=True)
                break
    return dict(text=WorkingCopies._read(path).decode("utf8"), fresh=False)


def material_scheme_change(reaction, target, before, after, external, name=None):
    """Project a row edit against one side. Both the review and the locked save use this decision."""
    if not isinstance(target, str) or not isinstance(after, str):
        raise store.StoreError("Choose a material and a replacement structure.")
    if any(isinstance(v, str) and len(v.encode("utf8")) > structure.MAX_BYTES for v in (before, after, reaction)):
        raise store.StoreError("Structure text exceeds 2 MB.")
    if (not reaction and not external) or before == after:
        return {}
    old, new = structure.molecule(before), structure.molecule(after)
    if new is None:
        raise store.StoreError("The replacement material has no readable structure.")
    if old and structure.Chem.MolToSmiles(old) == structure.Chem.MolToSmiles(new):
        return {}
    role = structure_search.material_role({"id": target})
    sides = structure.reaction_sides(reaction)
    old_key = structure.Chem.MolToInchiKey(old) if old else None
    side = (sides or {}).get(role, [])
    match = next((i for i, (_, key) in enumerate(side) if key == old_key), None)
    if external or match is None:
        why = "The scheme image was supplied separately." if external else "The old structure is absent on the %s side." % role
        label = "%s (%s)" % (target, name) if name else target
        return dict(mismatch=True, message="The scheme no longer matches material %s. %s" % (label, why))
    side[match] = (after, None)
    updated = ">".join(".".join(value for value, _ in sides[r]) for r in structure.ROLES)
    return dict(smiles=updated, message="The scheme follows the change to %s on the %s side." % (target, role))


def _updated_scheme(smiles, worker=None):
    from rdkit.Chem import rdChemReactions
    rxn = rdChemReactions.ReactionFromSmarts(smiles, useSmiles=True)
    text = rdChemReactions.ReactionToRxnBlock(rxn, separateAgents=True)
    parsed = structure.parse(text, worker=worker)
    actual = structure.reaction_sides((parsed["reaction"] or {}).get("smiles"))
    expected = structure.reaction_sides(smiles)
    if parsed["errors"] or not actual or any([k for _, k in actual[r]] != [k for _, k in expected[r]] for r in structure.ROLES):
        raise store.StoreError("Could not preserve all species and roles in the regenerated scheme.")
    return text, parsed


def _link_materials(draft, species, rows, prior, source):
    linked = draft.get("material_ids", [])
    positions = draft.get("material_positions", {})
    if not isinstance(linked, list) or not isinstance(positions, dict):
        raise store.StoreError("Expected material IDs and species positions from the preview.")
    by_position = {m["position"]: m for m in species}
    by_key = {m["inchikey"]: m for m in species}
    for mid, pos in positions.items():
        if mid not in linked or type(pos) is not int or pos not in by_position:
            raise store.StoreError("A material refers to an unknown species in this preview.")
        prior[mid] = by_position[pos]["smiles"]
    for mid, row in rows.items():
        if mid in linked and row.get("inchikey") in by_key:
            row["drawing"] = source
            if mid not in positions:
                prior[mid] = by_key[row["inchikey"]]["smiles"]
    return linked


def prepare(case, rid, rec, drafts, by, old=None, library=None, worker=None):
    """Prepare bytes and metadata in memory; Case.write installs them at commit."""
    files = {}
    if not isinstance(drafts, list):
        raise store.StoreError("Expected a list of structure sources.")
    folder = scheme_folder(case, rid)
    attachments = rec.get("attachments", [])
    if not isinstance(attachments, list) or not all(isinstance(a, dict) for a in attachments):
        raise store.StoreError("Attachments must be a list of maps.")
    rec["attachments"] = attachments = attachments.copy()
    old = old or {}
    # The edit form can already show the accepted preview. Replay all replacements
    # against the locked record, including successive edits to the same material.
    saved_reaction = old.get("reaction")
    projected = [d["schemeState"].get("smiles") for d in drafts
                 if isinstance(d, dict) and d.get("target") and isinstance(d.get("schemeState"), dict)]
    if (isinstance(saved_reaction, dict) and isinstance(rec.get("reaction"), dict)
            and rec["reaction"].get("drawing") == saved_reaction.get("drawing") and rec["reaction"].get("smiles") in projected):
        rec["reaction"] = saved_reaction.copy()
    prior_smiles = {m["id"]: structure.material_smiles(old, m) for m in old.get("materials") or [] if isinstance(m, dict) and "id" in m}
    edited_materials = set()
    labels = {}
    if isinstance(rec.get("materials"), list):
        rec["materials"] = [dict(m) if isinstance(m, dict) else m for m in rec["materials"]]
    rows = {m["id"]: m for m in rec.get("materials") or [] if isinstance(m, dict) and isinstance(m.get("id"), str)}
    for draft in drafts:
        if not isinstance(draft, dict):
            raise store.StoreError("Expected pasted structure text.")
        text = draft.get("text")
        ket = _sketch(draft)
        parsed = structure.parse(text, draft.get("step", 0), draft.get("focus"), draft.get("roles"), bool(ket), worker=worker)
        if ket and (parsed["kind"] not in ("mol", "rxn") or parsed["errors"]):
            raise store.StoreError("A sketch needs a complete, readable MOL or RXN drawing.")
        if not parsed["molecules"]:
            raise store.StoreError("No readable structures to save.")
        stem = "structure-" + uuid.uuid4().hex
        def asset(suffix, content, kind, note):
            path = folder / (stem + suffix)
            rel = case.layout.relative(path)
            files[path] = content
            attachments.append(dict(path=rel, kind=kind, size=len(content), sha256=hashlib.sha256(content).hexdigest(),
                                    added=store._now().isoformat(), by=by, note=note))
            return rel
        origin = "ChemDraw " + ("edit" if draft.get("edited") else "import" if draft.get("filename") else "paste")
        origin = ("Drawn in the app" if ket else origin) + ", " + datetime.date.today().isoformat()
        rel = asset("." + parsed["kind"], text.encode("utf-8"), "sketch" if ket else "chemdraw", origin)
        if ket:
            rel = asset(".ket", ket.encode("utf8"), "sketch", origin)
        target = draft.get("target")
        if target is not None and not isinstance(target, str):
            raise store.StoreError("Choose a material ID for this edit.")
        old_smiles = prior_smiles.get(target)
        linked = _link_materials(draft, parsed["molecules"], rows, prior_smiles, rel)
        positions = {pos: rows[mid] for mid, pos in draft.get("material_positions", {}).items() if mid in rows}
        selected = draft.get("library", [])
        if not isinstance(selected, list):
            raise store.StoreError("Choose species to save to the library.")
        species = {m["position"]: m for m in parsed["molecules"]}
        for choice in selected:
            if not isinstance(choice, dict) or type(choice.get("position")) is not int or choice["position"] not in species:
                raise store.StoreError("Unknown library species.")
            pos = choice["position"]
            mol, final = species[pos], positions.get(pos)
            if final and final.get("inchikey") != mol["inchikey"]:
                continue
            if library is not None:
                library.append(_compound(mol, final or choice, origin, ket, parsed))
        name_drawings = draft.get("name_drawings", {})
        if not isinstance(name_drawings, dict):
            raise store.StoreError("Expected labelled ChemDraw copies by species position.")
        named_sources = {}
        for key, cdxml in name_drawings.items():
            row = next((m for m in species.values() if str(m["position"]) == key), None)
            checked = structure.parse(cdxml, worker=worker)
            if (not row or checked["kind"] != "cdxml" or checked["errors"] or len(checked["molecules"]) != 1 or
                    checked["molecules"][0]["inchikey"] != row["inchikey"] or
                    not (checked["molecules"][0].get("caption") or checked["molecules"][0]["label"])):
                raise store.StoreError("The ChemDraw name needs a labelled copy of the same structure.")
            named_rel = asset("-name-" + key + ".cdxml", cdxml.encode("utf8"), "chemdraw", "Name from ChemDraw")
            labelled = checked["molecules"][0]
            labels[named_rel] = (labelled.get("caption") or labelled["label"]).strip()
            named_sources[row["position"]] = named_rel
            final = positions.get(row["position"])
            if final and final.get("inchikey") == row["inchikey"]:
                final["drawing"] = named_rel
        if target:
            row = rows.get(target)
            if row is None or linked != [target] or len(parsed["molecules"]) != 1 or parsed["reaction"]:
                raise store.StoreError("A material edit needs one structure for an existing material.")
            row["drawing"] = named_sources.get(parsed["molecules"][0]["position"], rel)
            new_smiles = parsed["molecules"][0]["smiles"]
            prior_smiles[target] = new_smiles
            edited_materials.add(target)
            external = bool((rec.get("scheme_image") or case.scheme(rec)) and not scheme_options(case, rec))
            change = material_scheme_change((rec.get("reaction") or {}).get("smiles"), target, old_smiles, new_smiles, external)
            if change.get("mismatch"):
                row["scheme_mismatch"] = True
            if not change.get("smiles"):
                continue
            row.pop("scheme_mismatch", None)
            text, parsed = _updated_scheme(change["smiles"], worker)
            origin = "Drawn in the app, " + datetime.date.today().isoformat()
            rel = asset("-reaction.rxn", text.encode("utf8"), "sketch", origin)
        elif draft.get("materialOnly"):
            continue
        if parsed["reaction"]:
            rec["reaction"] = dict(smiles=parsed["reaction"]["smiles"], source=origin, drawing=rel)

            pending_scheme = (folder / Path(rec.get("scheme_image") or "").name) in files
            if target or pending_scheme or not (rec.get("scheme_image") or case.scheme(rec)) or draft.get("replace") is True:
                drawing = (_record_scheme(rec, parsed, text, worker=worker) if target else
                           _record_scheme(rec, parsed, text, draft.get("step", 0), draft.get("focus"), bool(ket), worker))
                if not target:
                    for m in rows.values():
                        m.pop("scheme_mismatch", None)
                if drawing["colour"]:
                    asset("-plain.png", base64.b64decode(drawing["plain"]), "scheme", "RDKit plain scheme")
                rec["scheme_image"] = asset(".png", base64.b64decode(drawing["colour"] or drawing["plain"]),
                                            "scheme", "RDKit reaction scheme. " + drawing["reason"])
        elif draft.get("edited") and draft.get("replaces_reaction"):
            rec.pop("reaction", None)
            if draft.get("replace") and scheme_options(case, rec):
                rec.pop("scheme_image", None)
    for mid in edited_materials:
        actual = structure.molecule(structure.material_smiles(rec, rows[mid]))
        if actual is None or structure.Chem.MolToSmiles(actual) != prior_smiles[mid]:
            raise store.StoreError("The accepted drawing and material %s differ. Review the material before saving." % mid)
        if isinstance(rec.get("smiles"), dict) and mid in rec["smiles"]:
            rec["smiles"] = dict(rec["smiles"], **{mid: prior_smiles[mid]})
    for row in rows.values():
        if row.get("name_basis") == {"kind": "chemdraw"} and row.get("drawing") in labels and row.get("name") != labels[row["drawing"]]:
            raise store.StoreError("The ChemDraw label and accepted material name differ.")
    return files


def scheme_options(case, rec):
    path = rec.get("scheme_image")
    entries = {a.get("path"): a for a in rec.get("attachments") or [] if isinstance(a, dict)}
    note = entries.get(path, {}).get("note", "")
    if not isinstance(path, str) or not str(note).startswith("RDKit reaction scheme. "):
        return None
    plain = path[:-4] + "-plain.png"
    return dict(plain=plain if plain in entries else path, colour=path if plain in entries else None,
                reason=note[len("RDKit reaction scheme. "):])


@contextlib.contextmanager
def install(files):
    made = []
    try:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                made.append(path)
                stream.write(data)
        yield
    except Exception:
        for path in reversed(made):
            path.unlink(missing_ok=True)
        raise


def library_rows(case):
    path = case.layout.case_file("compounds.yaml")
    try:
        rows = yamlio.load(path.read_bytes()) if path.exists() else []
    except (yamlio.YAMLError, OSError) as exc:
        raise store.StoreError("Could not read compounds.yaml.") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise store.StoreError("compounds.yaml must contain a list of compounds.")
    for row in rows:
        if "name_basis" in row and not store.valid_name_basis(row["name_basis"]):
            raise store.StoreError("Invalid name_basis on library entry %s." % row.get("id", "?"))
    return rows


def library(case, query="", fragment=""):
    structure.require()
    rows = library_rows(case)
    match = structure_search.matcher(fragment, "substructure") if fragment else None
    hits = []
    for row in rows:
        if query.casefold() not in row.get("name", "").casefold():
            continue
        mol = structure.molecule(row.get("smiles"))
        if mol is None:
            continue
        hit = match(row) if match else {"svg": structure._draw(mol)}
        if hit:
            try:
                weight = round(chem.mol_weight(row["formula"]), 3)
            except ValueError:
                weight = None
            hits.append(dict(row, svg=hit["svg"], mw=weight))
    return hits


def _compound(mol, values, source, ket, parsed):
    name = values.get("name", mol["label"])
    if not isinstance(name, str):
        raise store.StoreError("Enter a compound name or leave it empty.")
    entry = dict(id=uuid.uuid4().hex, name=name)
    if "name_basis" in values:
        if not store.valid_name_basis(values["name_basis"]):
            raise store.StoreError("Invalid library name_basis.")
        entry["name_basis"] = values["name_basis"]
    elif name:
        entry["name_basis"] = {"kind": "entered"}
    if values.get("cas"):
        entry["cas"] = values["cas"]
    entry.update({k: mol[k] for k in ("smiles", "inchikey", "formula")}, source=source)
    if ket:
        entry["sketch"] = ket if len(parsed["molecules"]) == 1 and parsed["kind"] == "mol" else mol["molfile"]
    return entry


@contextlib.contextmanager
def install_compounds(case, additions):
    """Called under the record lock. Undo the library update if the record cannot be installed."""
    if not additions:
        yield 0
        return
    rows = library_rows(case)
    known = {(r.get("inchikey"), r.get("name")) for r in rows}
    count = 0
    for entry in additions:
        identity = entry["inchikey"], entry["name"]
        if identity not in known:
            known.add(identity)
            rows.append(entry)
            count += 1
    if not count:
        yield 0
        return
    path = case.layout.case_file("compounds.yaml")
    before = path.read_bytes().decode("utf8") if path.exists() else None
    store._write_atomic(path, yamlio.dump(rows))
    try:
        yield count
    except Exception:
        if before is None:
            path.unlink()
        else:
            store._write_atomic(path, before)
        raise


def add_compounds(case, body):
    ket = _sketch(body)
    parsed = structure.parse(body.get("text"), body.get("step", 0), sketch=bool(ket))
    if ket and (parsed["errors"] or parsed["kind"] not in ("mol", "rxn")):
        raise store.StoreError("A library compound needs a complete structure.")
    positions = body.get("positions")
    if not isinstance(positions, list) or not positions or any(type(p) is not int for p in positions):
        raise store.StoreError("Choose species to save to the library.")
    source = ("Drawn in the app" if ket else str(body.get("filename") or "ChemDraw paste")) + ", " + datetime.date.today().isoformat()
    entries = [_compound(m, {}, source, ket, parsed) for m in parsed["molecules"] if m["position"] in positions]
    with case._record_lock(), install_compounds(case, entries) as count:
        return dict(added=count)


class WorkingCopies:
    """Routes accept opaque session IDs. Paths are always re-derived and checked."""
    def __init__(self):
        self.sessions = {}
        self.lock = threading.RLock()

    def start(self, case, body, launch, worker=None):
        structure.require()
        rid = body.get("id")
        if set(body) - {"id", "draft", "from", "step", "roles", "expected", "scheme", "material"}:
            raise store.StoreError("Choose an experiment, not a file path.")
        with self.lock, case._record_lock():
            new = rid is None
            source_id = rid or body.get("from")
            rec = case.read(source_id)[0] if source_id else {}
            rid = case.next_id() if new else rid
            folder = scheme_folder(case, rid)
            extensions = {".cdxml", ".smi", ".rxn", ".mol", ".sdf"}
            latest = next((a["path"] for a in reversed(rec.get("attachments") or [])
                           if isinstance(a, dict) and a.get("kind") == "chemdraw"
                           and Path(a.get("path", "")).suffix.lower() in extensions), None)
            latest = latest or (rec.get("reaction") or {}).get("drawing") or (rec.get("sources") or {}).get("chemdraw")
            if body.get("scheme") and (rec.get("reaction") or {}).get("drawing"):
                latest = rec["reaction"]["drawing"]
            text = body.get("draft")
            if body.get("material") and not text:
                row = next((m for m in rec.get("materials", []) if m.get("id") == body["material"]), {})
                text = structure.material_smiles(rec, row)
                rel = row.get("drawing", "")
                if text and rel.lower().endswith(".cdxml"):
                    original = self._read(source_path(case, source_id, rel)).decode("utf8")
                    parsed = structure.parse(original, worker=worker)
                    mol = structure.molecule(text)
                    if (mol and not parsed["errors"] and len(parsed["molecules"]) == 1 and
                            parsed["molecules"][0]["inchikey"] == structure.Chem.MolToInchiKey(mol)):
                        text = original
                if not text:
                    raise store.StoreError("The material has no structure.")
            replaces_reaction = bool(latest and latest == (rec.get("reaction") or {}).get("drawing"))
            if not text and latest and Path(latest).suffix.lower() in extensions:
                source = _stored_path(case, source_id, latest, extensions)
                text = self._read(source).decode("utf-8")
            previous = []
            if text:
                parsed = structure.parse(text, body.get("step", 0), roles=body.get("roles"), worker=worker)
                if body.get("expected") is not None:
                    expected = structure.parse(body["expected"], sketch=True, worker=worker)
                    def identities(result):
                        return sorted((m["role"], m["inchikey"]) for m in result["molecules"])
                    if (parsed["kind"] != "cdxml" or parsed["errors"] or expected["errors"] or
                            not expected["molecules"] or identities(expected) != identities(parsed)):
                        raise store.StoreError("ChemDraw conversion changed a structure or reaction role. Use Draw for this sketch.")
                if body.get("draft") or body.get("material"):
                    replaces_reaction = bool(parsed["reaction"])
                prior = parsed
                if replaces_reaction and not body.get("draft") and not body.get("material"):
                    # The researcher may have assigned roles that the stored drawing cannot express.
                    saved = rec["reaction"].get("smiles")
                    if saved and saved != (parsed["reaction"] or {}).get("smiles"):
                        with contextlib.suppress(structure.StructureError):
                            prior = structure.parse(saved, worker=worker)
                previous = [dict(smiles=m["smiles"], inchikey=m["inchikey"], role=m["role"]) for m in prior["molecules"]]
                data = (text if parsed["kind"] == "cdxml" else structure.editable_cdxml(parsed, worker)).encode("utf-8")
            else:
                data = (Path(__file__).parent / "data" / "blank.cdxml").read_bytes()
            token = secrets.token_urlsafe(18)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("working-" + token + ".cdxml")
            with path.open("xb") as f:
                f.write(data)
            self.sessions[token] = dict(case=case.name, rid=rid, rel=case.layout.relative(path), new=new,
                                        previous=previous, replaces_reaction=replaces_reaction, signature=None, edited=False, digest=hashlib.sha256(data).hexdigest())
            try:
                launch(str(path))
            except OSError:
                self._remove(case, token, path)
                raise store.StoreError("ChemDraw could not open .cdxml through the file association. Use ChemDraw paste or drop a file.")
            return dict(session=token)

    @staticmethod
    def _read(path):
        with path.open("rb") as stream:
            data = stream.read(structure.MAX_BYTES+1)
        if len(data) > structure.MAX_BYTES:
            raise store.StoreError("Structure text exceeds 2 MB.")
        return data

    def _remove(self, case, token, path):
        try:
            path.unlink(missing_ok=True)
        except PermissionError as exc:
            raise store.StoreError("Close the working document in ChemDraw and try again.") from exc
        session = self.sessions.pop(token)
        if session["new"]:
            with contextlib.suppress(OSError):
                path.parent.rmdir()
            if case.layout.per_experiment:
                with contextlib.suppress(OSError):
                    case.layout.experiment_dir(session["rid"]).rmdir()

    def update(self, case, action, body, worker=None):
        structure.require()
        with self.lock:
            token = body.get("session")
            session = self.sessions.get(token) if isinstance(token, str) else None
            if not session or session["case"] != case.name or set(body) - {"session", "digest"}:
                raise store.StoreError("Unknown ChemDraw working copy.")
            path = source_path(case, session["rid"], session["rel"])
            if action == "discard":
                self._remove(case, token, path)
                return dict(discarded=True)
            if action not in ("poll", "accept"):
                raise store.StoreError("Unknown working-copy action.")
            stat = path.stat()
            signature = stat.st_size, stat.st_mtime_ns
            reviewed = not session["edited"] or body.get("digest") == session["digest"]
            if action == "poll" and reviewed and signature == session["signature"]:
                return dict(changed=False)
            data = self._read(path)
            digest = hashlib.sha256(data).hexdigest()
            if action == "poll" and reviewed and digest == session["digest"]:
                session["signature"] = signature
                return dict(changed=False)
            if action == "accept" and (not session["edited"] or digest != body.get("digest") or digest != session["digest"]):
                raise store.Conflict("ChemDraw saved again. Review the latest preview.")
            try:
                text = data.decode("utf-8")
            except UnicodeError as exc:
                raise store.StoreError("Save the ChemDraw document as UTF-8 CDXML text.") from exc
            parsed = structure.parse(text, worker=worker)
            if parsed["kind"] != "cdxml":
                raise store.StoreError("The working copy must contain CDXML.")
            if action == "accept":
                self._remove(case, token, path)
                return dict(text=text, edited=True, replaces_reaction=session["replaces_reaction"])
            session.update(digest=digest, signature=signature, edited=True)
            return dict(changed=True, digest=digest, preview=parsed, text=text, previous=session["previous"])
