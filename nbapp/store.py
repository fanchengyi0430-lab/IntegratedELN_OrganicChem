"""Records store for classic and per-experiment notebooks.

Every save is checked against the version the editor loaded, journaled to
<case>/_logs/changes.jsonl and preceded by a snapshot in <case>/_logs/history/.
"""
import collections
import contextlib
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from . import attachments, chem, yamlio
from . import arrangement, waste

TIERS = ("blocking", "needed", "nice")
SCHEMA_VERSION = 1
METRIC_KINDS = ("yield", "conversion", "dr", "ee", "er", "regioselectivity", "other")
_WORD_LOCKED = "The notebook file is open in Word, so it could not be replaced. Close it in Word and rebuild."
REQUIRED = ("id", "title", "type", "status", "question", "key_result", "flags")
KEY_ORDER = ["id", "schema_version", "legacy_id", "eln", "title", "type", "status", "planned", "researcher", "started", "question", "metric_kind", "metric",
             "key_result", "compound_id", "smiles", "reaction", "materials", "conditions", "procedure", "procedure_basis", "refs", "safety", "runs",
             "results_basis", "result", "characterization", "characterization_basis", "interpretation", "next", "vessels", "bench", "result_fields", "notes", "entries",
             "nmr", "attachments", "checks", "flags", "history", "scheme_image", "scheme_alt", "sources"]
_RID = re.compile(r"^EXP-\d{3,}$")
MATERIAL_KEY_ORDER = ("id", "name", "name_basis", "compound_id", "cas", "pubchem_cid", "smiles", "inchikey", "drawing", "check_name", "formula", "mw", "equiv",
                      "mmol", "amount", "assay", "density", "density_basis", "note", "bottle")
PROCESSING_KEY_ORDER = ("source", "lb_hz", "points", "phase_mode", "ph0", "ph1", "delta_ph0", "numpy")
_RESERVED_NAME = re.compile(r"(?i)(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])")
_lock = threading.RLock()
_locked_cases = set()  # accessed only under _lock


class StoreError(Exception):
    status = 400


class Conflict(StoreError):
    status = 409


class NotFound(StoreError):
    status = 404


def valid_name_basis(basis):
    if not isinstance(basis, dict):
        return False
    kind = basis.get("kind")
    text = lambda k: isinstance(basis.get(k), str) and bool(basis[k].strip())
    if kind in ("entered", "chemdraw"):
        return set(basis) == {"kind"}
    if kind == "generated":
        return set(basis) == {"kind", "package", "version"} and text("package") and text("version")
    if kind == "notebook":
        origin = basis.get("generated")
        return (set(basis) <= {"kind", "source", "generated"} and text("source") and
                ("generated" not in basis or isinstance(origin, dict) and origin.get("kind") == "generated" and valid_name_basis(origin)))
    if kind == "pubchem" and set(basis) == {"kind", "cid", "date"} and type(basis["cid"]) is int and basis["cid"] > 0:
        try:
            return datetime.date.fromisoformat(basis["date"]).isoformat() == basis["date"]
        except (ValueError, TypeError):
            pass
    return False


def _version_error(rec):
    version = rec.get("schema_version", 0)
    if type(version) is not int or version > SCHEMA_VERSION:
        return "Record schema version %r is unsupported (app schema version %d)." % (version, SCHEMA_VERSION)
    return None


def _bare_runs(rec):
    runs = rec.get("runs")
    return [str(run["run"]) for run in (runs if isinstance(runs, list) else [])
            if isinstance(run, dict) and "run" in run and not run.get("basis")
            and re.search(r"[0-9]", str(run.get("result", "")))]


def measured_processing(measured):
    """Numeric measurements and older maps without processing used TopSpin's 1r."""
    if isinstance(measured, dict):
        return measured.get("processing", {"source": "topspin"})
    return {"source": "topspin"} if type(measured) in (int, float) else {}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_manual_regions(regions):
    return (isinstance(regions, dict) and regions.get("manual") is True
            and all(isinstance(bounds, list) and len(bounds) == 2
                    and all(_finite(v) for v in bounds) and bounds[0] < bounds[1]
                    for bounds in (regions.get("product"), regions.get("standard"))))


def _measurement_error(measured):
    if measured is None or _finite(measured):
        return None
    if not isinstance(measured, dict) or not _finite(measured.get("value")):
        return "measured needs a numeric percent value."
    if "regions" in measured and not valid_manual_regions(measured["regions"]):
        return "measured.regions needs manual: true and increasing numeric product and standard bounds."
    p = measured_processing(measured)
    if not isinstance(p, dict) or p.get("source") not in ("topspin", "fid"):
        return "measured.processing needs source topspin or fid."
    if p["source"] == "fid":
        if (not all(_finite(p.get(k)) for k in ("lb_hz", "ph0", "ph1"))
                or type(p.get("points")) is not int or p["points"] < 2
                or p.get("phase_mode") not in ("topspin", "manual", "auto0")
                or not isinstance(p.get("numpy"), str) or not p["numpy"].strip()):
            return "FID processing needs lb_hz, points, phase_mode, ph0, ph1 and the numpy version."
        if p.get("delta_ph0") is not None and not _finite(p["delta_ph0"]):
            return "delta_ph0 must be a number or null."
    return None


def _record_conflict(rid):
    return Conflict("%s changed on disk after you opened it (another session or agent saved it). Load the current version and repeat your edit." % rid)


_ROW_KEYS = ("id", "run", "sample", "field")
_COLLECTION_KEYS = {"materials": "id", "runs": "run", "flags": "id", "nmr": "sample"}
MISSING = object()


def record_changes(old, new):
    """Describe changed leaves in stored field order. A keyed row is one addition or removal."""
    changes = []

    def visit(before, after, path, basis=MISSING):
        if before == after:
            return
        # An absent collection has no children. Keep an explicitly added/removed
        # empty collection visible as a value at its own path.
        sample = before if after is MISSING else after
        left = type(sample)() if before is MISSING and isinstance(sample, (list, dict)) else before
        right = type(sample)() if after is MISSING and isinstance(sample, (list, dict)) else after
        if isinstance(left, dict) and isinstance(right, dict) and (left or right):
            for key in dict.fromkeys([*right, *left]):
                child = "%s.%s" % (path, key) if path else str(key)
                is_result = child == "result.text" or (path.startswith("runs[") and key == "result")
                visit(left.get(key, MISSING), right.get(key, MISSING), child,
                      right.get("basis", "") if is_result else MISSING)
            return
        if isinstance(left, list) and isinstance(right, list) and (left or right):
            keys = (_COLLECTION_KEYS[path],) if path in _COLLECTION_KEYS else _ROW_KEYS
            key = next((k for k in keys if all(isinstance(r, dict) and k in r for r in left + right)
                        and all(len({str(r[k]) for r in side}) == len(side) for side in (left, right))), None)
            lhs = {str(r[key]): r for r in left} if key else dict(enumerate(left))
            rhs = {str(r[key]): r for r in right} if key else dict(enumerate(right))
            if key and [k for k in lhs if k in rhs] != [k for k in rhs if k in lhs]:
                changes.append({"path": path + ".order", "old": list(lhs), "new": list(rhs)})
            for label in dict.fromkeys([*rhs, *lhs]):
                child = "%s[%s]" % (path, label)
                a, b = lhs.get(label, MISSING), rhs.get(label, MISSING)
                if key and (a is MISSING or b is MISSING):
                    changes.append({"path": child, "old": a, "new": b, "row_key": key})
                else:
                    visit(a, b, child)
            return
        change = {"path": path, "old": before, "new": after}
        if basis is not MISSING:
            change["basis"] = basis
        changes.append(change)

    visit(old, new, "")
    return changes


