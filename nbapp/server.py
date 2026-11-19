"""Local web server for the notebook app. Listens on 127.0.0.1 only."""
import base64
import collections
import getpass
import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import arrangement, project_setup, structure, structure_files, structure_search
from . import attachments, chem, formatting, multiplets, fid, inventory, nmr, outputs, reference, runtime_info, store, wordsync, yamlio

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
VERSION = "1.1"
UPLOAD_LIMIT = 200 * 1024 * 1024
INLINE = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
          ".svg": "image/svg+xml", ".md": "text/plain; charset=utf-8", ".yaml": "text/plain; charset=utf-8",
          ".txt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8", ".json": "application/json"}
# Internal-standard regions in CDCl3 (ppm, CHCl3 = 7.26). Product regions are case-specific: <case>/_build/nmr.yaml.
STANDARD_PRESETS = [
    {"name": "Mesitylene ArH", "lo": 6.77, "hi": 6.83, "nH": 3},
    {"name": "Mesitylene CH3", "lo": 2.24, "hi": 2.33, "nH": 9},
    {"name": "1,3,5-Trimethoxybenzene ArH", "lo": 6.05, "hi": 6.13, "nH": 3},
    {"name": "1,3,5-Trimethoxybenzene OCH3", "lo": 3.73, "hi": 3.81, "nH": 9},
    {"name": "Dibromomethane CH2", "lo": 4.89, "hi": 4.97, "nH": 2},
]
STD_NAMES = re.compile(r"mesitylene|internal standard|trimethoxybenzene|dibromomethane|\bTMB\b", re.I)


class HttpError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


SCHEDULE_OFF = 'Schedule and supplies is switched off. Set schedule_and_supplies to "on" to open it.'


def load_config(root):
    cfg = {"user": "", "port": 8765, "inventory_dir": "inventory", "own_group": "", "reference_lookup": "off",
           "schedule_and_supplies": "off"}
    path = os.path.join(HERE, "config.yaml")
    if os.path.normcase(os.path.realpath(root)) == os.path.normcase(os.path.dirname(HERE)) and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update(yamlio.load(fh.read()) or {})
    return cfg


