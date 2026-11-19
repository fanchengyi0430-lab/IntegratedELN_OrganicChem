"""Install the pinned standalone Ketcher release. Run explicitly from the command line."""
import argparse
from pathlib import Path
import tempfile

if __package__:
    from .build_runtime import archive, unpack
else:
    # Embedded Python omits the script directory from its isolated search path.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_runtime import archive, unpack

HERE = Path(__file__).resolve().parent
PIN = dict(version="3.18.0", filename="ketcher-standalone-3.18.0.zip", size=35057618,
           sha256="484e7f10a0e74808ae5f43f0e6448db6f4d884bdd2189aa271108474167a3e7e",
           url="https://github.com/epam/ketcher/releases/download/v3.18.0/ketcher-standalone-3.18.0.zip")


def build(folder, downloads, force=False, offline=False):
    for name in ("LICENSE-ketcher.txt", "NOTICE-ketcher.txt"):
        if not (folder / name).is_file():
            raise ValueError("Place %s in %s before installing Ketcher." % (name, folder))
    target = folder / "ketcher"
    if target.exists() and not force:
        raise ValueError("Ketcher is already present. Use --force to rebuild.")
    zip_path = archive(downloads, PIN, offline)
    with tempfile.TemporaryDirectory(dir=folder) as staging:
        staged = Path(staging) / "ketcher"
        unpack(zip_path, staged)
        old = Path(staging) / "previous"
        if target.exists():
            target.rename(old)
        try:
            staged.rename(target)
        except OSError:
            if old.exists():
                old.rename(target)
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE.parent / "sketcher", help="Directory containing the two notices")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        build(args.out, HERE / "_downloads", args.force, args.offline)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    print("Installed Ketcher " + PIN["version"])
