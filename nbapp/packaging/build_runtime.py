"""Build and verify the redistributable Windows notebook runtime."""
import argparse
import datetime
import hashlib
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

HERE = Path(__file__).resolve().parent
PINS = {
    "python": json.loads((HERE / "windows_python.json").read_text(encoding="utf-8")),
    "numpy": dict(version="2.5.4", filename="numpy-2.5.4-cp314-cp314-win_amd64.whl", size=12703552,
                  sha256="2ca144f15135b6212a5c47b1e2aeca6e412f102f95a2d5d88d8aec77eb255de3",
                  url="https://files.pythonhosted.org/packages/52/9a/e1e512ebc948d5b9dd33b08736760f0ebbed2848fd4eda1f553088a6dcee/numpy-2.5.4-cp314-cp314-win_amd64.whl"),
    "rdkit": dict(version="2026.9.1", filename="rdkit-2026.9.1-cp314-cp314-win_amd64.whl", size=25888564,
                  sha256="655cf6c4df7711254bb925b612af3d00f24f372e6461251f7db579fe9e1476ad",
                  url="https://files.pythonhosted.org/packages/c1/43/6ef1ba623b405f6201e98888ac69f195544ab3679c370df73b70e30e0676/rdkit-2026.9.1-cp314-cp314-win_amd64.whl"),
    "pillow": dict(version="12.3.0", filename="pillow-12.3.0-cp314-cp314-win_amd64.whl", size=7237707,
                   sha256="fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d",
                   url="https://files.pythonhosted.org/packages/f1/e0/492879f69d94f91f60fc8cd05ba03650e9520afebb2fb7aa12777d7c7f38/pillow-12.3.0-cp314-cp314-win_amd64.whl"),
    "openclatura": dict(version="0.4.4", filename="openclatura-0.4.4-py3-none-any.whl", size=690529,
                        sha256="98cc62fa67a5099ec4c2e921f72795ecd16c2f1e79b4c0bc9cd8c60991e4f57b",
                        url="https://files.pythonhosted.org/packages/f9/7c/8261c814b7b58ca338ced80caff8a6ff6def607ac4464b26e319027fae09/openclatura-0.4.4-py3-none-any.whl"),
}
PTH = "python314.zip\n.\nLib/site-packages\n../..\n"


def reserved(part):
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(part)
    return PureWindowsPath(part).is_reserved()


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify(path, pin):
    if path.stat().st_size != pin["size"]:
        raise ValueError("Size mismatch for %s (expected %s bytes)." % (path.name, pin["size"]))
    if digest(path) != pin["sha256"]:
        raise ValueError("SHA-256 mismatch for %s." % path.name)


def archive(downloads, pin, offline):
    path = downloads / pin["filename"]
    if path.exists():
        verify(path, pin)
    else:
        if offline:
            raise ValueError("Offline build needs %s." % path)
        downloads.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=downloads) as staging:
            tmp = Path(staging) / path.name
            with urlopen(pin["url"], timeout=60) as response, tmp.open("xb") as out:
                shutil.copyfileobj(response, out)
            verify(tmp, pin)
            os.replace(tmp, path)
    return path


def unpack(path, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(path) as source:
        for member in source.infolist():
            rel = PureWindowsPath(member.filename)
            if (rel.anchor or not rel.parts or ".." in rel.parts or stat.S_ISLNK(member.external_attr >> 16)
                    or any(":" in part or part.endswith((" ", ".")) or reserved(part)
                           for part in rel.parts)):
                raise ValueError("Unsafe archive path: %s" % member.filename)
            target = destination.joinpath(*rel.parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError("Archive path leaves the runtime: %s" % member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as entry, target.open("xb") as out:
                    shutil.copyfileobj(entry, out)


def inventory(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and p != folder / "RUNTIME.json"
            and not ("__pycache__" in p.parts and p.suffix == ".pyc")}


def check(folder, pins):
    manifest = json.loads((folder / "RUNTIME.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError("Invalid runtime manifest.")
    if manifest.get("packages") != pins:
        raise ValueError("This runtime is out of date. Rebuild it with --force.")
    actual = inventory(folder)
    expected = manifest["files"]
    differences = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
    if differences:
        raise ValueError("Runtime verification failed for " + ", ".join(differences))
    required = ["python.exe", "python314.zip", "python314._pth", "LICENSE.txt"]
    required.extend("Lib/site-packages/%s-%s.dist-info/METADATA" % (name, pin["version"])
                    for name, pin in pins.items() if name != "python")
    for name in required:
        if name not in actual:
            raise ValueError("Runtime is missing " + name)
    return manifest


def self_test(folder, pins):
    expected = {name: pin["version"] for name, pin in pins.items()}
    code = """import platform
import numpy, PIL, rdkit, openclatura
from rdkit import Chem
versions = dict(python=platform.python_version(), numpy=numpy.__version__,
                pillow=PIL.__version__, rdkit=rdkit.__version__, openclatura=openclatura.__version__)
expected = %r
for name, version in versions.items():
    print(name, version)
    # RDKit's date-based version may include a leading zero on the month.
    assert tuple(map(int, version.split('.'))) == tuple(map(int, expected[name].split('.')))
mol = Chem.MolFromSmiles('CCO')
assert mol is not None and mol.GetNumAtoms() == 3
assert openclatura.name_smiles('CCO') == 'ethanol'
""" % expected
    subprocess.run([str(folder / "python.exe"), "-B", "-c", code], check=True)


def build(out, downloads, pins, offline=False, force=False, test=self_test):
    out = out.resolve()
    if out.is_relative_to(downloads.resolve()) or downloads.resolve().is_relative_to(out):
        raise ValueError("Use separate output and download folders.")
    existing = out.exists() and any(out.iterdir())
    if existing:
        if not force:
            check(out, pins)
            print("Existing runtime verified.")
            return
        # Never replace a project, downloads folder or other unrelated directory.
        if not (out / "RUNTIME.json").is_file() or not (out / "python314._pth").is_file():
            raise ValueError("Choose an empty folder or an existing packaged runtime for --out.")
    files = {key: archive(downloads, pin, offline) for key, pin in pins.items()}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nbapp-runtime-", dir=out.parent) as tmp:
        staging = Path(tmp) / "runtime"
        unpack(files["python"], staging)
        for name, wheel in files.items():
            if name != "python":
                unpack(wheel, staging / "Lib" / "site-packages")
        (staging / "python314._pth").write_bytes(PTH.encode("ascii"))
        epoch = os.environ.get("SOURCE_DATE_EPOCH")
        date = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc).date() if epoch else datetime.date.today()
        manifest = dict(packages=pins, built=date.isoformat(), files=inventory(staging))
        (staging / "RUNTIME.json").write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
        check(staging, pins)
        test(staging, pins)
        previous = Path(tmp) / "previous"
        if out.exists():
            out.rename(previous)
        try:
            staging.rename(out)
        except OSError:
            if previous.exists():
                previous.rename(out)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE.parent / "runtime")
    parser.add_argument("--offline", action="store_true", help="use only verified files already in _downloads")
    parser.add_argument("--check", action="store_true", help="verify the installed files against RUNTIME.json")
    parser.add_argument("--force", action="store_true", help="replace an existing packaged runtime")
    args = parser.parse_args(argv)
    try:
        if args.check:
            check(args.out, PINS)
            print("Runtime verified.")
        else:
            build(args.out, HERE / "_downloads", PINS, args.offline, args.force)
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