class App:
    def __init__(self, root, config=None, reference_client=None):
        self.project = store.Project(root)
        self.config = load_config(root) if config is None else config
        # YAML accepts both quoted "on" and an unquoted on (boolean true).
        switch = self.config.get("schedule_and_supplies")
        self.schedule_and_supplies = switch is True or switch == "on"
        self.reference_client = reference_client
        self.user = self.config.get("user") or getpass.getuser()
        self.token = secrets.token_urlsafe(24)
        self.structure_indexes = {}
        self.working_copies = structure_files.WorkingCopies()
        self._spectra = collections.OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ helpers
    def inventory_dir(self, case=None):
        folder = os.path.join(self.project.root, self.config.get("inventory_dir") or "inventory")
        if case is not None and case.cfg().get("demo") is True and not inventory.source(folder)["files"]:
            return inventory.DEMO_FOLDER
        return folder

    def case_state(self, case):
        cfg = case.cfg()
        state = {"name": case.name, "title": cfg.get("title", case.name), "notebook": cfg.get("notebook"), "stale": case.stale()}
        if cfg.get("demo") is True:
            state["demo"] = True
        return state

    def spectrum(self, case, folder, acq, settings=None):
        acq_dir = case.layout.acquisition(folder, acq)
        if not os.path.isdir(acq_dir):
            raise HttpError(404, "No acquisition %s in %s." % (acq, folder))
        settings = {} if settings is None else settings
        if not isinstance(settings, dict) or settings.get("source", "topspin") not in ("topspin", "fid"):
            raise HttpError(400, "Choose a spectrum source (topspin or fid).")
        if settings.get("source") == "fid":
            try:
                return fid.process(acq_dir, **{k: settings[k] for k in ("lb_hz", "points", "phase_mode", "ph0", "ph1")
                                               if k in settings})
            except nmr.NmrError as exc:
                raise HttpError(400, str(exc)) from exc
        key = case.layout.spectrum_cache_key(acq_dir)
        with self._lock:
            if key in self._spectra:
                self._spectra.move_to_end(key)
                return self._spectra[key]
        try:
            spec = nmr.Spectrum(acq_dir)
        except nmr.NmrError as e:
            raise HttpError(404, str(e))
        with self._lock:
            self._spectra[key] = spec
            while len(self._spectra) > 12:
                self._spectra.popitem(last=False)
        return spec

    def nmr_defaults(self, rec):
        mats = rec.get("materials") or []
        std = next((m for m in mats if STD_NAMES.search(str(m.get("name", ""))) and isinstance(m.get("mmol"), (int, float))), None)
        lim = next((m for m in mats if str(m.get("id", "")).startswith("R") and m.get("equiv") == 1 and isinstance(m.get("mmol"), (int, float))), None)
        std_mmol = std["mmol"] if std else None
        digits = len(repr(float(std_mmol)).replace(".", "").lstrip("0")) if std_mmol else 0
        if std and lim and digits < 3 and isinstance(std.get("equiv"), (int, float)) and std["equiv"] > 0:
            std_mmol = round(std["equiv"] * lim["mmol"], 6)  # a mmol printed to two figures (0.017): equiv x limiting keeps the digits
        return {"std_mmol": std_mmol, "std_name": std["name"] if std else None,
                "limiting_mmol": lim["mmol"] if lim else None, "limiting_name": lim["name"] if lim else None}

    def presets(self, case):
        path = case.layout.presets
        try:
            with open(path, encoding="utf-8") as fh:
                cfg = yamlio.load(fh.read()) or {}
        except FileNotFoundError:
            return {"product": [], "standard": []}
        except (OSError, yamlio.YAMLError):  # a broken presets file must not take the yield tool down
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        ok = lambda p: isinstance(p, dict) and all(isinstance(p.get(k), (int, float)) for k in ("lo", "hi", "nH")) and p.get("name")
        own = [p for p in cfg.get("standard") or [] if ok(p)]
        names = set(p["name"] for p in own)
        return {"product": [p for p in cfg.get("product") or [] if ok(p)],
                "standard": own + [p for p in STANDARD_PRESETS if p["name"] not in names]}

    def arrangement_view(self, case):
        rows = case.summary()
        state = case.arrangement([r["id"] for r in rows])
        return rows, state, arrangement.parents(rows, state["data"]), arrangement.sequences(rows, state["data"])

    def record_view(self, case, rid):
        rec, meta = case.read(rid)
        rows, state, groups, routes = self.arrangement_view(case)
        ids = [r['id'] for r in rows]
        i = ids.index(rid)
        src = rec.get("sources") or {}
        scheme = case.scheme(rec)
        acqs = case.acquisitions(rec)
        text = chem.plan_text(rec)
        run_samples = {}
        for run in rec.get("runs") or []:
            if isinstance(run, dict):
                s = case.run_sample(rec, run.get("run"))
                if s:
                    run_samples[str(run.get("run"))] = s["sample"]
        return {"record": rec, "meta": meta, "derived": {
            "n": store.expno(rid), "prev": ids[i - 1] if i else None, "next": ids[i + 1] if i + 1 < len(ids) else None,
            **case.layout.record_links(rid),
            **arrangement.record_context(rid, rows, state, groups, routes),
            "locations": inventory.record_locations(self.inventory_dir(case), self.config.get("own_group"), rec.get("materials") or []),
            "material_drawings": {m["id"]: structure_search._highlight(s, (), ()) for m in rec.get("materials") or []
                                  if not structure.REASON and (s := structure.material_smiles(rec, m)) and structure_search._entry(s)},
            "scheme_options": structure_files.scheme_options(case, rec),
            "index_scheme": rows[i]["scheme"],
            "scheme_preview": structure_files.record_preview(rec) if not scheme else None,
            "same_step": self.structure_indexes.setdefault(case.name, structure_search.Index()).same_step(case, rid)
                if not structure.REASON and any(structure.material_smiles(rec, m) or m.get("inchikey") for m in rec.get("materials") or [] if isinstance(m, dict)) else [],
            "scheme": scheme, "scheme_is_full_drawing": bool(scheme and scheme.endswith("-scheme-materials.png")),
            "eln": src.get("eln") if src.get("eln") and case.layout.asset(rid, src["eln"]).is_file() else None,
            "chemdraw": src.get("chemdraw") if src.get("chemdraw") and case.layout.asset(rid, src["chemdraw"]).is_file() else None,
            "acquisitions": acqs, "run_samples": run_samples, "validation": case.validate(rec, rid),
            "attachments": case.attachment_states(rec), "attachment_kinds": attachments.KINDS,
            "hazards": chem.hazard_prompts(rec.get("materials"), text), "nmr_defaults": self.nmr_defaults(rec),
            "nmr_presets": self.presets(case), "unlinked_nmr": case.unlinked_nmr(rec),
            "yaml": yamlio.dump(rec)}}

    def batch_yield(self, case, body):
        rec, _ = case.read(body["exp"])
        out = []
        by_run = body.get("processing_by_run", {})
        if not isinstance(by_run, dict):
            raise HttpError(400, "Processing settings must be keyed by run.")
        overrides = body.get("regions_by_run", {})
        if not isinstance(overrides, dict) or not all(store.valid_manual_regions(v) for v in overrides.values()):
            raise HttpError(400, "Each manual region needs increasing numeric bounds for product and standard.")
        for run in rec.get("runs") or []:
            sample = case.run_sample(rec, run.get("run"))
            row = {"run": str(run.get("run")), "variable": run.get("variable", ""), "recorded": run.get("result", ""),
                   "basis": run.get("basis", ""), "sample": sample["sample"] if sample else None}
            h1 = next((s for s in sample["spectra"] if s["nucleus"] == "1H"), None) if sample and sample["exists"] else None
            if not h1:
                row["note"] = "no ¹H spectrum for this run"
            else:
                row.update(folder=sample["folder"], acq=h1["acq"])
                try:
                    settings = by_run.get(row["run"], body.get("processing", body))
                    spec = self.spectrum(case, sample["folder"], h1["acq"], settings)
                    manual = overrides.get(row["run"])
                    product, standard = (dict(body[k], lo=manual[k][0], hi=manual[k][1]) if manual else body[k]
                                         for k in ("product", "standard"))
                    res = nmr.nmr_yield(spec, product, standard, body.get("std_mmol"), body.get("limiting_mmol"),
                                        baseline=body.get("baseline", True), reference=body.get("reference", True), snap=not manual and body.get("snap", True))
                    if manual:
                        res["regions"] = manual
                    row["calc"] = dict(res, processing=spec.processing)
                except (HttpError, nmr.NmrError, ValueError, OSError) as e:
                    row["note"] = str(e)
            out.append(row)
        return out

    def open_chemdraw(self, path):
        if sys.platform.startswith("win"):
            import ctypes
            from ctypes import wintypes
            query = ctypes.windll.shlwapi.AssocQueryStringW
            query.argtypes = (wintypes.DWORD, ctypes.c_int, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
            names = []
            for field in (2, 4):  # ASSOCSTR_EXECUTABLE, ASSOCSTR_FRIENDLYAPPNAME
                buf = ctypes.create_unicode_buffer(4096)
                length = wintypes.DWORD(len(buf))
                if query(0, field, ".cdxml", "open", buf, ctypes.byref(length)) == 0:
                    names.append(os.path.basename(buf.value).casefold())
            if not any("chemdraw" in name for name in names):
                raise OSError("ChemDraw is not associated with .cdxml.")
        self.open_native(path)

    def open_native(self, path):
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: only on Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "NotebookApp/" + VERSION

        def log_message(self, fmt, *args):  # quiet: errors only
            if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
                sys.stderr.write("%s %s\n" % (self.command, fmt % args))

        # ---------------------------------------------------- plumbing
        def _send(self, status, body, ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self._send_headers(status, len(body), ctype, extra)
            self.wfile.write(body)

        def _send_headers(self, status, size, ctype, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if "Cache-Control" not in (extra or {}):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _upload(self, case, rid, q):
            name = q.get("name", "")
            attachments.check_name(name)
            kind = q.get("kind")
            if kind not in attachments.KINDS:
                raise HttpError(400, "Choose an attachment kind.")
            case.read(rid)
            with tempfile.TemporaryDirectory(prefix=".upload-", dir=case.path) as staging:
                source = os.path.join(staging, name)
                self._receive_file(source)
                result = case.attach(rid, source, kind, sample=q.get("sample"), run=q.get("run"), by=app.user,
                                     note=q.get("note", ""), expect_hash=q.get("hash"), upload_name=name)
            return self._send(200, result)

        def _receive_file(self, path):
            length = self.headers.get("Content-Length", "")
            if not re.fullmatch(r"[0-9]+", length):
                raise HttpError(400, "The upload needs a file size.")
            remaining = int(length)
            if remaining > UPLOAD_LIMIT:
                raise HttpError(413, "Attach a file up to 200 MB.")
            with open(path, "xb") as fh:
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise HttpError(400, "The upload ended before the file was complete.")
                    fh.write(chunk)
                    remaining -= len(chunk)

        def _import_inventory(self, name):
            attachments.check_name(name)
            if not name.lower().endswith(".xlsx") or name.startswith("~$"):
                raise HttpError(400, "Choose an .xlsx inventory workbook.")
            folder = app.inventory_dir()
            os.makedirs(folder, exist_ok=True)
            destination = os.path.join(folder, name)
            with tempfile.TemporaryDirectory(prefix=".import-", dir=folder) as staging:
                source = os.path.join(staging, name)
                self._receive_file(source)
                try:
                    count = len(inventory.workbook_items(source))
                except ValueError as exc:
                    raise HttpError(400, str(exc)) from exc
                try:
                    # Both operations publish a complete file and refuse an existing name.
                    if os.name == "nt":
                        os.rename(source, destination)
                    else:
                        os.link(source, destination)
                except FileExistsError as exc:
                    raise HttpError(409, "An export named %s already exists. To update it, replace the file in %s." %
                                    (name, folder)) from exc
            return self._send(201, {"name": name, "bottles": count})

        def _attachment_folder(self, case, rel, rid):
            folder = case.layout.attachment_path(rid, rel)
            rec, _ = case.read(rid)
            for entry in rec.get("attachments") or []:
                if not isinstance(entry, dict):
                    continue
                try:
                    parent = case.layout.attachment_path(rid, entry.get("path"))
                except (store.StoreError, ValueError, OSError):
                    continue
                if os.path.isdir(parent) and os.path.normcase(os.path.commonpath([folder, parent])) == os.path.normcase(parent):
                    break
            else:
                raise HttpError(404, "Attachment folder not found.")
            links = []
            base = "/file/" + urllib.parse.quote(case.name, safe="") + "/"
            with os.scandir(folder) as entries:
                for item in sorted(entries, key=lambda entry: entry.name):
                    if item.is_symlink():
                        continue
                    child = rel.rstrip("/") + "/" + item.name
                    try:
                        case.layout.attachment_path(rid, child)
                    except (store.StoreError, ValueError, OSError):
                        continue
                    href = base + urllib.parse.quote(child)
                    label = item.name
                    if item.is_dir():
                        href += "?exp=" + rid
                        label += "/"
                    links.append('<li><a href="%s">%s</a></li>' % (html.escape(href, quote=True), html.escape(label)))
            title = html.escape(os.path.basename(folder))
            page = '<!doctype html><html lang="en"><meta charset="utf-8"><title>%s</title><h1>%s</h1>%s</html>'
            contents = "<ul>%s</ul>" % "".join(links) if links else "<p>This folder is empty.</p>"
            return self._send(200, page % (title, title, contents), "text/html; charset=utf-8")

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 5 * 1024 * 1024:
                raise HttpError(413, "Request too large.")
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                raise HttpError(400, "Request body is not JSON.")

        def _guard(self, write):
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                raise HttpError(403, "This app only answers on this computer.")
            if write and not secrets.compare_digest(self.headers.get("X-NB-Token") or "", app.token):
                raise HttpError(403, "Session expired. Reload the page.")

        def _dispatch(self, method):
            try:
                url = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(url.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                self._guard(method != "GET")
                self._route(method, path, q)
            except HttpError as e:
                self._send(e.status, {"error": str(e)})
            except store.StoreError as e:
                self._send(e.status, {"error": str(e)})
            except (structure.StructureError, attachments.AttachmentError) as e:
                self._send(400, {"error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # report, never crash the server
                traceback.print_exc()
                self._send(500, {"error": "Unexpected error: %s" % e})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        # ---------------------------------------------------- routes
        def _route(self, method, path, q):
            if method == "GET" and path in ("/", "/index.html"):
                with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
                    page = fh.read().replace("{{TOKEN}}", app.token).replace("{{VERSION}}", VERSION)
                return self._send(200, page, "text/html; charset=utf-8")
            if method == "GET" and path.startswith("/sketcher/"):
                parts = path[len("/sketcher/"):].split("/")
                try:
                    for part in parts:
                        attachments.check_name(part)
                except attachments.AttachmentError:
                    raise HttpError(404, "Sketcher file not found.")
                root = runtime_info.SKETCHER.resolve()
                full = root.joinpath(*parts).resolve()
                if not full.is_relative_to(root) or not full.is_file():
                    raise HttpError(404, "Sketcher file not found. Run py -3 packaging/build_sketcher.py.")
                types = {".html": "text/html; charset=utf-8", ".wasm": "application/wasm",
                         ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
                ctype = types.get(full.suffix) or mimetypes.guess_type(full.name)[0] or "application/octet-stream"
                # The bundle constructs parser functions and boots embedded Indigo in a blob worker.
                policy = ("default-src 'none'; script-src 'self' 'unsafe-eval'; worker-src 'self' blob:; "
                          "style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self' data:; "
                          "connect-src 'self'; manifest-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
                with full.open("rb") as fh:
                    self._send_headers(200, os.fstat(fh.fileno()).st_size, ctype, {"Content-Security-Policy": policy})
                    return shutil.copyfileobj(fh, self.wfile)
            if method == "GET" and path.startswith("/static/"):
                name = os.path.basename(path)
                full = os.path.join(STATIC, name)
                if not os.path.isfile(full):
                    raise HttpError(404, "Not found.")
                ctype = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}.get(os.path.splitext(name)[1], "application/octet-stream")
                with open(full, "rb") as fh:
                    return self._send(200, fh.read(), ctype)
            if method == "GET" and path in ("/help/MANUAL.md", "/help/DEMO.md", "/help/README.md", "/help/SCHEMA.md", "/help/THIRD_PARTY_NOTICES.md"):
                with open(os.path.join(HERE, os.path.basename(path)), "rb") as fh:
                    return self._send(200, fh.read(), "text/plain; charset=utf-8")
            if method == "GET" and path == "/api/state":
                cases = [app.case_state(app.project.case(name)) for name in app.project.case_names()]
                return self._send(200, {"cases": cases, "user": app.user, "version": VERSION,
                                        "root": app.project.root, "elements": chem.ELEMENTS, "formula_rules": formatting.RULES,
                                        "schedule_and_supplies": app.schedule_and_supplies,
                                        "schedule_off_message": SCHEDULE_OFF,
                                        "reference_lookup": app.config.get("reference_lookup", "off"),
                                        "sketcher": runtime_info.sketcher_info(), "about": runtime_info.about(), "structure_reason": structure.REASON,
                                        "inventory": bool(inventory.source(app.inventory_dir())["files"]),
                                        "inventory_dir": app.config.get("inventory_dir") or "inventory"})
            if method == "POST" and path == "/api/cases":
                b = self._body()
                if not isinstance(b, dict):
                    raise HttpError(400, "Enter a notebook name.")
                case = project_setup.start(app.project, b.get("name"), title=b.get("title", ""), researcher=b.get("researcher", ""))
                return self._send(201, app.case_state(case))
            if method == "POST" and path == "/api/demo":
                self._body()
                case = project_setup.demo(app.project)
                return self._send(201, app.case_state(case))
            if method == "GET" and path == "/api/inventory":
                case = app.project.case(q["case"]) if q.get("case") else None
                folder = app.inventory_dir(case)
                result = inventory.search(folder, q.get("q", ""), app.config.get("own_group", ""))
                result["inventory_dir"] = app.config.get("inventory_dir") or "inventory"
                result["demo_inventory"] = folder == inventory.DEMO_FOLDER
                if not q.get("q"):
                    result["bottles"] = len(inventory.load(folder))
                return self._send(200, result)
            if method == "POST" and path == "/api/inventory/import":
                return self._import_inventory(q.get("name", ""))
            if method == "POST" and path == "/api/hazards":
                b = self._body()
                return self._send(200, {"prompts": chem.hazard_prompts(b.get("materials"), b.get("text", ""))})
            if method == "POST" and path == "/api/lookup":
                provider = app.config.get("reference_lookup")
                if provider != "pubchem":
                    raise HttpError(403, reference.OFF)
                b = self._body()
                if not isinstance(b, dict) or type(b.get("refresh", False)) is not bool:
                    raise HttpError(400, "Enter one compound name or CAS number.")
                try:
                    by_key = "inchikey" in b
                    result = reference.lookup(app.project.root, provider, b.get("inchikey") if by_key else b.get("query"),
                                              b.get("refresh", False), app.reference_client, by_key=by_key)
                except reference.NoMatch as exc:
                    raise HttpError(404, str(exc))
                except reference.LookupError as exc:
                    raise HttpError(400, str(exc))
                return self._send(200, result)

            m = re.match(r"^/file/([^/]+)/(.+)$", path)
            if method == "GET" and m:
                case = app.project.case(m.group(1))
                full = (case.layout.attachment_path(q["exp"], m.group(2)) if q.get("exp")
                        else case.safe_path(m.group(2)))
                if q.get("exp") and os.path.isdir(full):
                    return self._attachment_folder(case, m.group(2), q["exp"])
                if not os.path.isfile(full):
                    raise HttpError(404, "File not found: %s" % m.group(2))
                ext = os.path.splitext(full)[1].lower()
                ctype = INLINE.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
                extra = {} if ext in INLINE else {"Content-Disposition": "attachment; filename*=UTF-8''%s" % urllib.parse.quote(os.path.basename(full))}
                if ext == ".svg":
                    extra["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
                with open(full, "rb") as fh:
                    self._send_headers(200, os.fstat(fh.fileno()).st_size, ctype, extra)
                    return shutil.copyfileobj(fh, self.wfile)

            m = re.match(r"^/api/case/([^/]+)(/.*)?$", path)
            if not m:
                raise HttpError(404, "Not found.")
            case = app.project.case(m.group(1))
            rest = m.group(2) or "/"
            user = app.user

            if rest.startswith("/structures/"):
                structure.require()
                action = rest[len("/structures/"):]
                if method == "GET" and action == "library":
                    return self._send(200, {"rows": structure_files.library(case, q.get("q", ""))})
                if method == "GET" and action == "inventory":
                    bottles = structure_search.bottles(app.project.root, inventory.load(app.inventory_dir(case)))
                    return self._send(200, {"count": len(bottles)})
                if method == "POST":
                    b = self._body()
                    if not isinstance(b, dict):
                        raise HttpError(400, "Enter structure text.")
                    if action == "parse":
                        worker = getattr(self.server, "parser", None)
                        parsed = structure.parse(b.get("text"), b.get("step", 0), b.get("focus"), b.get("roles"),
                                                 b.get("sketch") is True, worker=worker, species_only=b.get("speciesOnly") is True)
                        mode = b.get("identify")
                        if mode in ("preview", "once", "refresh"):
                            index = app.structure_indexes.setdefault(case.name, structure_search.Index())
                            parsed["identities"] = structure_search.identify(
                                case, index, lambda: structure_search.bottles(app.project.root, inventory.load(app.inventory_dir(case))),
                                parsed["molecules"], app.config.get("reference_lookup"), worker.propose,
                                app.reference_client, once=mode != "preview", refresh=mode == "refresh")
                        return self._send(200, parsed)
                    if action == "library":
                        return self._send(200, structure_files.add_compounds(case, b))
                    if action == "sketch-input":
                        return self._send(200, structure_files.sketch_input(case, b.get("id"), b.get("material")))
                    if action == "material-change":
                        change = structure_files.material_scheme_change(
                            b.get("reaction"), b.get("target"), b.get("before"), b.get("after"), b.get("external") is True, b.get("name"))
                        if change.get("smiles"):
                            change["scheme"] = structure.parse(change["smiles"], worker=getattr(self.server, "parser", None))["scheme"]
                        return self._send(200, change)
                    if action == "pattern":
                        return self._send(200, {"svg": structure_search.pattern_svg(b.get("query"))})
                    if action == "resolve":
                        index = app.structure_indexes.setdefault(case.name, structure_search.Index())
                        return self._send(200, {"rows": structure_search.resolve(b.get("query"), case, index,
                            lambda: structure_search.bottles(app.project.root, inventory.load(app.inventory_dir(case))))})
                    if action == "library-search":
                        return self._send(200, {"rows": structure_files.library(case, b.get("q", ""), b.get("fragment", ""))})
                    if action == "bottles":
                        index = app.structure_indexes.setdefault(case.name, structure_search.Index())
                        return self._send(200, structure_search.search_inventory(
                            case, index, inventory.load(app.inventory_dir(case)), b.get("query"), b.get("mode"),
                            b.get("threshold", 0.7), b.get("switches", []),
                            b.get("lookup") is True or app.config.get("reference_lookup") == "pubchem", app.reference_client))
                    if action == "search":
                        mode, query, threshold = b.get("mode"), b.get("query"), b.get("threshold", 0.7)
                        index = app.structure_indexes.setdefault(case.name, structure_search.Index())
                        scope, role, switches = b.get("scope", "all"), b.get("role", "any"), b.get("switches", [])
                        if scope not in ("experiments", "reactions", "inventory", "library", "all") or not isinstance(query, str):
                            raise HttpError(400, "Choose a search scope and enter a structure.")
                        hits = index.search(case, query, mode, role, threshold, scope, switches) if scope in (
                            "all", "experiments", "reactions") else []
                        bottles = structure_search.bottles(app.project.root, inventory.load(app.inventory_dir(case)))
                        inventory_hits = []
                        library_hits = []
                        if mode != "transformation" and ">" not in query and role == "any":
                            match = structure_search.matcher(query, mode, threshold, switches)
                            if scope in ("library", "all"):
                                library_hits = [hit for row in structure_files.library_rows(case) if (hit := match(row))]
                            for bottle in bottles if scope in ("all", "inventory") else []:
                                hit = match(bottle)
                                if hit:
                                    inventory_hits.append({**bottle, **hit})
                        return self._send(200, {"hits": hits, "bottles": inventory_hits, "library": library_hits, "count": len(bottles)})
                    if action == "open":
                        return self._send(200, app.working_copies.start(case, b, app.open_chemdraw, self.server.parser))
                    if action in ("poll", "accept", "discard"):
                        return self._send(200, app.working_copies.update(case, action, b, self.server.parser))
            if method == "GET" and rest == "/index":
                cfg = case.cfg()
                rows, state, groups, routes = app.arrangement_view(case)
                return self._send(200, {"case": case.name, "title": cfg.get("title", case.name), "question": cfg.get("project_question", ""),
                                        "caveats": cfg.get("caveats", []), "notebook": cfg.get("notebook"), "rows": rows,
                                        "arrangement": state, "parents": groups, "sequences": routes,
                                        "researcher": case.researcher(rows), "references": cfg.get("references") or {},
                                        "stale": case.stale(), "next_id": case.next_id(),
                                        "nmr_hints": case.layout.sample_hints()})
            if method == "GET" and rest == "/search":
                return self._send(200, {"hits": case.search(q.get("q", ""))})
            if method == "GET" and rest == "/changes":
                return self._send(200, {"changes": case.changes(int(q.get("limit", 200)))})
            if method == "GET" and rest == "/validate":
                warnings = case.arrangement()["warnings"]
                out = [{"id": "arrangement.yaml", "notes": [{"level": "warn", "msg": w} for w in warnings]}] if warnings else []
                try:
                    structure_files.library_rows(case)
                except store.StoreError as exc:
                    out.append({"id": "compounds.yaml", "notes": [{"level": "error", "msg": str(exc)}]})
                for rid in case.ids():
                    try:
                        rec, _ = case.read(rid)
                        notes = case.validate(rec, rid)
                    except store.StoreError as e:
                        notes = [{"level": "error", "msg": str(e)}]
                    if notes:
                        out.append({"id": rid, "notes": notes})
                return self._send(200, {"records": out})
            if method == "GET" and rest == "/flags":
                out = []
                for rec in case.all():
                    for f in rec.get("flags") or []:
                        out.append({"exp": rec["id"], "n": store.expno(rec["id"]), "title": rec.get("title", ""), "id": f.get("id"),
                                    "tier": f.get("tier"), "text": f.get("text")})
                return self._send(200, {"flags": out})
            if method == "POST" and rest == "/build":
                return self._send(200, case.build(force=bool(self._body().get("force"))))
            if method == "POST" and rest == "/convert":  # one draft for the form and the record-file view
                b = self._body()
                if b.get("yaml") is not None:
                    try:
                        rec = yamlio.load(b["yaml"])
                    except Exception as e:
                        raise HttpError(400, "The YAML does not parse: %s" % str(e).splitlines()[0])
                    if not isinstance(rec, dict):
                        raise HttpError(400, "The text is not a record.")
                    return self._send(200, {"record": rec})
                return self._send(200, {"yaml": yamlio.dump(b.get("record") or {})})
            if method == "POST" and rest == "/open":
                b = self._body()
                full = case.safe_path(b.get("path", ""))
                if not os.path.exists(full):
                    raise HttpError(404, "Not found on disk: %s" % b.get("path"))
                if os.path.splitext(full)[1].lower() == ".cdxml":
                    raise HttpError(400, "Use Edit in ChemDraw to open a working copy.")
                app.open_native(full)
                return self._send(200, {"ok": True})
            if method == "GET" and rest == "/arrangement":
                return self._send(200, case.arrangement())
            if (method, rest) in (("PUT", "/arrangement"), ("POST", "/arrangement/undo")):
                b = self._body()
                if not isinstance(b, dict):
                    raise HttpError(400, "Expected an arrangement request.")
                return self._send(200, case.save_arrangement(b.get("data"), b.get("hash"), b.get("summary"),
                                                             by=user, undo=rest.endswith("/undo")))
            if not app.schedule_and_supplies and (rest == "/followups" or rest.startswith("/followups/")):
                raise HttpError(404, SCHEDULE_OFF)
            if method == "GET" and rest == "/followups/waste" and q.get("format") == "csv":
                return self._send(200, case.waste_csv(q.get("id", "")), "text/csv; charset=utf-8",
                                  {"Content-Disposition": "attachment; filename=waste-log.csv"})
            if method == "GET" and rest in ("/followups", "/followups/waste"):
                return self._send(200, case.followups())
            if method == "PUT" and rest == "/followups":
                b = self._body()
                return self._send(200, case.save_followups(b.get("tasks"), b.get("supplies"), expect_hash=b.get("hash"), by=user))
            if method == "PUT" and rest == "/followups/waste":
                b = self._body()
                return self._send(200, case.save_waste(b.get("waste"), expect_hash=b.get("hash")))
            if method == "GET" and rest == "/screening":
                if q.get("format") == "csv":
                    return self._send(200, outputs.screening_csv(case), "text/csv; charset=utf-8",
                                      {"Content-Disposition": "attachment; filename=screening.csv"})
                return self._send(200, {"rows": outputs.screening_rows(case)})
            if method == "GET" and rest == "/wordsync":
                return self._send(200, wordsync.pending(case))
            if method == "POST" and rest == "/wordsync":
                return self._send(200, wordsync.apply(case, self._body().get("tags", []), by=user))

            thumbnail = re.fullmatch(r"/record/(EXP-\d+)/scheme", rest)
            if thumbnail and method == "GET":
                rid = thumbnail[1]
                rec, meta = case.read(rid)
                if "comput" in str(rec.get("type", "")).lower():
                    raise HttpError(404, "No scheme.")
                image = structure_files.scheme_image(case, rec)
                tag = meta["hash"]
                if image:
                    ctype = structure_files.SCHEME_TYPES[image.suffix.lower()]
                    stat = image.stat()
                    tag += "-%x-%x" % (stat.st_mtime_ns, stat.st_size)
                headers = {"ETag": '"' + tag + '"', "Cache-Control": "private, no-cache",
                           "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"}
                if self.headers.get("If-None-Match") == headers["ETag"]:
                    return self._send(304, b"", "image/png", headers)
                if image:
                    with image.open("rb") as fh:
                        self._send_headers(200, os.fstat(fh.fileno()).st_size, ctype, headers)
                        return shutil.copyfileobj(fh, self.wfile)
                preview = structure_files.record_preview(rec, worker=getattr(self.server, "parser", None), materials=True)
                if not preview:
                    raise HttpError(404, "No scheme.")
                return self._send(200, base64.b64decode(preview["plain"]), "image/png", headers)

            upload = re.fullmatch(r"/record/(EXP-\d+)/attach", rest)
            if upload and method == "POST":
                return self._upload(case, upload.group(1), q)
            m2 = re.match(r"^/record/(EXP-\d+)$", rest)
            if m2 and method == "GET":
                return self._send(200, app.record_view(case, m2.group(1)))
            if m2 and method == "PUT":
                b = self._body()
                rec = b.get("record")
                if b.get("yaml") is not None:
                    try:
                        rec = yamlio.load(b["yaml"])
                    except Exception as e:
                        raise HttpError(400, "The YAML does not parse: %s" % str(e).splitlines()[0])
                if not isinstance(rec, dict):
                    raise HttpError(400, "No record in the request.")
                res = case.write(m2.group(1), rec, expect_hash=b.get("hash"), by=user, summary=b.get("summary", ""),
                                 structures=b.get("structures"), worker=getattr(self.server, "parser", None))
                return self._send(200, res)
            if method == "POST" and rest == "/record":
                b = self._body()
                rec = b.get("record")
                if not isinstance(rec, dict):
                    raise HttpError(400, "No record in the request.")
                return self._send(200, case.create(rec, by=user, structures=b.get("structures"), worker=getattr(self.server, "parser", None)))
            m2 = re.match(r"^/si/(EXP-\d+)$", rest)
            if m2 and method == "GET":
                rec, _ = case.read(m2.group(1))
                return self._send(200, outputs.si_draft(case, rec))

            if method == "GET" and rest == "/nmr/presets":
                return self._send(200, app.presets(case))
            if method == "GET" and rest == "/nmr/meta":
                np, reason = runtime_info.numpy_support()
                return self._send(200, {"fid_available": np is not None, "fid_reason": reason})
            if method == "POST" and rest == "/nmr/proposal":
                b = self._body()
                spec = app.spectrum(case, b.get("folder"), b.get("acq"), b.get("processing"))
                try:
                    proposal = multiplets.proposal(spec, outputs.CDCL3_IMPURITIES, b.get("reference_group"), b.get("count"))
                except ValueError as exc:
                    raise HttpError(400, str(exc)) from exc
                return self._send(200, proposal)
            if method == "GET" and rest == "/nmr/spectrum":
                spec = app.spectrum(case, q.get("folder"), q.get("acq"), q)
                lo = float(q.get("lo", spec.lo))
                hi = float(q.get("hi", spec.offset))
                data = {"meta": dict(spec.meta(), processing=spec.processing), "reference": spec.solvent_shift(),
                        "env": spec.envelope(lo, hi, int(q.get("bins", 1200)))}
                if "print_bins" in q:
                    data["print_env"] = spec.envelope(lo, hi, int(q["print_bins"]))
                return self._send(200, data)
            if method == "POST" and rest == "/nmr/yield":
                b = self._body()
                spec = app.spectrum(case, b.get("folder"), b.get("acq"), b.get("processing", b))
                result = nmr.nmr_yield(spec, b["product"], b["standard"], b.get("std_mmol"), b.get("limiting_mmol"),
                                       baseline=b.get("baseline", True), reference=b.get("reference", True), snap=b.get("snap", True))
                return self._send(200, dict(result, processing=spec.processing))
            if method == "POST" and rest == "/nmr/batch":
                return self._send(200, {"runs": app.batch_yield(case, self._body())})
            raise HttpError(404, "Not found.")

    return Handler


class NotebookServer(ThreadingHTTPServer):
    def __init__(self, address, app):
        self.parser = structure.ParserWorker()
        super().__init__(address, make_handler(app))

    def server_close(self):
        self.parser.close()
        super().server_close()


def serve(root, port=None, open_browser=True, lookup=None):
    app = App(root)
    if lookup is not None:
        app.config["reference_lookup"] = lookup
    threading.Thread(target=inventory.load, args=(app.inventory_dir(),), daemon=True).start()
    port = int(port or app.config.get("port") or 8765)
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = NotebookServer(("127.0.0.1", p), app)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("No free port between %d and %d." % (port, port + 19))
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    cases = app.project.case_names()
    print("Integrated Notebook for Organic Chemistry %s" % VERSION)
    print("Project folder: %s" % app.project.root)
    print("Cases: %s" % (", ".join(cases) if cases else "none found (choose Start a notebook)"))
    print("Open %s  (Ctrl+C here to stop)" % url)
    sys.stdout.flush()
    if open_browser:
        try:
            import webbrowser
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
