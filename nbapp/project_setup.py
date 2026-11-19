"""Install the bundled agent rules and teaching notebook into a project."""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from . import store, yamlio

APP = Path(__file__).resolve().parent
DATA = APP / "data"


def rules_text(root):
    root = Path(root).resolve()
    if (root / "nbapp" / "run.py").is_file():
        python = r".\nbapp\runtime\python.exe" if (root / "nbapp/runtime/python.exe").is_file() else "py -3"
        command = python + r" nbapp\run.py"
    else:
        runtime = APP / "runtime/python.exe"
        python = '& "%s"' % runtime if runtime.is_file() else "py -3"
        command = '%s "%s" --root "%s"' % (python, APP / "run.py", root)
    return (DATA / "AGENTS.template.md").read_text(encoding="utf-8").replace("{{RUN}}", command)


def write_rules(root):
    results = []
    for name, content in (("AGENTS.md", rules_text(root)), ("CLAUDE.md", "@AGENTS.md\n")):
        path = Path(root) / name
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(content)
        except FileExistsError:
            if not path.is_file():
                raise store.StoreError("%s is not a file." % path)
            results.append("Found " + name)
        else:
            results.append("Wrote " + name)
    return results


@contextmanager
def _new_case(project, name, title="", researcher=""):
    # Publish the finished case together so a failed setup or build can be retried.
    with tempfile.TemporaryDirectory(prefix=".notebook-", dir=project.root) as tmp:
        staged = store.Project(tmp).create_case(name, title, researcher)
        destination = Path(project.root) / staged.name
        if destination.exists():
            raise store.StoreError("A folder or file named '%s' already exists." % name)
        yield staged
        write_rules(project.root)
        try:
            staged.layout.root.rename(destination)
        except OSError:
            if destination.exists():
                raise store.StoreError("A folder or file named '%s' already exists." % name)
            raise


def start(project, name, title="", researcher=""):
    with _new_case(project, name, title, researcher):
        pass
    return project.case(name)


def demo(project):
    source = DATA / "demo"

    def load(name):
        return yamlio.load((source / name).read_text(encoding="utf-8"))

    settings = load("case.yaml")
    name = settings["title"]
    with _new_case(project, name, researcher=settings["researcher"]) as staged:
        store._write_atomic(staged.layout.settings, yamlio.dump({**staged.cfg(), **settings}))
        for path in sorted(source.glob("EXP-*.yaml")):
            record = load(path.name)
            result = staged.create(record, by="demo", via="demo")
            for attachment in record.get("attachments", []):
                # Import the original attachment, retaining its shipped provenance.
                asset = source / Path(attachment["path"]).name
                saved = staged.attach(result["id"], asset, attachment["kind"], by="demo", via="demo")
                if saved["attachment"] != attachment:
                    raise store.StoreError("Demo attachment differs from its record: %s" % asset.name)
        staged.save_followups(**load("followups.yaml"))
        built = staged.build(via="demo")
        if not built["ok"]:
            raise store.StoreError(built["message"])
    return project.case(name)