def _retype(new, old):
    """Give values that only changed type on the way through the browser (30.0 -> 30, key 2 -> '2', dates -> text) their stored type back."""
    if isinstance(new, dict) and isinstance(old, dict):
        keys = {str(k): k for k in old if not isinstance(k, str)}
        incoming = {keys.get(k, k): v for k, v in new.items()}
        order = [k for k in old if k in incoming] + [k for k in incoming if k not in old]
        return {k: _retype(incoming[k], old.get(k)) for k in order}
    if isinstance(new, list) and isinstance(old, list):
        key = next((k for k in _ROW_KEYS if new and all(isinstance(v, dict) and k in v for v in new)), None)
        if key:
            by = {str(o.get(key)): o for o in old if isinstance(o, dict)}
            return [_retype(v, by.get(str(v[key]))) for v in new]
        return [_retype(v, old[i] if i < len(old) else None) for i, v in enumerate(new)]
    if isinstance(new, int) and not isinstance(new, bool) and isinstance(old, float) and float(new) == old:
        return old
    if isinstance(new, str) and isinstance(old, (datetime.date, datetime.datetime)) and str(old) == new:
        return old
    return new


def _floats(rec):
    """Material numbers are stored as decimals (30.0, not 30), as in the migrated records."""
    for m in rec.get("materials") or []:
        if isinstance(m, dict):
            for k in ("mw", "mmol", "equiv"):
                if isinstance(m.get(k), int) and not isinstance(m.get(k), bool):
                    m[k] = float(m[k])
    return rec


def _fill(value, rid):
    """Replace the planner's placeholders with the assigned experiment number."""
    if isinstance(value, str):
        return value.replace("EXP-NEW", rid).replace("Exp NEW", "Exp %d" % expno(rid))
    if isinstance(value, list):
        return [_fill(v, rid) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, rid) for k, v in value.items()}
    return value


def expno(rid):
    return int(rid.split("-")[1])


def is_screening(rec):
    return "screen" in str(rec.get("type") or "").lower()


def run_result(rec, run):
    """Read the run result, falling back to the bench entry for a planned run."""
    result = run.get("result")
    entries = rec.get("entries")
    rid = str(rec.get("id") or "")
    if (result in (None, "") and rec.get("planned") and isinstance(entries, dict)
            and "run" in run and _RID.fullmatch(rid)):
        label = re.sub(r"[^a-z0-9]+", "_", str(run["run"]).lower())
        result = entries.get("exp%02d_run_%s_yield" % (expno(rid), label))
    return "" if result is None else result


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _now():
    return datetime.datetime.now().astimezone().replace(microsecond=0)


def _read(path, newline=None):
    with open(path, encoding="utf-8", newline=newline) as fh:
        return fh.read()


def _write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


class CaseLayout:
    """Map notebook paths to disk. Record fields and browser links are case-relative."""

    def __init__(self, root, kind):
        if kind not in ("classic", "per-experiment"):
            raise StoreError("Unknown notebook layout: %s." % kind)
        self.project_root = Path(root).absolute().parent.resolve()
        self.root = Path(root).resolve()
        self.per_experiment = kind == "per-experiment"
        self.collection = self.root / ("experiments" if self.per_experiment else "records")
        self.logs = self.root / "_logs"
        self.index = self.root / "index.md"
        self.settings = self.settings_path(self.root)
        self.presets = self.settings.with_name("nmr.yaml")
        self.build_script = self.settings.with_name("build.py")
        self.word_state = self.logs / "word_export.json"

    @staticmethod
    def settings_path(root):
        return Path(root) / "_build" / "case.yaml"

    @classmethod
    def discover(cls, root):
        settings = cls.settings_path(root)
        if settings.is_file():
            try:
                cfg = yamlio.load(_read(settings))
            except (OSError, UnicodeError, yamlio.YAMLError):
                return None
            if cfg is None:
                cfg = {}
            if isinstance(cfg, dict) and cfg.get("layout", "classic") in ("classic", "per-experiment"):
                layout = cls(root, cfg.get("layout", "classic"))
                if layout.collection.is_dir():
                    return layout
        return None

    def relative(self, path):
        return path.relative_to(self.root).as_posix()

    def experiment_dir(self, rid):
        if not isinstance(rid, str) or not _RID.fullmatch(rid):
            raise StoreError("Record IDs look like EXP-010.")
        if not self.per_experiment:
            return self.root
        folder = self.collection / rid
        if folder.resolve() != folder:
            raise StoreError("The experiment folder cannot be a link.")
        return folder

    def asset(self, rid, rel):
        """Resolve a record-owned file, including a path which does not exist yet."""
        if not self.per_experiment:
            return self.root / rel
        folder = self.experiment_dir(rid)
        try:
            parts = attachments.relative_parts(rel)
        except attachments.AttachmentError as exc:
            raise StoreError(str(exc)) from exc
        path = self.root.joinpath(*parts)
        if folder not in path.parents or folder not in path.resolve().parents:
            raise StoreError("Choose a path inside the experiment folder for %s." % rid)
        return path

    def case_file(self, rel):
        path = (self.root / rel).resolve()
        if self.root not in path.parents:
            raise StoreError("Choose a file within the notebook folder.")
        return path

    def browse_path(self, rel):
        if not self.per_experiment:
            path = (self.root / rel).resolve()
            if not path.is_relative_to(self.project_root):
                raise StoreError("Path is outside the project folder.")
            return path
        if rel in ("", "."):
            return self.root
        parts = Path(rel).parts
        if not parts or Path(rel).anchor or ".." in parts:
            raise StoreError("Choose a path inside the notebook folder.")
        if len(parts) >= 2 and self.root / parts[0] == self.collection:
            if len(parts) == 2:
                return self.experiment_dir(parts[1])
            return self.asset(parts[1], Path(rel).as_posix())
        return self.case_file(rel)

    def record_path(self, rid):
        folder = self.experiment_dir(rid)
        if self.per_experiment:
            return self.asset(rid, self.relative(folder / "record.yaml"))
        return self.collection / (rid + ".yaml")

    def record_links(self, rid):
        return {
            "record_path": self.relative(self.record_path(rid)),
            "experiment_folder": self.relative(self.experiment_dir(rid)) if self.per_experiment else None,
            "scheme_example": self.relative(self.scheme_dir(rid) / "scheme.png"),
        }

    def ids(self, occupied=False):
        if self.per_experiment:
            ids = (p.name for p in self.collection.iterdir() if _RID.fullmatch(p.name)
                   and (occupied or self.record_path(p.name).is_file()))
        else:
            ids = (p.stem for p in self.collection.iterdir() if p.suffix == ".yaml" and _RID.fullmatch(p.stem))
        return sorted(ids, key=expno)

    def newest_input(self):
        # Classic notebooks also tracked other files placed directly in records/.
        records = (self.record_path(rid) for rid in self.ids()) if self.per_experiment else self.collection.iterdir()
        return max(self.settings.stat().st_mtime, max((p.stat().st_mtime for p in records), default=0))

    def scheme_dir(self, rid):
        if self.per_experiment:
            return self.experiment_dir(rid) / "scheme"
        return self.root / "ChemDraw notebook v2" / "Previews"

    def attachment_dir(self, rid, kind=None):
        if self.per_experiment:
            folder = (self.scheme_dir(rid) if kind in ("chemdraw", "scheme", "sketch")
                      else self.experiment_dir(rid) / "attachments")
        else:
            folder = self.root / "attachments" / rid
        if folder.resolve() != folder:
            raise StoreError("The attachment folder cannot be a link.")
        return folder

    def attachment_path(self, rid, rel):
        if self.per_experiment:
            return self.asset(rid, rel).resolve()
        return self.case_file(Path(*attachments.relative_parts(rel)))

    def nmr_dir(self, rid):
        path = self.experiment_dir(rid) / "NMR"
        return self.asset(rid, self.relative(path))

    def sample_folder(self, rid, sample):
        root = self.nmr_dir(rid)
        if self.per_experiment:
            attachments.check_name(sample)
            plain = self.asset(rid, self.relative(root / sample))
            if plain.is_dir() or not (root / (rid + "-" + sample)).is_dir():
                return self.relative(plain)
        path = root / (rid + "-" + sample)
        return self.relative(self.asset(rid, self.relative(path)))

    def sample_hints(self):
        base = "experiments/EXP-NEW/NMR/" if self.per_experiment else "EXP-NEW-"
        return {"run": base + "<run>-<label>", "sample": base + "<label>"}

    def acquisition(self, folder, acq):
        try:
            parts = attachments.relative_parts(folder)
        except attachments.AttachmentError:
            parts = []
        if not str(acq).isascii() or not str(acq).isdigit():
            raise StoreError("Invalid acquisition number.")
        if self.per_experiment and len(parts) == 4:
            rid = parts[1]
            if self.root.joinpath(*parts[:-1]) == self.nmr_dir(rid):
                path = self.asset(rid, folder + "/" + str(acq))
                # Instrument readers open these child files directly. A linked pdata
                # directory or FID must obey the same boundary as the acquisition.
                owner = self.experiment_dir(rid)
                for child in ("acqus", "acqu2s", "fid", "pdata/1/1r", "pdata/1/procs",
                              "pdata/1/title", "pdata/1/peaklist.xml"):
                    if not (path / child).resolve().is_relative_to(owner):
                        raise StoreError("Acquisition data must be inside the experiment folder.")
                return path
        if not self.per_experiment and len(parts) == 2 and parts[0] == "NMR":
            return self.browse_path(folder + "/" + str(acq))
        raise StoreError("Not an NMR sample folder.")

    def unlinked_samples(self, rid, linked):
        root = self.nmr_dir(rid)
        if not root.is_dir():
            return
        seen = set(linked)
        prefix = rid + "-"
        for path in sorted(root.iterdir()):
            if path.name.startswith(prefix):
                sample = path.name[len(prefix):]
            elif self.per_experiment:
                sample = path.name
            else:
                continue
            if sample and sample not in seen:
                folder = self.sample_folder(rid, sample)
                if (self.root / folder).is_dir():
                    seen.add(sample)
                    yield sample, folder

    @staticmethod
    def spectrum_cache_key(acquisition):
        data = acquisition / "pdata" / "1" / "1r"
        return acquisition, data.stat().st_mtime if data.is_file() else 0

    def spectrum_pdf(self, rid, folder, sample, acq, nucleus):
        names = [Path(folder).name]
        if self.per_experiment:
            names.extend([sample, rid + "-" + sample])
        for name in dict.fromkeys(names):
            rel = "%s/%s/pdata/1/%s__%s_acq%s_proc1.pdf" % (folder, acq, name, nucleus, acq)
            if self.asset(rid, rel).is_file():
                return rel
        return None

    def mnova(self, rid, folder, named):
        if named and self.asset(rid, named).is_file():
            return named
        sample = self.root / folder
        parent = self.nmr_dir(rid)
        dirs = [sample, parent]
        if not self.per_experiment:
            dirs.append(self.root / "Mnova")
        for directory in dirs:
            if directory.is_dir():
                for path in sorted(directory.iterdir(), key=lambda p: p.name):
                    if path.suffix.lower() == ".mnova" and (directory == sample or path.name.lower().startswith(sample.name.lower())):
                        rel = self.relative(path)
                        if self.asset(rid, rel).is_file():
                            return rel
        return None

    def scheme(self, rec):
        rid = rec["id"]
        named = rec.get("scheme_image")
        if named and self.asset(rid, named).is_file():
            return named
        if self.per_experiment:
            return None
        for suffix in ("-scheme.png", "-scheme-materials.png"):
            path = self.scheme_dir(rid) / (rid + suffix)
            if path.is_file():
                return self.relative(path)
        return None

    @contextlib.contextmanager
    def new_experiment(self, rid):
        """Reserve and populate the folder under the case lock after validation."""
        if not self.per_experiment:
            yield
            return
        folder = self.experiment_dir(rid)
        made = []
        try:
            for path in (folder, self.scheme_dir(rid), self.nmr_dir(rid), self.attachment_dir(rid)):
                path.mkdir()
                made.append(path)
            yield
        except Exception:
            for path in reversed(made):
                with contextlib.suppress(OSError):
                    path.rmdir()
            raise


