"""Environment information and the shared entry point for optional scientific packages."""
from functools import lru_cache
from pathlib import Path
import platform
import sys


@lru_cache(maxsize=1)
def numpy_support():
    try:
        import numpy
    except (ImportError, OSError) as exc:
        return None, "This feature needs numpy. Use the packaged runtime. (%s)" % exc
    return numpy, ""


@lru_cache(maxsize=1)
def rdkit_support():
    try:
        import rdkit
    except (ImportError, OSError) as exc:
        return None, "This feature needs RDKit. Use a runtime built with RDKit. (%s)" % exc
    return rdkit, ""


SKETCHER = Path(__file__).resolve().parent / "sketcher" / "ketcher"


def sketcher_info():
    files = ("index.html", "static/js/main.e47c48ad.js", "static/css/main.96b87be0.css")
    installed = all((SKETCHER / name).is_file() for name in files)
    return dict(installed=installed, version="3.18.0" if installed else None)


def about():
    rdkit, _ = rdkit_support()
    numpy, _ = numpy_support()
    return dict(python=platform.python_version(), packaged=(Path(sys.executable).resolve().parent / "RUNTIME.json").is_file(),
                numpy=numpy.__version__ if numpy is not None else "not installed",
                rdkit=rdkit.__version__ if rdkit is not None else "not installed")
