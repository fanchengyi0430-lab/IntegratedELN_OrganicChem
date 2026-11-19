"""Explicit, single-compound PubChem requests and project-local reference records."""
import datetime
import http.client
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from urllib import error, parse, request

from . import chem

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/"
HEADINGS = ("Boiling Point", "Melting Point", "Density")
PROPERTIES = "MolecularFormula,MolecularWeight,IUPACName,SMILES,InChIKey,Title"
KEY = re.compile(r"[A-Z]{14}-[A-Z]{10}-[A-Z]")
OFF = "Reference look-up is off. See Help under PubChem look-up."


class LookupError(ValueError):
    pass


class NoMatch(LookupError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(url):
    parts = parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "pubchem.ncbi.nlm.nih.gov":
        raise LookupError("Reference requests must use PubChem over HTTPS.")
    req = request.Request(url, headers={"User-Agent": "nbapp-notebook", "Accept": "application/json"})
    with request.build_opener(_NoRedirect()).open(req, timeout=10) as response:
        return json.load(response)


class RateLimit:
    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.next_request = 0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            remaining = self.next_request - self.clock()
            if remaining > 0:
                self.sleep(remaining)
            self.next_request = self.clock() + 0.201


_LIMIT = RateLimit()
_NUM = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_TEMP_UNIT = r"(?:°\s*|deg(?:ree)?s?\.?\s*)?(?:C(?:elsius)?|F(?:ahrenheit)?|K(?:elvin)?)\b"
_TEMP = re.compile(r"^\s*(" + _NUM + r")\s*(?:(?:(" + _TEMP_UNIT + r")\s*)?"
                   r"(?:to\b|[-–—])\s*(" + _NUM + r")\s*)?(" + _TEMP_UNIT + r")", re.I)
_PRESSURE = re.compile(r"(" + _NUM + r")\s*\[?\s*(mm\s*Hg|torr|atm|kPa|hPa|MPa|Pa|mbar|bar|psi)\b\s*\]?", re.I)
_ATM = {"mmhg": 760, "torr": 760, "atm": 1, "kpa": 101.325, "hpa": 1013.25,
        "pa": 101325, "mpa": 0.101325, "bar": 1.01325, "mbar": 1013.25, "psi": 14.696}
_DENSITY_UNIT = r"(?:g\s*/\s*(?:ml|cm[³3]|cu\.?\s*cm|cc|l)|kg\s*/\s*m[³3]|mg\s*/\s*ml)\b"
# PubChem's sources write "1.4788 g/cu cm at 25 °C" and "Density (at 20 °C): 1.48 g/ml". A figure with no unit is a
# relative density and stays unparsed.
_DENSITY = re.compile(r"^\s*(?:density\s*(?:\(\s*at\s[^)]{1,24}\))?\s*:\s*)?(" + _NUM + r")\s*(" + _DENSITY_UNIT + r")", re.I)


def _to_c(number, unit):
    unit = re.sub(r"^(?:°\s*|deg(?:ree)?s?\.?\s*)", "", unit, flags=re.I).lower()
    value = float(number)
    if unit.startswith("f"):
        return (value - 32) * 5 / 9
    return value - 273.15 if unit.startswith("k") else value


def parse_candidate(heading, text):
    """Return canonical units only for unambiguous values. Keep all original texts separately."""
    s = text.replace("−", "-").replace("℃", "°C").replace("℉", "°F")
    if heading == "Density":
        m = _DENSITY.match(s)
        if (m and float(m[1]) > 0 and not re.search(_DENSITY_UNIT, s[m.end():], re.I)
                and not re.match(r"\s*(?:[-–—±]|\bto\b|\bor\b)", s[m.end():], re.I)):
            unit = re.sub(r"[\s.]", "", m[2]).lower()
            return float(m[1]) / (1000 if unit in ("g/l", "kg/m³", "kg/m3", "mg/ml") else 1), "g/mL"
        return None, None
    m = _TEMP.match(s)
    if not m or re.search(r"decomp|sublim|vacuum|reduced pressure|less than|greater than", s, re.I):
        return None, None
    tail = s[m.end():]
    # Remove explicit pressures before removing citations, since a pressure may be parenthesised.
    for p in _PRESSURE.finditer(tail):
        standard = _ATM[re.sub(r"\s", "", p[2]).lower()]
        if abs(float(p[1]) / standard - 1) > 0.02:
            return None, None
    tail = _PRESSURE.sub(" ATM ", tail)
    tail = re.sub(r"(?:@|\bat\b)?\s*(?:ATM\b|atmospheric pressure\b|standard pressure\b)", "", tail, flags=re.I)
    # Only allow source citations and punctuation after the value and pressure.
    tail = re.sub(r"\((?!at\b|under\b|pressure\b)[A-Za-z][A-Za-z .&'/-]*(?:,\s*\d{4}[a-z]?)?\)", "", tail, flags=re.I)
    if tail.strip(" .,;()"):
        return None, None
    value = _to_c(m[1], m[2] or m[4])
    if m[3]:
        value = (value + _to_c(m[3], m[4])) / 2
    return round(value, 6), "°C"


def view_candidates(document, heading):
    record = document.get("Record", {})
    refs = {r.get("ReferenceNumber"): r for r in record.get("Reference", [])}
    rows = []

    def visit(section, inside=False):
        inside = inside or section.get("TOCHeading") == heading
        information = section.get("Information", []) if inside else ()
        for info in information:
            ref = refs.get(info.get("ReferenceNumber"), {})
            source = ref.get("SourceName") or "Source not recorded"
            licence = ref.get("LicenseNote") or ref.get("LicenseURL") or ""
            value = info.get("Value", {})
            unit = value.get("Unit", "")
            texts = [item["String"] for item in value.get("StringWithMarkup", []) if item.get("String")]
            texts.extend(("%s %s" % (n, unit)).strip() for n in value.get("Number", []))
            for text in texts:
                number, canonical = parse_candidate(heading, text)
                rows.append(dict(text=text, value=number, unit=canonical, source=source, licence=licence))
        for child in section.get("Section", []):
            visit(child, inside)

    visit(record)
    return rows


def check_query(query):
    if not isinstance(query, str) or not 0 < len(query.strip()) <= 256 or query.strip() in (".", ".."):
        raise LookupError("Enter one compound name or CAS number (up to 256 characters).")
    return query.strip()


class PubChem:
    def __init__(self, fetcher=fetch_json, limiter=None):
        self.fetcher = fetcher
        self.limiter = limiter or _LIMIT

    def _get(self, url):
        self.limiter.wait()
        try:
            doc = self.fetcher(url)
        except error.HTTPError as exc:
            if exc.fp is not None:
                exc.close()
            if exc.code == 404:
                raise NoMatch("No PubChem match.") from exc
            raise LookupError("PubChem returned HTTP %d. Try again later." % exc.code) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LookupError("PubChem timed out. Try again later.") from exc
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                raise LookupError("PubChem timed out. Try again later.") from exc
            raise LookupError("Could not read the PubChem response. Check the connection and try again.") from exc
        if not isinstance(doc, dict) or "Fault" in doc:
            raise LookupError("PubChem could not complete this request.")
        return doc

    def identity(self, query, *, by_key=False):
        if by_key:
            check_key(query)
            namespace = "inchikey"
        else:
            query = check_query(query)
            namespace = "name"
        url = BASE + "pug/compound/%s/%s/property/%s/JSON" % (namespace, parse.quote(query, safe=""), PROPERTIES)
        table = self._get(url).get("PropertyTable")
        rows = table.get("Properties") if isinstance(table, dict) else None
        if not isinstance(rows, list):
            raise LookupError("PubChem returned an incomplete identity.")
        if not rows:
            raise NoMatch("No PubChem match.")
        for row in rows:
            if not isinstance(row, dict) or type(row.get("CID")) is not int or row["CID"] < 1:
                raise LookupError("PubChem returned an invalid compound ID.")
        if len(rows) > 1:
            raise LookupError("Several PubChem matches (%s). Try a more specific name or CAS number."
                              % ", ".join("CID %d" % row["CID"] for row in rows))
        if by_key and rows[0].get("InChIKey") != query:
            raise LookupError("PubChem returned a different or missing InChIKey.")
        return rows[0], url

    def candidates(self, cid, heading):
        url = BASE + "pug_view/data/compound/%d/JSON?" % cid + parse.urlencode({"heading": heading})
        try:
            document = self._get(url)
        except NoMatch:
            return [], url
        if "Record" not in document:
            raise LookupError("PubChem returned an incomplete property record.")
        return view_candidates(document, heading), url


def atomic_text(path, text):
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False)
    try:
        with tmp:
            tmp.write(text)
        os.replace(tmp.name, path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _cached(folder, query):
    index = folder / "index.sqlite3"
    if not index.is_file():
        return None
    with closing(sqlite3.connect(index)) as db:
        # A concurrent first writer may still be creating the index.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='queries'").fetchone():
            return None
        hit = db.execute("SELECT cid FROM queries WHERE query=?", (query,)).fetchone()
        if hit:
            try:
                return json.loads((folder / ("%d.json" % hit[0])).read_text(encoding="utf-8"))
            except FileNotFoundError:
                pass
    return None


def _cache(folder, result):
    folder.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(folder / "index.sqlite3")) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS queries (query TEXT PRIMARY KEY, cid INTEGER NOT NULL)")
        # Serialize publishers across the browser server and CLI. Publish the CID before its index entry.
        db.execute("INSERT OR REPLACE INTO queries VALUES (?, ?)", (result["query"], result["cid"]))
        atomic_text(folder / ("%d.json" % result["cid"]), json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def cached_cas_identities(root):
    """Read the local CAS-to-identity map once for a bottle search. Never fetch."""
    folder = Path(root) / "reference_cache" / "pubchem"
    index = folder / "index.sqlite3"
    identities = {}
    if not index.is_file():
        return identities
    with closing(sqlite3.connect(index)) as db:
        tables = {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "queries" in tables:
            for query, cid in db.execute("SELECT query, cid FROM queries"):
                if re.fullmatch(r"\d{2,7}-\d{2}-\d", query):
                    try:
                        identity = json.loads((folder / ("%d.json" % cid)).read_text(encoding="utf-8"))["identity"]
                    except FileNotFoundError:
                        continue
                    identities[query] = identity
        if "structure_keys" in tables:
            for payload, in db.execute("SELECT result FROM structure_keys"):
                result = json.loads(payload)
                for cas in result.get("cas_numbers", []):
                    identities.setdefault(cas, result["identity"])
    return identities


def check_key(key):
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise LookupError("Invalid InChIKey.")


def lookup_key(root, key, refresh=False, client=None, *, include_cas=False):
    """Cache the key's identity or dated 404 independently of the full CID property record."""
    check_key(key)
    folder = Path(root) / "reference_cache" / "pubchem"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(folder / "index.sqlite3")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS structure_keys (key TEXT PRIMARY KEY, result TEXT NOT NULL)")
            hit = db.execute("SELECT result FROM structure_keys WHERE key=?", (key,)).fetchone()
            if hit and not refresh:
                result = json.loads(hit[0])
            else:
                try:
                    identity, url = (client or PubChem()).identity(key, by_key=True)
                    result = dict(identity=identity, url=url)
                except NoMatch:
                    result = dict(identity=None)
                result["retrieved"] = datetime.date.today().isoformat()
                db.execute("INSERT OR REPLACE INTO structure_keys VALUES (?, ?)", (key, json.dumps(result)))
            ident = result["identity"]
            # The name client records CAS queries in its query-to-CID index.
            if ident and db.execute("SELECT 1 FROM sqlite_master WHERE name='queries'").fetchone():
                aliases = [q for q, in db.execute("SELECT query FROM queries WHERE cid=?", (ident["CID"],))
                           if re.fullmatch(r"\d{2,7}-\d{2}-\d", q)]
                if len(aliases) == 1:
                    result["cas"] = aliases[0]
            if include_cas and ident and not result.get("cas") and "cas_numbers" not in result:
                rows, url = (client or PubChem()).candidates(ident["CID"], "CAS")
                result["cas_numbers"] = sorted({r["text"] for r in rows if re.fullmatch(r"\d{2,7}-\d{2}-\d", r["text"])})
                result["cas_url"] = url
                db.execute("UPDATE structure_keys SET result=? WHERE key=?", (json.dumps(result), key))
            return result
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        raise LookupError("Could not read or write the project reference cache.") from exc


def lookup(root, provider, query, refresh=False, client=None, *, by_key=False):
    if provider != "pubchem":
        raise LookupError(OFF)
    if by_key:
        check_key(query)
    else:
        query = check_query(query)
    folder = Path(root) / "reference_cache" / "pubchem"
    try:
        key_result = lookup_key(root, query, refresh, client) if by_key else None
        if by_key and not key_result["identity"]:
            raise NoMatch("No PubChem match.")
        record = None if refresh else _cached(folder, query)
        if by_key and record and record.get("identity", {}).get("InChIKey") != query:
            record = None
        cached = record is not None
        if not cached:
            client = client or PubChem()
            identity, url = (key_result["identity"], key_result["url"]) if by_key else client.identity(query)
            cid = identity["CID"]
            urls, candidates = {"identity": url}, {}
            for heading in HEADINGS:
                candidates[heading], urls[heading] = client.candidates(cid, heading)
            record = dict(query=query, cid=cid, identity=identity, candidates=candidates, urls=urls,
                          retrieved=datetime.date.today().isoformat())
            _cache(folder, record)
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        raise LookupError("Could not read or write the project reference cache: %s" % exc) from exc
    if cached:  # the cache keeps each source's wording, so a later fix to the parser reaches old entries too
        for heading, rows in record.get("candidates", {}).items():
            for row in rows:
                row["value"], row["unit"] = parse_candidate(heading, row.get("text", ""))
    identity = record["identity"]
    try:
        weight = chem.mol_weight(identity.get("MolecularFormula"))
    except ValueError:
        weight = None
    try:
        difference = round(abs(weight - float(identity["MolecularWeight"])), 9) if weight is not None else None
    except (KeyError, ValueError, TypeError):
        difference = None
    return dict(record, cached=cached, query=query, formula_mw=weight, mw_warning=difference is not None and difference > 0.05,
                cas=key_result.get("cas") if by_key else query if re.fullmatch(r"\d{2,7}-\d{2}-\d", query) else None)