class Project:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.experiment_indexes = {}

    def case_names(self):
        return sorted(p.name for p in Path(self.root).iterdir() if CaseLayout.discover(p))

    def case(self, name):
        if isinstance(name, str) and Path(name).name == name and name not in ("", ".", ".."):
            layout = CaseLayout.discover(Path(self.root) / name)
            if layout:
                return Case(self, name, layout)
        raise NotFound("No notebook named '%s' with matching case settings and record folder." % name)

    def create_case(self, name, title="", researcher=""):
        if (not isinstance(name, str) or not name or name.startswith(".") or name != name.strip()
                or name.endswith(".") or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                or _RESERVED_NAME.fullmatch(name.split(".", 1)[0].rstrip())):
            raise StoreError("Choose a notebook name that can be used as a folder name.")
        if not isinstance(title, str) or not isinstance(researcher, str):
            raise StoreError("Title and researcher must be text.")
        layout = CaseLayout(Path(self.root) / name, "per-experiment")
        case = Case(self, name, layout)
        build = layout.settings.parent
        try:
            os.mkdir(case.path)
        except FileExistsError:
            raise StoreError("A folder or file named '%s' already exists." % name)
        made = [case.path]
        config_path = str(layout.settings)
        try:
            for directory in (layout.collection, build):
                os.mkdir(directory)
                made.append(directory)
            settings = {"layout": "per-experiment", "title": title or name, "researcher": researcher, "notebook": name + " notebook.docx",
                        "project_question": "", "caveats": [], "references": {}}
            _write_atomic(config_path, yamlio.dump(settings))
        except OSError as e:
            for directory in reversed(made):
                with contextlib.suppress(OSError):
                    os.rmdir(directory)
            raise StoreError("Could not start the notebook: %s" % e)
        return case


