"""Build and smoke-test the offline Windows x64 download from a distribution checkout."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

if __package__:
    from . import build_runtime, build_sketcher
else:
    import build_runtime
    import build_sketcher


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
APP = "Organic-Chemistry-Notebook"
ASSET = APP + "-Windows-x64.zip"

# Only these published source groups are read from the working tree. Glob pathspecs
# select tracked files, so a local inventory, notebook or scratch module stays local.
TRACKED_GROUPS = (
    "nbapp/*.py", "nbapp/*.md", "nbapp/static/*", "nbapp/vendor/yaml/*.py",
    "nbapp/data/demo/*.yaml", "nbapp/data/demo/edits/*.yaml",
)
APP_FILES = (
    "Start Notebook.bat", "README.md", "LICENSE",
    "docs/demo-experiment.png", "docs/demo-experiments.png",
    "nbapp/config.example.yaml", "nbapp/vendor/yaml/LICENSE",
    "nbapp/data/AGENTS.template.md", "nbapp/data/aliases.yaml", "nbapp/data/blank.cdxml",
    "nbapp/data/formula.json", "nbapp/data/hazards.yaml", "nbapp/data/solvents.yaml",
    "nbapp/data/demo/condensation.png", "nbapp/data/demo/inventory/Teaching inventory.xlsx",
    "nbapp/sketcher/LICENSE-ketcher.txt", "nbapp/sketcher/NOTICE-ketcher.txt",
    "nbapp/packaging/build_runtime.py", "nbapp/packaging/build_sketcher.py",
    "nbapp/packaging/setup_windows.ps1", "nbapp/packaging/windows_python.json",
)


def stage_app(folder):
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *[":(glob)" + p for p in TRACKED_GROUPS]], cwd=ROOT
    ).decode("utf-8").split("\0")
    for name in sorted(set(APP_FILES).union(filter(None, paths))):
        src = ROOT / name
        if src.resolve() != src:
            raise ValueError("Expected a regular distribution file at " + name)
        dest = folder / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    # A developer's active config can name a lab, an inventory or a researcher.
    shutil.copyfile(folder / "nbapp/config.example.yaml", folder / "nbapp/config.yaml")


SMOKE_TEST = """\
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from nbapp import inventory, runtime_info, structure
assert runtime_info.about()["packaged"], "Expected the embedded Python"
assert runtime_info.sketcher_info()["installed"], "Incomplete local Ketcher editor"
parsed = structure.parse("CCO")
assert parsed["molecules"][0]["inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", parsed["errors"]
folder = str(Path("nbapp/data/demo/inventory").resolve())
bottles = inventory.load(folder)
assert bottles and inventory.search(folder, bottles[0]["name"])["items"], "Missing teaching inventory"
print("Verified portable structure parsing, sketcher assets and inventory search.")
"""


def build(out, downloads, offline):
    if sys.platform != "win32":
        raise ValueError("Use Windows x64 to build and run the packaged interpreter.")
    if out.suffix.lower() != ".zip":
        raise ValueError("--out must name a .zip file.")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nb-release-") as work:
        staged = Path(work) / APP
        stage_app(staged)
        build_runtime.build(staged / "nbapp/runtime", downloads, build_runtime.PINS, offline=offline)
        build_sketcher.build(staged / "nbapp/sketcher", downloads, offline=offline)
        # Stage the ZIP beside its destination so a failed build leaves the previous ZIP usable.
        with tempfile.TemporaryDirectory(prefix=".release-", dir=out.parent) as pending:
            archive = Path(pending) / ASSET
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for path in sorted(staged.rglob("*")):
                    if path.is_file():
                        z.write(path, path.relative_to(staged.parent))
            unpacked = Path(work) / "Extracted copy"
            with zipfile.ZipFile(archive) as z:
                z.extractall(unpacked)
            app = unpacked / APP
            subprocess.run([str(app / "nbapp/runtime/python.exe"), "-B", "-c", SMOKE_TEST],
                           cwd=app, check=True, timeout=90)
            # Exercise the actual launcher against a disposable project without opening a browser.
            project = Path(work) / "Empty notebook"
            project.mkdir()
            subprocess.run([os.environ["COMSPEC"], "/d", "/c", "call", "Start Notebook.bat",
                            "--root", str(project), "cases"],
                           cwd=app, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           timeout=60, check=True)
            os.replace(archive, out)
    print("Windows download:", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / ASSET)
    parser.add_argument("--downloads", type=Path, default=HERE / "_downloads",
                        help="directory for the pinned upstream ZIP and wheel archives")
    parser.add_argument("--offline", action="store_true", help="use the existing archive cache")
    args = parser.parse_args()
    try:
        build(args.out.resolve(), args.downloads.resolve(), args.offline)
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + "\n")
