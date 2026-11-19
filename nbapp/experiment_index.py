"""Content-addressed row summaries for the Experiments page and its record links."""
from collections import Counter, defaultdict
from datetime import datetime
import os
import threading

from . import outputs, store, structure, structure_files, structure_search


def _local_time(timestamp):
    return datetime.fromtimestamp(timestamp).astimezone().isoformat()


def _record_fields(rec):
    rid = rec["id"]
    flags = Counter(f.get("tier") for f in rec.get("flags") or [] if isinstance(f, dict))
    main = structure_search.main_materials(rec)
    pair = [structure_search.material_key(rec, m) for m in main]
    names = [m.get("name") for m in main]
    materials = []
    for m in rec.get("materials") or []:
        if not isinstance(m, dict):
            continue
        role = structure_search.material_role(m)
        if role in ("reactant", "product"):
            key = structure_search.material_key(rec, m)
            if key:
                materials.append((role, key, m["id"], m.get("name") or key))
    computational = "comput" in str(rec.get("type", "")).lower()
    drawable = not computational and any(">" not in text or structure.reaction_sides(text)
                                         for text in structure_files.preview_sources(rec))
    row = {k: rec.get(k) or "" for k in ("legacy_id", "title", "type", "status", "key_result", "researcher", "scheme_alt")}
    row.update(id=rid, n=store.expno(rid), started=str(rec.get("started") or ""), computational=computational,
               step=">>".join(pair) if all(isinstance(k, str) and k for k in pair) else "",
               reaction_title="%s from %s" % (names[1], names[0]) if all(names) else "",
               metric_kind=rec.get("metric_kind") or "yield", best=outputs.best_entry(rec),
               planned=bool(rec.get("planned")), runs=len(rec.get("runs") or []), error=rec.get("_error"),
               flags={tier: flags[tier] for tier in store.TIERS})
    # Keep only record fields needed to refresh filesystem-dependent facts.
    files = {k: rec[k] for k in ("id", "scheme_image", "nmr") if k in rec}
    return row, files, drawable, materials


class Index:
    def __init__(self):
        self.lock = threading.Lock()
        self.records = {}
        self.journal_stamp = None
        self.created = {}

    def _creation_times(self, case):
        path = case.layout.logs / "changes.jsonl"
        try:
            stat = path.stat()
            stamp = stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            stamp = None
        if stamp != self.journal_stamp:
            created = {}
            for c in case.changes(None):
                if c.get("action") == "create":
                    try:
                        created[c["exp"]] = datetime.fromisoformat(c["ts"].replace("Z", "+00:00")).astimezone().isoformat()
                    except (KeyError, ValueError, TypeError):
                        continue
            self.created, self.journal_stamp = created, stamp
        return self.created

    def rows(self, case):
        with self.lock:
            current = {}
            created = self._creation_times(case)
            rows = []
            reactants, products = defaultdict(list), defaultdict(list)
            for rid in case.layout.ids(occupied=True):
                path = case.layout.record_path(rid)
                try:
                    with path.open(encoding="utf8") as fh:
                        stat = os.fstat(fh.fileno())
                        text = fh.read()
                except FileNotFoundError:
                    continue
                digest = store._sha(text)
                cached = self.records.get(rid)
                if cached is None or cached[0] != digest:
                    try:
                        rec = case.parse_record(rid, path, text)
                    except store.StoreError as exc:
                        rec = dict(id=rid, title="(unreadable record)", type="?", status="error", _error=str(exc))
                    cached = digest, _record_fields(rec)
                current[rid] = cached
                row, files, drawable, materials = cached[1]
                acq = case.acquisitions(files)
                image = not row["computational"] and structure_files.scheme_image(case, files)
                rows.append(dict(row, hash=digest, scheme=bool(image or drawable), previous=[], next=[],
                                 created=created.get(rid) or _local_time(getattr(stat, "st_birthtime", stat.st_ctime)),
                                 modified=_local_time(stat.st_mtime), samples=len(acq),
                                 spectra=sum(len(a["spectra"]) for a in acq)))
                for role, key, mid, name in materials:
                    (products if role == "product" else reactants)[key].append((rid, mid, name))
            self.records = current
        by_id = {r["id"]: r for r in rows}
        for key, producers in products.items():
            for src, product, name in producers:
                for dst, reactant, other_name in reactants.get(key, ()):
                    if src == dst:
                        continue
                    link = dict(product=product, reactant=reactant, name=name if name != key else other_name)
                    by_id[src]["next"].append(dict(link, id=dst))
                    by_id[dst]["previous"].append(dict(link, id=src))
        return rows
