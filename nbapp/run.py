"""Start the notebook app or work with a project from the command line."""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from nbapp import attachments, project_setup, reference, server, store, structure_files, yamlio  # noqa: E402


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise store.StoreError(message)


def parser():
    common = Parser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--root", help="project folder (default: the folder that contains nbapp)")
    common.add_argument("--port", type=int)
    common.add_argument("--no-browser", action="store_true")
    common.add_argument("--lookup", choices=("pubchem", "off"), help="override reference look-up for this run")
    ap = Parser(description="Integrated Notebook for Organic Chemistry", parents=[common])
    sub = ap.add_subparsers(dest="command")
    for name in ("serve", "validate", "build", "cases", "ids", "show", "save", "new", "init", "attach", "lookup", "rules", "demo"):
        cmd = sub.add_parser(name, parents=[common])
        if name == "rules":
            cmd.add_argument("--print", action="store_true", dest="print_rules")
        if name in ("validate", "build"):
            cmd.add_argument("case", nargs="?")
        if name in ("ids", "show", "save", "new", "init", "attach"):
            cmd.add_argument("case")
        if name in ("show", "save", "attach"):
            cmd.add_argument("id")
        if name == "show":
            cmd.add_argument("--json", action="store_true")
        if name == "lookup":
            cmd.add_argument("query")
            cmd.add_argument("--json", action="store_true")
            cmd.add_argument("--refresh", action="store_true")
        if name in ("save", "new"):
            cmd.add_argument("--file", required=True)
        if name in ("save", "new", "attach"):
            cmd.add_argument("--by", required=True)
        if name == "save":
            cmd.add_argument("--expect")
            cmd.add_argument("--summary", default="")
            cmd.add_argument("--dry-run", action="store_true")
        if name == "init":
            cmd.add_argument("--title", default="")
            cmd.add_argument("--researcher", default="")
        if name == "attach":
            cmd.add_argument("path")
            cmd.add_argument("--kind", required=True, choices=attachments.KINDS)
            cmd.add_argument("--sample")
            cmd.add_argument("--run")
            cmd.add_argument("--note", default="")
        if name == "validate":
            cmd.add_argument("--deep", action="store_true")
    return ap


