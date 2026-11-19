"""Search the group chemical inventory exports (.xlsx) without any spreadsheet library.

Each workbook is read once per run (and again if the file changes) into memory.
"""
import datetime
import os
import re
import threading
from pathlib import Path
from functools import lru_cache
from collections import defaultdict, namedtuple
from . import yamlio
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLUMNS = {
    "chemname": "name", "chemicalname": "name", "name": "name", "barcode": "barcode",
    "location": "location", "locationpath": "path", "supplier": "supplier", "productno": "product",
    "sizeperunit": "size", "amountremaining": "remaining", "uom": "unit", "unit": "unit",
    "cas": "cas", "casno": "cas", "casnumber": "cas", "casrn": "cas", "casregistrynumber": "cas",
    "formula": "formula", "molformula": "formula", "molecularformula": "formula", "chemicalformula": "formula",
    "smiles": "smiles", "isomericsmiles": "smiles", "canonicalsmiles": "smiles",
    "assay": "assay", "assaywt": "assay", "densitygml": "density", "density": "density",
}
DEMO_FOLDER = Path(__file__).parent / "data/demo/inventory"
_cache = {}
_lock = threading.Lock()


def _col(ref):
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def read_xlsx(path):
    """Rows of the first worksheet as lists of strings."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as fh:
                for _, el in ET.iterparse(fh):
                    if el.tag == NS + "si":
                        shared.append("".join(t.text or "" for t in el.iter(NS + "t")))
                        el.clear()
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        if not sheets:
            return []
        rows = []
        with z.open(sheets[0]) as fh:
            for _, el in ET.iterparse(fh):
                if el.tag != NS + "row":
                    continue
                row = []
                for c in el.findall(NS + "c"):
                    idx = _col(c.get("r", "")) if c.get("r") else len(row)
                    kind = c.get("t")
                    v = c.find(NS + "v")
                    if kind == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif kind == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(NS + "t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    while len(row) < idx:
                        row.append("")
                    row.append(val)
                rows.append(row)
                el.clear()
        return rows


def _owner(filename):
    base = os.path.splitext(filename)[0]
    return re.sub(r"\s*inventory\s*", "", base, flags=re.I).strip().title()


Stock = namedtuple("Stock", "items by_cas by_name")
_EMPTY = Stock([], {}, {})


def load(folder):
    return _stock(folder).items


def _stock(folder):
    """Reuse the rows and their location indexes until an export changes."""
    if not folder or not os.path.isdir(folder):
        return _EMPTY
    folder = os.path.abspath(folder)
    files = sorted(os.path.join(folder, f) for f in os.listdir(folder)
                   if f.lower().endswith(".xlsx") and not f.startswith("~$"))
    stamp = tuple((f, os.stat(f).st_mtime_ns) for f in files)
    with _lock:
        if _cache.get("stamp") == stamp:
            return _cache["stock"]
        cached = _cache.get("books", {})
        books = {key: cached[key] if key in cached else _workbook(key[0]) for key in stamp}
        items = [item for rows in books.values() for item in rows]
        by_cas, by_name = defaultdict(list), defaultdict(list)
        for item in items:
            if item.get("cas"):
                by_cas[item["cas"]].append(item)
            name = item["name"].casefold()
            prefixes = {name, *(name[:m.start()].rstrip() for m in re.finditer(r"[,(]", name))}
            for prefix in prefixes:
                if prefix:
                    by_name[prefix].append(item)
        stock = Stock(items, by_cas, by_name)
        _cache.update(stamp=stamp, stock=stock, books=books)
        return stock


def _workbook(path):
    try:
        return workbook_items(path)
    except (OSError, ValueError):
        return []


def workbook_items(path):
    try:
        rows = read_xlsx(path)
    except (zipfile.BadZipFile, ValueError, KeyError, IndexError, TypeError, RuntimeError, ET.ParseError) as exc:
        raise ValueError("Choose a readable, unencrypted .xlsx workbook.") from exc
    cols = {key: i for i, heading in enumerate(rows[0] if rows else [])
            if (key := COLUMNS.get(re.sub(r"[^a-z]", "", heading.lower())))}
    if "name" not in cols:
        raise ValueError("The first row of the first worksheet needs a Name, Chemical Name or ChemName column.")
    owner = _owner(os.path.basename(path))
    items = []
    for r in rows[1:]:
        item = {k: (r[i].strip() if i < len(r) else "") for k, i in cols.items()}
        if item["name"]:
            item["group"] = owner
            _index(item)
            items.append(item)
    if not items:
        raise ValueError("Enter at least one chemical name below the column headings.")
    return items


def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def source(folder):
    """What the search reads: spreadsheet exports, not a live stock system."""
    if not folder or not os.path.isdir(folder):
        return {"files": 0, "newest": ""}
    files = [f for f in os.listdir(folder) if f.lower().endswith(".xlsx") and not f.startswith("~$")]
    newest = max([os.path.getmtime(os.path.join(folder, f)) for f in files] or [0])
    return {"files": len(files), "newest": datetime.date.fromtimestamp(newest).isoformat() if newest else ""}



_IGNORE = re.compile(r"""[\s,\-‐‑–'"′″‘’()\[\]{}]+""")
_CAS = re.compile(r"\d{2,7}-\d{2}-\d")


def normal(text):
    return _IGNORE.sub("", text.casefold())


def _index(item):
    n = item["_name"] = normal(item["name"])
    fields = [n] + [normal(item.get(k, "")) for k in ("product", "barcode", "formula")]
    item["_other"] = "\0".join(fields)
    item["_key"] = item["_other"] + "\0" + normal(item.get("cas", ""))
    item["_words"] = frozenset(re.findall(r"[a-z]+|\d+", item["name"].casefold()))
    item["_tie"] = (not (_num(item.get("remaining")) > 0), len(item["name"]), item["name"])
    item["_group"] = item["group"].casefold()


_ALIAS_FILE = Path(__file__).parent / "data/aliases.yaml"


@lru_cache(maxsize=1)
def _aliases(path, stamp):
    data = yamlio.load(path.read_text(encoding="utf-8"))
    aliases, by_name = {}, {}
    if not isinstance(data, dict):
        return aliases
    for short, row in data.items():
        if not isinstance(short, str) or not short.strip() or not isinstance(row, dict):
            continue
        cas, names, also = row.get("cas"), row.get("names"), row.get("also", [])
        if not (isinstance(cas, str) and _CAS.fullmatch(cas) and isinstance(names, list)
                and isinstance(also, list) and all(isinstance(n, str) and n.strip() for n in names + also)):
            continue
        entry = cas, tuple(names)
        for spelling in [short, *also]:
            aliases[_alias_key(spelling)] = entry
        for name in names:
            by_name.setdefault(_alias_key(name), entry)
    # A full name in the table gives its CAS number too; an abbreviation wins a clash.
    for name, entry in by_name.items():
        aliases.setdefault(name, entry)
    return aliases


def _alias_key(text):
    """Records write Dess–Martin with any of several dashes."""
    return re.sub(r"[‐‑–—]", "-", text.strip().casefold())


def aliases():
    return _aliases(_ALIAS_FILE, _ALIAS_FILE.stat().st_mtime_ns)


def _forms(name):
    yield name
    bare = name
    if name.endswith(")"):
        depth = 0
        for i in range(len(name) - 1, -1, -1):
            depth += (name[i] == ")") - (name[i] == "(")
            if depth == 0:
                bare = name[:i].rstrip()
                if bare:
                    yield bare
                break
    # A list of alternative chemicals does not identify a single bottle.
    if ", " in bare and not re.search(r"/|\bor\b", bare, re.I):
        yield bare.split(", ", 1)[0]


def locate_material(folder, own_group, material, *, stock=None):
    """Resolve one charge against the indexes shared by this inventory snapshot."""
    stock = _stock(folder) if stock is None else stock
    if not stock.items:
        return []
    own = (own_group or "").strip().casefold()
    cas = str(material.get("cas") or "").strip()
    explicit = cas if _CAS.fullmatch(cas) else ""
    table = aliases()
    for form in _forms(str(material.get("name") or "").strip()):
        alias_cas, names = table.get(_alias_key(form), ("", ()))
        query = explicit or alias_cas
        hits = stock.by_cas.get(query)
        basis = "CAS"
        if not hits:
            basis, query = "name", form
            named = {id(row): row for n in (form, *names) for row in stock.by_name.get(n.casefold(), ())}
            hits = list(named.values())
            numbers = {row.get("cas", "") for row in hits}
            if len(numbers) == 1:
                shared = numbers.pop()
                if _CAS.fullmatch(shared):
                    hits, query = stock.by_cas[shared], shared
        if hits:
            results = []
            for row in hits:
                try:
                    remaining = float(row.get("remaining"))
                except (TypeError, ValueError):
                    remaining = None
                same_group = bool(own and own in row["_group"])
                result = {k: v for k, v in row.items() if not k.startswith("_")}
                result.update(basis=basis, empty=remaining == 0, own_group=same_group, query=query)
                rank = (result["empty"], not same_group, not (remaining is not None and remaining > 0),
                        row.get("location", "").casefold(), row["name"].casefold(), row.get("barcode", ""))
                results.append((rank, result))
            return [result for _, result in sorted(results, key=lambda pair: pair[0])]
    return []


def record_locations(folder, own_group, materials):
    stock = _stock(folder)
    if not stock.items:
        return {}
    return {m["id"]: locate_material(folder, own_group, m, stock=stock) for m in materials
            if m.get("id") and not str(m["id"]).startswith("P") and not m.get("bottle")}


def _highlights(name, terms):
    folded, positions = [], []
    for i, c in enumerate(name):
        for ch in normal(c):
            folded.append(ch)
            positions.append(i)
    key = "".join(folded)
    spans = []
    for term in terms:
        for m in re.finditer(re.escape(term), key):
            spans.append((positions[m.start()], positions[m.end() - 1] + 1))
    merged = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged


def search(folder, query, own_group="", limit=60):
    src = source(folder)
    q = normal(query.strip())
    if not q:
        return {"total": 0, "items": [], "source": src}
    table = aliases()
    alias_cas, names = table.get(query.strip().casefold(), ("", ()))
    # Keep punctuated abbreviations intact before expanding each search word.
    tokens = []
    for word in query.casefold().split():
        tokens.extend([word] if word in table else re.split(r"[,‐‑–-]+", word))
    alternatives = [(normal(w), *(normal(n) for n in table.get(w, ("", ()))[1])) for w in tokens if normal(w)]
    exact = {q, *(normal(n) for n in names)}
    terms = {w for group in alternatives for w in group}
    single = next(iter(terms)) if len(terms) == 1 else None
    own = own_group.casefold()
    cas = bool(_CAS.fullmatch(query.strip()))
    hits, formula_cas = [], {}
    for it in load(folder):
        if "_name" not in it:
            _index(it)
        name = it["_name"]
        if cas and it.get("cas") == query.strip():
            rank = 0
        elif alias_cas and it.get("cas") == alias_cas:
            rank = 1
        elif cas:
            if q not in it["_other"]:
                continue
            rank = 1 if name == q else 4
        else:
            if single:
                if single not in it["_key"]:
                    continue
            elif not all(any(w in it["_key"] for w in options) for options in alternatives):
                continue
            if name in exact:
                rank = 1
            elif any(name.startswith(w) for w in exact) and (len(alternatives) > 1 or any(w in it["_words"] for w in exact)):
                rank = 2
            elif all(any(w in it["_words"] for w in options) for options in alternatives):
                rank = 3
            else:
                rank = 4
        hits.append(((rank, bool(own and own not in it["_group"]), it["_tie"]), it))
        if it.get("formula") and it.get("cas"):
            formula_cas.setdefault(it["formula"], set()).add(it["cas"])
    hits.sort(key=lambda hit: hit[0])
    out = []
    for key, it in hits[:limit]:
        row = {k: v for k, v in it.items() if not k.startswith("_")}
        row["match"] = ("CAS", "exact", "name", "word", "part")[key[0]]
        row["highlights"] = _highlights(it["name"], [q] if cas else terms)
        cas_numbers = formula_cas.get(it.get("formula"), ())
        if it.get("cas") and len(cas_numbers) > 1:
            row["same_formula"] = sorted(cas_numbers)
        for k in ("remaining", "size"):
            if row.get(k):
                row[k] = "%g" % _num(row[k])
        out.append(row)
    return {"total": len(hits), "items": out, "source": src}
