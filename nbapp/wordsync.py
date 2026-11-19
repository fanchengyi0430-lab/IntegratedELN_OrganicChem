"""Read what the researcher typed into the generated Word notebook's fields.

The notebook's review and bench fields are content controls tagged review_expNN or expNN_*.
A field counts as filled when Word no longer marks it as showing its placeholder.
"""
import html
import json
import os
import re
import zipfile

_SDT = re.compile(r"<w:sdt>(.*?)</w:sdt>", re.S)
_TAG = re.compile(r'<w:tag w:val="([^"]*)"')
_ALIAS = re.compile(r'<w:alias w:val="([^"]*)"')
_PARA = re.compile(r"<w:p[ >].*?</w:p>", re.S)
_TEXT = re.compile(r"<w:t(?: [^>]*)?>([^<]*)</w:t>|<w:br/>|<w:tab/>")


def _plain(xml):
    paras = _PARA.findall(xml) or [xml]
    lines = []
    for p in paras:
        parts = []
        for m in _TEXT.finditer(p):
            parts.append(html.unescape(m.group(1)) if m.group(1) is not None else ("\n" if "br" in m.group(0) else " "))
        lines.append("".join(parts))
    return "\n".join(lines).strip()


def read_fields(docx_path):
    """{tag: {"text", "alias", "exp"}} for every filled field in the notebook."""
    with zipfile.ZipFile(docx_path) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    out = {}
    for m in _SDT.finditer(doc):
        block = m.group(1)
        tag = _TAG.search(block)
        if not tag or "<w:showingPlcHdr/>" in block.split("<w:sdtContent>")[0]:
            continue
        name = html.unescape(tag.group(1))
        em = re.match(r"^(?:review_exp|exp)(\d+)", name)
        if not em:
            continue
        content = block.split("<w:sdtContent>", 1)[1] if "<w:sdtContent>" in block else ""
        text = _plain(content)
        if not text or re.match(r"^\[.*\]$", text, re.S):
            continue
        alias = _ALIAS.search(block)
        out[name] = {"text": text, "alias": html.unescape(alias.group(1)) if alias else name, "exp": "EXP-%03d" % int(em.group(1))}
    return out


def write_baseline(case):
    """Remember what a build put into the Word fields, so later differences can be told apart:
    typed in Word since, or changed in the record since."""
    fields = {}
    for rec in case.all():
        fields.update(rec.get("entries") or {})
    os.makedirs(os.path.dirname(case.layout.word_state), exist_ok=True)
    with open(case.layout.word_state, "w", encoding="utf-8") as fh:
        json.dump({"index_mtime": os.path.getmtime(case.layout.index), "fields": fields}, fh, ensure_ascii=False)


def _baseline(case):
    """Fields exported by the last build the app ran, or None when another build has run since."""
    try:
        with open(case.layout.word_state, encoding="utf-8") as fh:
            data = json.load(fh)
        if abs(data["index_mtime"] - os.path.getmtime(case.layout.index)) > 2:
            return None
        return data["fields"]
    except (OSError, ValueError, KeyError):
        return None


def pending(case):
    """Fields filled in Word whose text differs from the record's `entries`.

    kind 'new': typed in Word, record unchanged since the export. kind 'conflict': Word and record
    both differ from the export (or nothing is known about the export and the record has other text).
    Fields where Word still shows the exported text and only the record moved on are counted as
    'stale' and not offered for import."""
    if not case.has_build_script():
        return {"error": None, "items": [], "stale": 0}
    path = case.notebook_path()
    try:
        fields = read_fields(path)
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        return {"error": "Could not read the notebook file: %s" % e, "items": [], "stale": 0}
    base = _baseline(case)
    items, stale = [], 0
    ids = set(case.ids())
    for tag, f in sorted(fields.items()):
        if f["exp"] not in ids:
            continue
        rec, _ = case.read(f["exp"])
        current = (rec.get("entries") or {}).get(tag)
        if current == f["text"]:
            continue
        if base is not None:
            exported = base.get(tag)
            if exported == f["text"]:
                stale += 1
                continue
            kind = "new" if current == exported else "conflict"
        else:
            kind = "new" if current in (None, "") else "conflict"
        items.append({"tag": tag, "exp": f["exp"], "field": f["alias"], "word": f["text"], "record": current, "kind": kind})
    return {"error": None, "items": items, "stale": stale}


def apply(case, tags, by=""):
    """Copy the chosen Word fields into the records' `entries`."""
    todo = [it for it in pending(case)["items"] if it["tag"] in set(tags)]
    done = 0
    by_exp = {}
    for it in todo:
        by_exp.setdefault(it["exp"], []).append(it)
    for rid, items in by_exp.items():
        rec, meta = case.read(rid)
        entries = dict(rec.get("entries") or {})
        for it in items:
            entries[it["tag"]] = it["word"]
        rec["entries"] = entries
        res = case.write(rid, rec, expect_hash=meta["hash"], by=by, summary="imported %d field(s) typed in Word" % len(items), action="word-import")
        if res["changed"]:
            done += len(items)
    return {"imported": done}