def _record_file(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            rec = json.load(fh) if path.lower().endswith(".json") else yamlio.load(fh.read())
    except (ValueError, yamlio.YAMLError) as e:
        raise store.StoreError("Invalid record file: %s" % e)
    if not isinstance(rec, dict):
        raise store.StoreError("The file must contain a full record.")
    return rec


def _preview_value(value, row_key=None):
    if isinstance(value, dict):
        fields = ["%s: %s" % (k, v if k == "tier" and v in store.TIERS else _preview_value(v))
                  for k, v in value.items() if k != row_key]
        rendered = "{" + ", ".join(fields) + "}"
    else:
        rendered = repr(value)
    return rendered if len(rendered) <= 200 else rendered[:98] + " … " + rendered[-99:]


def _print_changes(changes):
    for i, change in enumerate(changes):
        old, new = change["old"], change["new"]
        key = change.get("row_key")
        if old is store.MISSING:
            detail = "added " + _preview_value(new, key)
            if key == "run" and "result" in new:
                basis = _preview_value(new.get("basis", ""))
                if "basis: " + basis not in detail:
                    detail += " (basis: %s)" % basis
        elif new is store.MISSING:
            detail = "removed " + _preview_value(old, key)
        else:
            detail = _preview_value(old) + " -> " + _preview_value(new)
        path = change["path"]
        if "basis" in change:
            basis_path = path.rsplit(".", 1)[0] + ".basis"
            if i + 1 == len(changes) or changes[i + 1]["path"] != basis_path:
                detail += " (basis: %s)" % _preview_value(change["basis"])
        print("%s: %s" % (path, detail))


def _run(args):
    args.root = getattr(args, "root", os.path.dirname(HERE))
    project = store.Project(args.root)
    command = args.command or "serve"
    if command == "serve":
        server.serve(args.root, port=getattr(args, "port", None), open_browser=not getattr(args, "no_browser", False),
                     lookup=getattr(args, "lookup", None))
        return 0
    if command == "lookup":
        provider = getattr(args, "lookup", server.load_config(args.root)["reference_lookup"])
        result = reference.lookup(args.root, provider, args.query, args.refresh)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("PubChem CID %d (%s %s)" % (result["cid"], "cached," if result["cached"] else "retrieved", result["retrieved"]))
            for key, value in result["identity"].items():
                print("%s: %s" % (key, value))
            print("Formula MW (notebook): %s" % result["formula_mw"])
            if result["mw_warning"]:
                print("Warning: PubChem and notebook molecular weights differ by more than 0.05.")
            for heading, candidates in result["candidates"].items():
                for row in candidates:
                    print("%s: %s (%s)" % (heading, row["text"], row["source"]))
        return 0
    if command == "cases":
        for name in project.case_names():
            print(name)
        return 0
    if command == "init":
        case = project_setup.start(project, args.case, title=args.title, researcher=args.researcher)
        print("Started " + case.name)
        return 0
    if command == "rules":
        if args.print_rules:
            print(project_setup.rules_text(project.root), end="")
        else:
            print(*project_setup.write_rules(project.root), sep="\n")
        return 0
    if command == "demo":
        case = project_setup.demo(project)
        print("Started " + case.name)
        print("Walk-through: Help > Demo walk-through (nbapp/DEMO.md)")
        return 0
    if command in ("ids", "show", "save", "new", "attach"):
        case = project.case(args.case)
        if command == "ids":
            for rid in case.ids():
                print(rid)
        elif command == "show":
            rec, meta = case.read(args.id)
            if args.json:
                print(json.dumps({"record": rec, "hash": meta["hash"]}, ensure_ascii=False, default=str))
            else:
                print("# hash: " + meta["hash"])
                print(yamlio.dump(rec), end="")
        elif command == "save":
            result = case.write(args.id, _record_file(args.file), expect_hash=args.expect, by=args.by,
                                summary=args.summary, via="cli", dry_run=args.dry_run, include_changes=True)
            for note in result["notes"]:
                print("%s: %s" % (note["level"], note["msg"]))
            _print_changes(result.get("changes", []))
            print(("Would save" if args.dry_run else "Saved") if result["changed"] else "Unchanged")
        elif command == "new":
            result = case.create(_record_file(args.file), by=args.by, via="cli")
            print(result["id"], result["hash"])
        else:
            result = case.attach(args.id, args.path, args.kind, sample=args.sample, run=args.run, by=args.by,
                                 note=args.note, via="cli")
            print("Attached" if result["changed"] else "Already attached")
        return 0
    names = [args.case] if args.case else project.case_names()
    failed = False
    for name in names:
        case = project.case(name)
        if command == "build":
            res = case.build(via="cli")
            message = res["message"] if res["ok"] else " ".join(res["message"].splitlines())
            print("%s: %s" % (name, message), file=sys.stdout if res["ok"] else sys.stderr)
            failed = failed or not res["ok"]
            continue
        for warning in case.arrangement()["warnings"]:
            print("%s  arrangement.yaml  warn  %s" % (name, warning))
        try:
            structure_files.library_rows(case)
        except store.StoreError as e:
            print("%s  compounds.yaml  error %s" % (name, e), file=sys.stderr)
            failed = True
        for rid in case.ids():
            try:
                rec, _ = case.read(rid)
                notes = case.validate(rec, rid, deep=args.deep)
            except store.StoreError as e:
                notes = [{"level": "error", "msg": str(e)}]
            for n in notes:
                print("%s  %s  %-5s %s" % (name, rid, n["level"], n["msg"]),
                      file=sys.stderr if n["level"] == "error" else sys.stdout)
                failed = failed or n["level"] == "error"
    return 1 if failed else 0


def main(argv=None):
    try:
        if sys.version_info < (3, 9):
            raise store.StoreError("Python 3.9 or newer is needed (this is %s)." % sys.version.split()[0])
        return _run(parser().parse_args(argv))
    except (store.StoreError, OSError, yamlio.YAMLError, ValueError) as e:
        print(" ".join(str(e).splitlines()), file=sys.stderr)
        if isinstance(e, store.Conflict):
            return 2
        if isinstance(e, (store.NotFound, FileNotFoundError, reference.NoMatch)):
            return 3
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
