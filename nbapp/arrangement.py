"""Notebook arrangement rules and derived relationships. No record is modified here."""
from collections import defaultdict
from graphlib import TopologicalSorter
import re


def clean(data, ids):
    """Return the usable entries and a diagnostic for each invalid entry."""
    out = dict(groups=[], sequences=[], detached=[], references={})
    issues = []
    if not isinstance(data, dict):
        return out, ["arrangement.yaml must contain a map."]
    for key in data.keys() - out.keys():
        issues.append("Unknown arrangement entry %s." % key)

    def entries(key, kind):
        value = data.get(key, kind())
        if not isinstance(value, kind):
            issues.append("%s must be a %s." % (key, kind.__name__))
            return kind()
        return value

    def known(rid, where):
        if isinstance(rid, str) and rid in ids:
            return True
        issues.append("%s: unknown experiment %s." % (where, rid))
        return False

    def members(values, where, assigned):
        result = []
        if not isinstance(values, list):
            issues.append("%s must be a list." % where)
            return result
        for rid in values:
            if known(rid, where):
                if rid in assigned:
                    issues.append("%s: repeated membership for %s." % (where, rid))
                else:
                    result.append(rid)
                    assigned.add(rid)
        return result

    assigned = set()
    for key, field, prefix in (("groups", "members", "G"), ("sequences", "steps", "Q")):
        seen = set()
        for i, item in enumerate(entries(key, list)):
            where = "%s[%d]" % (key, i + 1)
            if not isinstance(item, dict):
                issues.append("%s must be a map." % where)
                continue
            gid = item.get("id")
            if not isinstance(gid, str) or not re.fullmatch(prefix + r"[1-9]\d*", gid) or gid in seen:
                issues.append("%s: invalid or repeated ID %s." % (where, gid))
                continue
            seen.add(gid)
            title = item.get("title")
            if not isinstance(title, str) or not title.strip():
                issues.append("%s needs a title." % gid)
                continue
            for extra in item.keys() - {"id", "title", field}:
                issues.append("%s: unknown field %s." % (gid, extra))
            values = members(item.get(field), gid + "." + field, assigned if key == "groups" else set())
            if key == "sequences" and len(values) < 2:
                issues.append("%s needs at least two steps." % gid)
                continue
            out[key].append({"id": gid, "title": title.strip(), field: values})
    out["detached"] = members(entries("detached", list), "detached", set())
    for rid, ref in entries("references", dict).items():
        if known(rid, "references") and known(ref, "references." + rid):
            if ref == rid:
                issues.append("references.%s must name another experiment." % rid)
            else:
                out["references"][rid] = ref
    return out, issues


def earlier(a, b):
    dates = [str(row.get("started") or "")[:10] for row in (a, b)]
    if all(dates) and dates[0] != dates[1]:
        return dates[0] < dates[1]
    return a["n"] < b["n"]


def best_row(rows):
    winner = None
    for row in rows:
        if not row["best"]:
            continue
        score = row["best"]["rank"]
        if winner is None or score > winner["best"]["rank"] or (
                score == winner["best"]["rank"] and earlier(winner, row)):
            winner = row
    return winner


def parents(rows, data):
    groups = [dict(g, automatic=False) for g in data["groups"]]
    taken = set(data["detached"]).union(*(g["members"] for g in groups))
    repeats = defaultdict(list)
    for row in rows:
        if row["step"] and row["id"] not in taken:
            repeats[row["step"]].append(row)
    for step, group in repeats.items():
        if len(group) >= 2:
            first = group[0]
            for member in group[1:]:
                if earlier(member, first):
                    first = member
            title = first["reaction_title"] or first["title"]
            groups.append(dict(id=step, title=title, members=[r["id"] for r in group], automatic=True))
    by_id = {row["id"]: row for row in rows}
    for group in groups:
        by_metric = defaultdict(list)
        for rid in group["members"]:
            row = by_id[rid]
            if row["best"]:
                by_metric[row["metric_kind"]].append(row)
        group["best"] = {kind: best_row(candidates)["id"] for kind, candidates in by_metric.items()}
    return groups


def _reachable(start, edges, remaining):
    found, pending = set(), [start]
    while pending:
        node = pending.pop()
        if node in remaining and node not in found:
            found.add(node)
            pending.extend(edges[node] - found)
    return found


def _stages(nodes, previous, following, order):
    # Kosaraju's two traversals collapse cycles before ordering stages. Both
    # traversals are iterative so a long synthetic route needs no recursion.
    seen, finished = set(), []
    for root in nodes:
        pending = [(root, False)]
        while pending:
            node, leaving = pending.pop()
            if leaving:
                finished.append(node)
            elif node not in seen:
                seen.add(node)
                pending.append((node, True))
                pending.extend((child, False) for child in following[node] if child not in seen)

    remaining, components, owner = set(nodes), {}, {}
    for root in reversed(finished):
        if root in remaining:
            component = _reachable(root, previous, remaining)
            remaining -= component
            components[root] = component
            owner.update(dict.fromkeys(component, root))

    sorter = TopologicalSorter()
    for root, component in components.items():
        dependencies = {owner[p] for n in component for p in previous[n] if owner[p] != root}
        sorter.add(root, *dependencies)
    sorter.prepare()
    while sorter.is_active():
        ready = sorter.get_ready()
        yield sorted((n for root in ready for n in components[root]), key=order)
        sorter.done(*ready)


def sequences(rows, data):
    manual = [dict(id=q["id"], title=q["title"], stages=[[s] for s in q["steps"]], automatic=False)
              for q in data["sequences"]]
    number = {r["id"]: r["n"] for r in rows}
    previous = {r["id"]: {m["id"] for m in r["previous"]} for r in rows}
    following = {r["id"]: {m["id"] for m in r["next"]} for r in rows}
    edges = {n: previous[n] | following[n] for n in number}
    remaining = {n for n in edges if edges[n]}
    result = manual[:]
    for rid in number:
        if rid not in remaining:
            continue
        nodes = _reachable(rid, edges, remaining)
        remaining -= nodes
        if any(nodes.issubset(q["steps"]) for q in data["sequences"]):
            continue
        stages = list(_stages(nodes, previous, following, number.get))
        result.append(dict(id="auto-" + rid, title="Sequence from Exp %d" % number[stages[0][0]],
                           stages=stages, automatic=True))
    return result


def record_context(rid, rows, state, groups, routes):
    by_id = {r["id"]: r for r in rows}
    current = by_id[rid]
    parent = next((g for g in groups if rid in g["members"]), None)
    chosen = state["data"]["references"].get(rid)
    eligible = [r for r in rows if r["metric_kind"] == current["metric_kind"] and earlier(r, current)
                and (current["step"] and r["step"] == current["step"] or parent and r["id"] in parent["members"])]
    ref = by_id.get(chosen) if chosen else best_row(eligible)
    reference = None
    if ref is not None and not current["computational"]:
        reference = dict(id=ref["id"], title=ref["title"], chosen=bool(chosen),
                         best=ref["best"] if ref["metric_kind"] == current["metric_kind"] else None)
    return dict(parent=parent, sequences=[q for q in routes if any(rid in stage for stage in q["stages"])][:3],
                reference=reference, arrangement_hash=state["hash"])