class Case:
    def __init__(self, project, name, layout):
        self.project = project
        self.name = name
        self.path = os.path.join(project.root, name)
        self.layout = layout

    # ------------------------------------------------------------ paths
    def safe_path(self, rel):
        """Absolute path for a case-relative path; refuses anything that leaves the project folder."""
        return str(self.layout.browse_path(rel))

    def cfg(self):
        return yamlio.load(_read(self.layout.settings)) or {}

    def notebook_path(self):
        return os.path.join(self.path, self.cfg().get("notebook", "notebook.docx"))

    # ------------------------------------------------------------ reading
    def ids(self):
        return self.layout.ids()

    def read(self, rid):
        path = self.layout.record_path(rid)
        if not os.path.isfile(path):
            raise NotFound("%s has no record file." % rid)
        text = _read(path)
        rec = self.parse_record(rid, path, text)
        return rec, {"hash": _sha(text), "mtime": os.path.getmtime(path)}

    def parse_record(self, rid, path, text):
        try:
            rec = yamlio.load(text)
        except Exception as e:  # a hand-edited file that no longer parses
            raise StoreError("%s is not valid YAML: %s" % (path.name, str(e).splitlines()[0]))
        if not isinstance(rec, dict):
            raise StoreError("%s does not contain a record." % path.name)
        if self.layout.per_experiment and rec.get("id") != rid:
            raise StoreError("The record ID must match its experiment folder (%s)." % rid)
        return rec

    def all(self):
        out = []
        for rid in self.ids():
            try:
                out.append(self.read(rid)[0])
            except StoreError as e:
                out.append({"id": rid, "title": "(unreadable record)", "type": "?", "status": "error", "legacy_id": "",
                            "question": str(e), "key_result": "", "flags": [], "_error": str(e)})
        return out

    # ------------------------------------------------------------ derived views
    def acquisitions(self, rec):
        """NMR samples and spectrum links for this record."""
        out = []
        for s in rec.get("nmr") or []:
            rid = rec["id"]
            folder = self.layout.sample_folder(rid, s["sample"])
            spectra = []
            for nuc, mhz, acq in re.findall(r"(\w+) (\d+) \(acq (\d+)\)", s.get("spectra", "")):
                pdf = self.layout.spectrum_pdf(rid, folder, s["sample"], acq, nuc)
                spectra.append({"nucleus": nuc, "mhz": int(mhz), "acq": acq, "pdf": pdf})
            out.append({"sample": s["sample"], "folder": folder, "date": s.get("date", ""), "spectra": spectra,
                        "exists": (self.layout.root / folder).is_dir(),
                        "mnova": self.layout.mnova(rid, folder, s.get("mnova")), "mnova_status": s.get("mnova_status", "")})
        return out

    def unlinked_nmr(self, rec):
        """Read instrument metadata only for samples absent from the record."""
        from . import nmr
        have = {s.get("sample") for s in rec.get("nmr") or [] if isinstance(s, dict)}
        out = []
        for sample, folder in self.layout.unlinked_samples(rec["id"], have):
            spectra, date = [], ""
            for acq in sorted((p.name for p in (self.layout.root / folder).iterdir() if p.name.isdigit()), key=int):
                info = nmr.acquisition_info(self.layout.acquisition(folder, acq))
                if info:
                    spectra.append("%s %d (acq %s)" % (info["nucleus"], info["mhz"], acq))
                    date = date or info["date"]
            if spectra:
                out.append({"sample": sample, "spectra": ", ".join(spectra), "date": date})
        return out

    def run_sample(self, rec, run):
        prefix = "%s-" % run
        for a in self.acquisitions(rec):
            if a["sample"].startswith(prefix):
                return a
        return None

    def researcher(self, rows=None):
        """The name most records carry, as the default for a new experiment."""
        records = self.all() if rows is None else rows
        names = collections.Counter(r.get("researcher") for r in records if r.get("researcher"))
        return names.most_common(1)[0][0] if names else self.cfg().get("researcher", "")

    def scheme(self, rec):
        return self.layout.scheme(rec)

    def summary(self):
        from .experiment_index import Index
        return self.project.experiment_indexes.setdefault(self.name, Index()).rows(self)

    def search(self, query):
        words = [w for w in query.lower().split() if w]
        hits = []
        if not words:
            return hits
        for rec in self.all():
            text = yamlio.dump(rec)
            low = text.lower()
            if all(w in low for w in words):
                i = low.find(words[0])
                start = max(0, low.rfind("\n", 0, i) + 1)
                end = low.find("\n", i)
                line = text[start:end if end > 0 else len(text)].strip()
                if len(line) > 220:
                    j = max(0, i - start - 80)
                    line = ("…" if j else "") + line[j:j + 220] + "…"
                hits.append({"id": rec["id"], "title": rec.get("title", ""), "snippet": line})
        return hits

    # ------------------------------------------------------------ validation
    def validate(self, rec, rid=None, deep=False, pending=()):
        """Problems with a record: 'error' blocks saving, 'warn' and 'note' are shown to the researcher."""
        from . import outputs

        out = []

        def add(level, msg):
            out.append({"level": level, "msg": msg})

        if not isinstance(rec, dict) or any(not isinstance(k, str) for k in rec):
            add("error", "A record must be a map with text field names.")
            return out
        for k in REQUIRED:
            if rec.get(k) in (None, ""):
                add("error", "Missing '%s'." % k)
            elif k != "flags" and not isinstance(rec[k], str):
                add("error", "'%s' must be text." % k)
        if rec.get("researcher") is not None and not isinstance(rec["researcher"], str):
            add("error", "'researcher' must be text.")
        def check_compound_id(row):
            if "compound_id" in row:
                value = row["compound_id"]
                if type(value) is not int and not (isinstance(value, str) and value.strip()):
                    add("error", "compound_id must be a compound number or a non-empty label.")

        check_compound_id(rec)
        version_error = _version_error(rec)
        if version_error:
            add("error", version_error)
        metric_kind = rec.get("metric_kind")
        if is_screening(rec):
            level = "error" if rec.get("schema_version") == SCHEMA_VERSION else "warn"
            if metric_kind not in METRIC_KINDS:
                add(level, "Choose a primary metric (metric_kind) for this screening: %s." % ", ".join(METRIC_KINDS))
            metric = rec.get("metric")
            if not isinstance(metric, str) or not metric.strip():
                add(level, "Describe how the primary metric will be measured (metric).")
        elif metric_kind is not None and metric_kind not in METRIC_KINDS:
            add("error", "'metric_kind' must be one of: %s." % ", ".join(METRIC_KINDS))
        if rid and rec.get("id") != rid:
            add("error", "The record's id (%s) does not match its file (%s)." % (rec.get("id"), rid))
        flags = rec.get("flags")
        if flags is not None and not isinstance(flags, list):
            add("error", "'flags' must be a list.")
            flags = []
        seen = set()
        for f in flags or []:
            if not isinstance(f, dict) or not isinstance(f.get("id"), (str, int)) or not f["id"] or not f.get("text"):
                add("error", "Each flag needs an id and text.")
                continue
            if f.get("tier") not in TIERS:
                add("error", "Flag %s: tier must be blocking, needed or nice." % f.get("id"))
            if f["id"] in seen:
                add("error", "Flag id %s is used twice." % f["id"])
            seen.add(f["id"])
        if flags and len(flags) > 3:
            add("warn", "%d open flags; the house rule is three or fewer per entry." % len(flags))
        runs = rec.get("runs")
        if runs is not None and not isinstance(runs, list):
            add("error", "'runs' must be a list.")
            runs = []
        for run in runs or []:
            if not isinstance(run, dict) or "run" not in run or "result" not in run:
                add("error", "Each run needs 'run' and 'result'.")
                continue
            if re.search(r"\d", str(run.get("result", ""))) and not run.get("basis"):
                add("warn", "Run %s: result '%s' has no basis." % (run["run"], run["result"]))
            label = "Run %s" % run["run"]
            measured = run.get("measured")
            error = _measurement_error(measured)
            if error:
                add("error", "%s: %s" % (label, error))
            if isinstance(measured, dict):
                measured = measured.get("value")
            if type(measured) in (int, float):
                measured = "%s%%" % measured
            yield_values = [(label + " measured", measured)]
            if metric_kind == "yield" or metric_kind not in METRIC_KINDS:
                yield_values.insert(0, (label, run["result"]))
            for where, value in yield_values:
                warning = outputs.high_yield_warning(value, where)
                if warning:
                    add("warn", warning)
        if rec.get("runs") and not rec.get("results_basis"):
            add("warn", "The run table has no overall basis (results_basis).")
        res = rec.get("result")
        if res is not None and (not isinstance(res, dict) or not res.get("text") or not res.get("basis")):
            add("error", "'result' needs both text and basis.")
        if isinstance(res, dict):
            warning = outputs.high_yield_warning(res.get("text"), "Isolated result", isolated=True)
            if warning:
                add("warn", warning)
        from . import structure, structure_search
        reaction = rec.get("reaction")
        sides = None
        if reaction is not None:
            if not isinstance(reaction, dict) or not all(isinstance(reaction.get(k), str) and reaction[k].strip()
                                                         for k in ("smiles", "drawing", "source")):
                add("error", "A reaction needs SMILES, a source and a drawing path.")
            else:
                try:
                    source = self.layout.attachment_path(rid or rec.get("id"), reaction["drawing"])
                    if source.parent != self.layout.attachment_dir(rid or rec.get("id"), "chemdraw"):
                        raise StoreError("Reaction drawing must be in this experiment's scheme folder.")
                except (StoreError, attachments.AttachmentError) as exc:
                    add("error", str(exc))
                if not structure.REASON:
                    sides = structure.reaction_sides(reaction["smiles"])
                    if sides is None:
                        add("warn", "Reaction SMILES could not be parsed.")
        materials = rec.get("materials")
        if materials is not None and not isinstance(materials, list):
            add("error", "'materials' must be a list.")
            materials = []
        for m in materials or []:
            if not isinstance(m, dict) or not m.get("id") or not (m.get("name") or (m.get("smiles") and m.get("formula"))):
                add("error", "Each material needs an id and a name.")
                continue
            check_compound_id(m)
            if "name_basis" in m and not valid_name_basis(m["name_basis"]):
                add("error", "%s: invalid name_basis or missing source details." % m["id"])
            if "check_name" in m and type(m["check_name"]) is not bool:
                add("error", "%s: check_name must be true or false." % m["id"])
            if "drawing" in m:
                try:
                    path = self.layout.attachment_path(rid or rec.get("id"), m["drawing"])
                    if path.parent != self.layout.attachment_dir(rid or rec.get("id"), "sketch") or not any(
                            isinstance(a, dict) and a.get("path") == m["drawing"] and a.get("kind") in ("sketch", "chemdraw")
                            for a in rec.get("attachments") or []):
                        raise StoreError("Material drawing must reference an attached source in the experiment's scheme folder.")
                except (StoreError, attachments.AttachmentError) as exc:
                    add("error", str(exc))
            for k in ("mmol", "equiv", "mw"):
                if k in m and not isinstance(m[k], (int, float)):
                    add("error", "%s: %s must be a number." % (m["id"], k))
            for k in ("density_basis", "cas", "smiles", "inchikey"):
                if k in m and (not isinstance(m[k], str) or not m[k].strip()):
                    add("error", "%s: %s must be non-empty text." % (m["id"], k))
            smiles = structure.material_smiles(rec, m)
            mismatch = m.get("scheme_mismatch") is True
            absent = False
            role = structure_search.material_role(m)
            if isinstance(smiles, str) and not structure.REASON:
                mol = structure.molecule(smiles)
                if mol and sides and role in ("reactant", "product"):
                    key = structure.Chem.MolToInchiKey(mol)
                    absent = all(other != key for _, other in sides[role])
                if mol is None:
                    add("warn", "%s: SMILES could not be parsed." % m["id"])
                elif m.get("formula"):
                    actual = structure.formula(mol)
                    if not chem.same_formula(actual, m["formula"]):
                        add("warn", "%s: recorded formula %s differs from structure formula %s." % (m["id"], m["formula"], actual))
            if "scheme_mismatch" in m and type(m["scheme_mismatch"]) is not bool:
                add("error", "%s: scheme_mismatch must be true or false." % m["id"])
            if mismatch or absent:
                label = str(m["id"]) + (" (" + str(m["name"]) + ")" if m.get("name") else "")
                message = "The scheme no longer matches material %s." % label
                if absent:
                    message += " Its structure is absent on the %s side of the record's reaction." % role
                out.append(dict(level="warn", msg=message, kind="scheme_mismatch"))
            if "density_basis" in m and (type(m.get("density")) not in (float, int) or not m["density"] > 0):
                add("error", "%s: density_basis needs a positive numeric density in g/mL." % m["id"])
            if "pubchem_cid" in m and (type(m["pubchem_cid"]) is not int or m["pubchem_cid"] <= 0):
                add("error", "%s: pubchem_cid must be a positive integer." % m["id"])
            for note in chem.check_material(m):
                add("note", note)
            warning = chem.assay_warning(m)
            if warning:
                add("warn", warning)
        for warning in chem.vessel_warnings(materials, chem.plan_text(rec)):
            add("warn", warning)
        samples = rec.get("nmr")
        if samples is not None and (not isinstance(samples, list) or any(
                not isinstance(s, dict) or not isinstance(s.get("sample"), str) or not s["sample"]
                or not isinstance(s.get("spectra", ""), str)
                or (s.get("mnova") is not None and not isinstance(s["mnova"], str))
                for s in samples)):
            add("error", "'nmr' must be a list of samples with text labels and paths.")
        sources = rec.get("sources")
        if sources is not None and not isinstance(sources, dict):
            add("error", "'sources' must be a map.")
        for name, value in (("scheme_image", rec.get("scheme_image")), ("sources.eln", sources.get("eln") if isinstance(sources, dict) else None)):
            if value is not None and not isinstance(value, str):
                add("error", "'%s' must be a path." % name)
        items = rec.get("attachments", [])
        if not isinstance(items, list):
            add("error", "'attachments' must be a list.")
            items = []
        for item in items:
            if not isinstance(item, dict):
                add("error", "Each attachment must be a map.")
                continue
            try:
                if self.layout.per_experiment:
                    self.layout.attachment_path(rid or rec.get("id"), item.get("path"))
                else:
                    attachments.relative_parts(item.get("path"))
            except (StoreError, attachments.AttachmentError) as e:
                add("error", str(e))
            digest = item.get("sha256")
            if (item.get("kind") not in attachments.KINDS
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or type(item.get("size")) is not int or item["size"] < 0
                    or not isinstance(item.get("added"), (str, datetime.date)) or not item["added"]
                    or not isinstance(item.get("by"), str)):
                add("error", "Each attachment needs a kind, SHA-256, size, added date and author.")
        if any(n["level"] == "error" for n in out):
            return out
        if rec.get("id") and _RID.match(str(rec["id"])):
            try:
                if self.layout.per_experiment:
                    for path in (rec.get("scheme_image"), (sources or {}).get("chemdraw"), (sources or {}).get("eln")):
                        if path:
                            self.layout.asset(rec["id"], path)
                acquisitions = self.acquisitions(rec)
            except (StoreError, attachments.AttachmentError) as exc:
                add("error", str(exc))
                return out
            for a in acquisitions:
                if not a["exists"]:
                    add("warn", "NMR folder not found: %s" % a["folder"])
            if rec.get("scheme_image") and rec["scheme_image"] not in pending and not os.path.isfile(os.path.join(self.path, rec["scheme_image"])):
                add("warn", "Scheme image not found: %s" % rec["scheme_image"])
            eln = (rec.get("sources") or {}).get("eln")
            if eln and not os.path.isfile(os.path.join(self.path, eln)):
                add("warn", "ELN export not found: %s" % eln)
        out.extend(self.check_attachments(dict(rec, attachments=[a for a in items if a.get("path") not in pending]), deep=deep))
        return out

    def attachment_states(self, rec, deep=False):
        """Return the saved attachment metadata with current file states."""
        items = rec.get("attachments")
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            rel = item.get("path")
            state, message, directory = "ok", None, False
            try:
                full = self.layout.attachment_path(rec["id"], rel)
                directory = full.is_dir()
                directory, size, digest = attachments.fingerprint(full, deep=deep)
                if size != item.get("size") or (digest is not None and digest != item.get("sha256")):
                    state, message = "changed", "Attachment %s: changed since it was attached." % rel
            except (FileNotFoundError, NotADirectoryError):
                state, message = "missing", "Attachment missing: %s." % rel
            except (StoreError, attachments.AttachmentError):
                state, message = ("changed", "Attachment %s: could not be checked." % rel) if directory else (
                    "missing", "Attachment missing: %s." % rel)
            except OSError:
                state, message = "changed", "Attachment %s: could not be checked." % rel
            out.append(dict(item, state=state, directory=directory, message=message))
        return out

    def check_attachments(self, rec, deep=False):
        return [{"level": "warn", "msg": item["message"]}
                for item in self.attachment_states(rec, deep=deep) if item["message"]]

    # ------------------------------------------------------------ writing
    def _journal(self, entry):
        logs = self.layout.logs
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "changes.jsonl"), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @contextlib.contextmanager
    def _record_lock(self):
        """Serialize record changes across both app threads and CLI processes."""
        with _lock:
            key = os.path.normcase(os.path.realpath(self.path))
            if key in _locked_cases:
                yield
                return
            logs = self.layout.logs
            os.makedirs(logs, exist_ok=True)
            with open(os.path.join(logs, "records.lock"), "a+b") as lockfile:
                lockfile.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lockfile.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
                _locked_cases.add(key)
                try:
                    yield
                finally:
                    _locked_cases.remove(key)

    def write(self, rid, rec, expect_hash=None, by="", summary="", action="edit", via="app", dry_run=False, structures=None, worker=None, include_changes=False):
        """Validate and save a full record, or report the result without writing."""
        from .outputs import parse_result

        path = self.layout.record_path(rid)
        with (_lock if dry_run else self._record_lock()):
            exists = os.path.isfile(path)
            old_text = _read(path) if exists else ""
            if not exists and action != "create":
                raise NotFound("%s has no record file." % rid)
            old_hash = _sha(old_text) if exists else None
            if (expect_hash is not None and old_hash != expect_hash) or (exists and action == "create"):
                raise _record_conflict(rid)
            old = yamlio.load(old_text) if exists else {}
            from . import structure_files
            rec = dict(rec) if structures and isinstance(rec, dict) else rec
            # Raw record edits (including CLI and YAML) can change a name while retaining its old attribution.
            if isinstance(old, dict) and isinstance(rec, dict) and isinstance(rec.get("materials"), list):
                previous = {m["id"]: m for m in old.get("materials") or [] if isinstance(m, dict) and "id" in m}
                # A reviewed drawing can legitimately supply a new label with the same basis,
                # e.g. a second ChemDraw name, or an empty name still marked for review.
                reviewed = {}
                for draft in structures if isinstance(structures, list) else ():
                    if isinstance(draft, dict) and isinstance(draft.get("names"), dict) and isinstance(draft.get("material_positions"), dict):
                        for mid, pos in draft["material_positions"].items():
                            if str(pos) in draft["names"]:
                                reviewed[mid] = draft["names"][str(pos)]
                for m in rec["materials"]:
                    prior = previous.get(str(m.get("id"))) if isinstance(m, dict) else None
                    if (prior and m.get("name") != prior.get("name") and reviewed.get(m["id"]) != m.get("name") and
                            ("name_basis" not in m or m["name_basis"] == prior.get("name_basis"))):
                        m["name_basis"] = {"kind": "entered"}
                        m.pop("check_name", None)
            library = []
            files = structure_files.prepare(self, rid, rec, structures, by, old, library, worker) if structures else {}
            if files and not exists:
                rec = {**{k: rec[k] for k in KEY_ORDER if k in rec}, **rec}
            notes = self.validate(rec, rid, pending={self.layout.relative(p) for p in files})
            errors = [v["msg"] for v in notes if v["level"] == "error"]
            if errors:
                raise StoreError("Not saved. " + " ".join(errors))
            had = set(_bare_runs(old)) if isinstance(old, dict) else set()
            bare = [label for label in _bare_runs(rec) if label not in had]
            if bare:
                raise StoreError("Run %s: state the basis of the result (measured, recalculated, slides, literature or target)." % ", ".join(bare))
            if isinstance(old, dict) and _version_error(old):
                raise StoreError("Not saved. " + _version_error(old))
            if not isinstance(old, dict):
                old = {}
            rec = _floats(_retype(rec, old) if exists else rec)
            if exists and old == rec:
                return {"changed": False, "hash": old_hash, "fields": [], "notes": notes}
            fields = sorted(k for k in set(old) | set(rec) if old.get(k) != rec.get(k))
            old_runs = old.get("runs")
            if "metric_kind" in fields and isinstance(old_runs, list) and any(
                    isinstance(run, dict) and (
                        run.get("measured") is not None or parse_result(str(run_result(old, run)))["kind"] not in ("none", "nr"))
                    for run in old_runs):
                warning = "primary metric changed from %s to %s after results were recorded" % (
                    old.get("metric_kind") or "unset", rec.get("metric_kind") or "unset")
                notes.append({"level": "warn", "msg": warning})
                summary = "%s. %s" % (summary, warning) if summary else warning
            result = {"changed": True, "hash": old_hash, "fields": fields, "notes": notes}
            if include_changes:
                result["changes"] = record_changes(old, rec)
            if dry_run:
                return result
            for run in rec.get("runs") or []:
                measured = run.get("measured")
                if isinstance(measured, dict):
                    if "processing" in measured:
                        p = measured["processing"]
                        measured["processing"] = {**{k: p[k] for k in PROCESSING_KEY_ORDER if k in p}, **p}
                    if "regions" in measured:
                        regions = measured["regions"]
                        measured["regions"] = {**{k: regions[k] for k in ("product", "standard", "manual")}, **regions}
                    run["measured"] = {**{k: measured[k] for k in ("value", "processing", "regions") if k in measured}, **measured}
            now = _now()
            header = yamlio.split_header(old_text) if exists else (
                "# %s record — source of truth for this experiment (added %s in the notebook app).\n"
                "# Paths are relative to the case folder. Every result states its basis; 'slides' = subgroup deck, not re-integrated.\n"
                % (rid, now.strftime("%d %b %Y").lstrip("0")))
            new_text = header + yamlio.dump(rec)
            if exists:
                hist = self.layout.logs / "history" / rid
                os.makedirs(hist, exist_ok=True)
                stem = os.path.join(hist, now.strftime("%Y-%m-%dT%H-%M-%S"))
                snapshot = stem + ".yaml"
                suffix = 2
                while os.path.exists(snapshot):
                    snapshot = "%s-%d.yaml" % (stem, suffix)
                    suffix += 1
                _write_atomic(snapshot, old_text)
            with self.layout.new_experiment(rid) if not exists else contextlib.nullcontext():
                with structure_files.install(files), structure_files.install_compounds(self, library):
                    _write_atomic(path, new_text)
            self._journal({"ts": now.isoformat(), "by": by, "via": via, "exp": rid, "action": action, "fields": fields,
                           "summary": summary, "before": old_hash, "after": _sha(new_text)})
            result["hash"] = _sha(new_text)
            return result

    def next_id(self):
        ids = self.layout.ids(occupied=True)
        return "EXP-%03d" % ((expno(ids[-1]) if ids else 0) + 1)

    def create(self, rec, by="", via="app", structures=None, worker=None):
        if not isinstance(rec, dict):
            raise StoreError("Not saved. A record must be a map with text field names.")
        version_error = _version_error(rec)
        if version_error:
            raise StoreError("Not saved. " + version_error)
        with self._record_lock():
            rid = self.next_id()
            return self._create(rid, rec, by, via, structures, worker)

    def _create(self, rid, rec, by, via, structures=None, worker=None):
        rec = _fill(dict(rec), rid)
        rec["id"] = rid
        rec["schema_version"] = SCHEMA_VERSION
        n = expno(rid)
        flags = rec.get("flags")
        for f in flags if isinstance(flags, list) else []:  # flag ids follow the experiment number
            if isinstance(f, dict) and str(f.get("id", "")).startswith("new."):
                f["id"] = "%d.%s" % (n, f["id"][4:])
        sources = rec.get("sources")
        refs = sources.get("refs") if isinstance(sources, dict) else None
        if isinstance(refs, dict):  # reference numbers arrive from the browser as text
            rec["sources"]["refs"] = {int(k) if str(k).isdigit() else k: v for k, v in refs.items()}
        ordered = {k: rec[k] for k in KEY_ORDER if k in rec}
        ordered.update({k: v for k, v in rec.items() if k not in ordered})
        if isinstance(ordered.get("materials"), list):
            ordered["materials"] = [
                {**{k: row[k] for k in MATERIAL_KEY_ORDER if k in row}, **row} if isinstance(row, dict) else row
                for row in ordered["materials"]]
        res = self.write(rid, ordered, by=by, summary="new experiment", action="create", via=via, structures=structures, worker=worker)
        res["id"] = rid
        return res

    # ------------------------------------------------------------ attachments
    def attach(self, rid, source, kind, sample=None, run=None, by="", note="", expect_hash=None, *, via="app", upload_name=None):
        if kind not in attachments.KINDS:
            raise StoreError("Choose an attachment kind.")
        with self._record_lock():
            rec, meta = self.read(rid)
            if expect_hash is not None and expect_hash != meta["hash"]:
                raise _record_conflict(rid)
            if rec.get("id") != rid:
                raise StoreError("The record's id (%s) does not match its file (%s)." % (rec.get("id"), rid))
            items = rec.get("attachments", [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise StoreError("The record's attachments must be a list of maps.")
            return self._attach(rec, meta["hash"], Path(source), kind, sample, run, by, note, via, upload_name)

    def _attach(self, rec, expected, source, kind, sample, run, by, note, via, upload_name):
        root = self.layout.root
        installed = None
        rid = rec["id"]
        try:
            if not source.exists():
                raise NotFound("Attachment source not found: %s." % source)
            name = attachments.check_name(upload_name if upload_name is not None else source.name)
            full = source.resolve()
            if full.is_dir() and (full == root or full in root.parents):
                raise StoreError("Choose a folder that does not contain this notebook.")
            owner = self.layout.experiment_dir(rid)
            local = owner in full.parents
            if full == owner or full in owner.parents:
                raise StoreError("Choose a file or folder inside the experiment or outside its parent folders.")
            if owner in source.absolute().parents and not local:
                raise StoreError("Choose a path inside the experiment folder.")
            fingerprint = attachments.fingerprint(source, deep=True)
            if upload_name is not None or not local:
                if upload_name is not None and (fingerprint[0] or full.parent.parent != root or full.name != name):
                    raise StoreError("Upload a file from this notebook's staging folder.")
                folder = self.layout.attachment_dir(rid, kind)
                target, reused = attachments.destination(folder, name, fingerprint)
                if not reused:
                    folder.mkdir(parents=True, exist_ok=True)
                    if upload_name is not None:
                        os.rename(full, target)
                    else:
                        with tempfile.TemporaryDirectory(prefix=".attach-", dir=folder) as temp:
                            staged = Path(temp) / name
                            attachments.copy(source, staged, fingerprint)
                            os.rename(staged, target)
                    installed = target
                full = target
            rel = full.relative_to(root).as_posix()
            items = rec.get("attachments", [])
            existing = next((item for item in items if os.path.normcase(str(item.get("path"))) == os.path.normcase(rel)), None)
            if existing is not None and (existing.get("size"), existing.get("sha256")) == fingerprint[1:]:
                entry = existing
            else:
                entry = {"path": rel, "kind": kind}
                for label, value in (("sample", sample), ("run", run)):
                    if value is not None and value != "":
                        entry[label] = value
                entry.update(sha256=fingerprint[2], size=fingerprint[1], added=_now().isoformat(), by=by)
                if note:
                    entry["note"] = note
                rec["attachments"] = [entry if item is existing else item for item in items] if existing else items + [entry]
            result = self.write(rid, rec, expect_hash=expected, by=by, summary=rel, action="attach", via=via)
            return dict(result, attachment=entry)
        except StoreError:
            if installed is not None:
                with contextlib.suppress(OSError):
                    if installed.is_dir():
                        shutil.rmtree(installed)
                    else:
                        installed.unlink()
            raise
        except (attachments.AttachmentError, OSError, RuntimeError) as e:
            raise StoreError(str(e)) from e

    def arrangement(self, ids=None):
        """Read the case view. Reading an untouched notebook creates no file."""
        path = self.layout.case_file("arrangement.yaml")
        with _lock:
            exists = path.exists()
            text = _read(path, newline="") if exists else ""
            try:
                data, issues = arrangement.clean(yamlio.load(text) if exists else {}, set(self.ids() if ids is None else ids))
            except yamlio.YAMLError as exc:
                data, issues = arrangement.clean({}, set())[0], ["Invalid arrangement.yaml: " + str(exc).splitlines()[0]]
            history = self.layout.logs / "history" / "arrangement"
            newest = max(history.glob("*.yaml"), default=None)
            undo = None
            if newest:
                undo = next((c.get("summary") for c in self.changes(None)
                             if c.get("snapshot") == newest.name and c.get("action") == "arrange"), "changed arrangement")
            return dict(data=data, hash=_sha(text), undo=undo, warnings=issues)

    def save_arrangement(self, data, expect_hash, summary="", by="", undo=False):
        path = self.layout.case_file("arrangement.yaml")
        history = self.layout.logs / "history" / "arrangement"
        with self._record_lock():
            ids = set(self.ids())
            state = self.arrangement(ids)
            if state["hash"] != expect_hash:
                raise Conflict("The arrangement changed on disk. Review the current version and repeat your change.")
            old = _read(path, newline="") if path.exists() else ""
            if undo:
                snapshot = max(history.glob("*.yaml"), default=None)
                if snapshot is None:
                    return dict(state, message="Nothing to undo.")
                original = new = _read(snapshot, newline="")
                if new:
                    try:
                        restored, issues = arrangement.clean(yamlio.load(new), ids)
                        if issues:
                            new = yamlio.dump(restored)
                    except yamlio.YAMLError:
                        pass  # Preserve the original text for a researcher undoing a repair.
                summary = "undid: " + state["undo"]
            else:
                data, issues = arrangement.clean(data, ids)
                if issues:
                    raise StoreError(" ".join(issues))
                if data == state["data"] and not state["warnings"]:
                    return dict(state, message="Arrangement unchanged.")
                if not isinstance(summary, str) or not summary.strip():
                    raise StoreError("Describe the arrangement change.")
                summary = " ".join(summary.split())
                new = yamlio.dump(data)
                history.mkdir(parents=True, exist_ok=True)
                # Monotonic names keep stack order even if the system clock moves back.
                newest = max(history.glob("*.yaml"), default=None)
                stamp = datetime.datetime.now(datetime.timezone.utc)
                if newest:
                    prior = datetime.datetime.strptime(newest.stem, "%Y%m%dT%H%M%S%f").replace(tzinfo=datetime.timezone.utc)
                    stamp = max(stamp, prior + datetime.timedelta(microseconds=1))
                snapshot = history / (stamp.strftime("%Y%m%dT%H%M%S%f") + ".yaml")
                _write_atomic(snapshot, old)
            def restore(text):
                if text:
                    _write_atomic(path, text)
                else:
                    path.unlink(missing_ok=True)
            try:
                restore(new)
                if undo:
                    snapshot.unlink()
                self._journal(dict(ts=_now().isoformat(), by=by, via="app", action="arrange", summary=summary,
                                   snapshot=None if undo else snapshot.name, before=_sha(old), after=_sha(new)))
            except Exception:
                restore(old)
                if undo and not snapshot.exists():
                    _write_atomic(snapshot, original)
                elif not undo:
                    snapshot.unlink(missing_ok=True)
                raise
            return dict(self.arrangement(ids), message=summary)

    # ------------------------------------------------------------ schedule, supplies and waste (<case>/followups.yaml)
    def _read_followups(self):
        path = os.path.join(self.path, "followups.yaml")
        text = _read(path) if os.path.isfile(path) else ""
        try:
            loaded = yamlio.load(text)
        except yamlio.YAMLError as e:
            raise StoreError("Could not read followups.yaml: %s" % str(e).splitlines()[0]) from e
        if loaded is not None and not isinstance(loaded, dict):
            raise StoreError("followups.yaml must contain named lists.")
        return text, loaded or {}

    def followups(self):
        """Tasks, supplies and waste bottles with their calculated reminders."""
        text, loaded = self._read_followups()
        tasks = [t for t in loaded.get("tasks") or [] if isinstance(t, dict)]
        supplies = [dict(s) for s in loaded.get("supplies") or [] if isinstance(s, dict)]
        bottles = [b for b in loaded.get("waste") or [] if isinstance(b, dict)]

        def span(t):
            try:
                start = datetime.datetime.fromisoformat(str(t["start"]))
                return start, start + datetime.timedelta(minutes=float(t.get("minutes") or 0))
            except (KeyError, ValueError, TypeError):
                return None
        timed = [(t, span(t)) for t in tasks if t.get("state", "open") == "open" and span(t)]
        conflicts = []
        for i, (a, sa) in enumerate(timed):
            for b, sb in timed[i + 1:]:
                if sa[0] < sb[1] and sb[0] < sa[1]:
                    same = a.get("equipment") and str(a.get("equipment")).strip().lower() == str(b.get("equipment") or "").strip().lower()
                    if same or (a.get("hands_on") and b.get("hands_on")):
                        conflicts.append({"a": a.get("id"), "b": b.get("id"), "why": "both use %s" % a["equipment"] if same else "both need you at the bench"})
        ends = {t.get("id"): s[1] for t, s in timed}
        late = [t.get("id") for t, s in timed if t.get("after") in ends and ends[t["after"]] > s[0]]
        for s in supplies:
            low = isinstance(s.get("count"), (int, float)) and isinstance(s.get("threshold"), (int, float)) and s["count"] <= s["threshold"]
            s["stored"] = s.get("state", "ok")   # what the file says; "state" adds the low-count rule
            s["state"] = "needed" if low and s["stored"] == "ok" else s["stored"]
        streams, fraction = waste.settings(self.cfg())
        return {"tasks": tasks, "supplies": supplies, "conflicts": conflicts, "late": late,
                "waste": bottles, "waste_status": waste.status(bottles, fraction), "waste_streams": streams,
                "waste_reminder_fraction": float(fraction), "hash": _sha(text)}

    def save_followups(self, tasks=None, supplies=None, expect_hash=None, by=""):
        updates = {name: rows for name, rows in (("tasks", tasks), ("supplies", supplies)) if rows is not None}
        return self._save_followup_lists(updates, expect_hash)

    def save_waste(self, bottles, expect_hash=None):
        return self._save_followup_lists({"waste": bottles}, expect_hash)

    def waste_csv(self, bottle_id):
        _, loaded = self._read_followups()
        for bottle in loaded.get("waste") or []:
            if isinstance(bottle, dict) and str(bottle.get("id")) == str(bottle_id):
                return waste.csv_log(bottle)
        raise NotFound("No waste bottle with that ID.")

    def _save_followup_lists(self, updates, expect_hash):
        path = os.path.join(self.path, "followups.yaml")
        with self._record_lock():
            text, loaded = self._read_followups()
            if expect_hash is not None and _sha(text) != expect_hash:
                raise Conflict("The schedule, supplies or waste log changed on disk. Reload the page and repeat the change.")
            if updates:
                header = yamlio.split_header(text) if text else "# Schedule, supplies and waste for this case.\n"
                for name, rows in updates.items():
                    if name == "waste":
                        error = waste.validate(rows)
                        if error:
                            raise StoreError(error)
                    elif name == "tasks":
                        if not isinstance(rows, list):
                            raise StoreError("Tasks must be a list.")
                        if any(not isinstance(t, dict) or not str(t.get("text", "")).strip() for t in rows):
                            raise StoreError("Each task needs a description.")
                    else:
                        if not isinstance(rows, list):
                            raise StoreError("Supplies must be a list.")
                        rows = [{k: v for k, v in s.items() if k != "stored"} for s in rows if isinstance(s, dict)]
                        names = [str(s.get("item", "")).strip().lower() for s in rows]
                        if "" in names or len(set(names)) != len(names):
                            raise StoreError("Each supply needs a name, and each name can appear once.")
                    loaded[name] = rows  # a list is saved as sent, so a cleared field stays cleared; other lists are untouched
                _write_atomic(path, header + yamlio.dump(loaded))  # the change log is for experiment records
            return self.followups()

    def changes(self, limit=200):
        path = self.layout.logs / "changes.jsonl"
        if not os.path.isfile(path):
            return []
        out = []
        for line in _read(path).splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out[::-1][:limit]

    # ------------------------------------------------------------ notebook build
    def has_build_script(self):
        return os.path.isfile(self.layout.build_script)

    def stale(self):
        """True when a record or the case text is newer than the generated index or notebook."""
        newest = self.layout.newest_input()
        outs = [self.layout.index, self.notebook_path()]
        if any(not os.path.isfile(p) for p in outs):
            return True
        built = min(os.path.getmtime(p) for p in outs)
        if newest > built + 90:  # files synced in one batch land seconds apart; that is not a change
            return True
        for c in self.changes(None):  # arrangement changes may follow the newest save or rebuild
            if c.get("action") == "build" and c.get("summary") == "notebook rebuilt":
                return False
            if c.get("action") in ("edit", "create", "word-import", "attach"):
                try:
                    return datetime.datetime.fromisoformat(c["ts"]).timestamp() + 1 >= built  # log times are whole seconds
                except (KeyError, ValueError):
                    return False
        return False

    def build(self, force=False, via="app"):
        """Regenerate index.md and the Word notebook.

        A case with its own build script checks for Word input before rebuilding. A forced
        rebuild with pending input first keeps a copy of that Word file."""
        from . import wordsync
        if not self.has_build_script():
            return self._build_generic(via)
        script = self.layout.build_script
        waiting = wordsync.pending(self)["items"]
        if waiting and not force:
            return {"ok": False, "pending": len(waiting), "kept": None,
                    "message": "%d field(s) typed in the Word notebook are not in the records yet. Rebuilding would drop them." % len(waiting)}
        kept = None
        if waiting:
            kept = "Notebook backups/Word input before rebuild %s.docx" % _now().strftime("%Y-%m-%d %H%M%S")
            os.makedirs(os.path.join(self.path, "Notebook backups"), exist_ok=True)
            shutil.copy2(self.notebook_path(), os.path.join(self.path, kept))
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([p for p in [env.get("PYTHONPATH"), yamlio.VENDOR] if p])
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        command = [sys.executable, script, self.path]
        if sys.flags.isolated:
            # Embeddable Python ignores PYTHONPATH and omits the case script's directory.
            bootstrap = """
import os, runpy, sys
vendor, script = sys.argv[1:3]
sys.path.insert(0, os.path.dirname(script))
sys.path.append(vendor)
sys.argv = sys.argv[2:]
runpy.run_path(script, run_name="__main__")
"""
            command = [sys.executable, "-X", "utf8", "-I", "-c", bootstrap, yamlio.VENDOR, script, self.path]
        try:
            p = subprocess.run(command, capture_output=True, text=True, timeout=300,
                               cwd=self.path, env=env, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            raise StoreError("The notebook build did not finish within five minutes.")
        ok = p.returncode == 0
        msg = (p.stdout or "").strip().splitlines()[-1:] if ok else (p.stderr or p.stdout or "").strip().splitlines()[-6:]
        text = "\n".join(msg)
        if not ok and "PermissionError" in (p.stderr or ""):
            text = _WORD_LOCKED + "\n" + text
        self._log_build(ok, via)
        if ok:
            wordsync.write_baseline(self)
        return {"ok": ok, "message": text, "pending": 0, "kept": kept}

    def _build_generic(self, via):
        from . import docx_export
        with self._record_lock():
            ok = False
            try:
                message = docx_export.export(self)
                ok = True
            except docx_export.NotebookLocked:
                message = _WORD_LOCKED
            except (StoreError, OSError, ValueError, yamlio.YAMLError) as e:
                message = "Could not build the notebook. " + str(e)
            self._log_build(ok, via)
        return {"ok": ok, "message": message, "pending": 0, "kept": None}

    def _log_build(self, ok, via):
        self._journal({"ts": _now().isoformat(), "by": via, "via": via, "exp": None, "action": "build", "fields": [],
                       "summary": "notebook rebuilt" if ok else "notebook build failed", "before": None, "after": None})
