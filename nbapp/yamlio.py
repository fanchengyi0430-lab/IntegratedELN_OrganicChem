"""YAML reading and writing in the same style the records already use.

Uses the system PyYAML when it is installed and the bundled copy in vendor/ otherwise,
so the app needs nothing beyond Python itself.
"""
import os
import sys

VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
try:
    import yaml
except ImportError:  # no PyYAML on this Python: use the bundled pure-Python copy
    sys.path.append(VENDOR)
    import yaml


YAMLError = yaml.YAMLError


class _Dumper(yaml.SafeDumper):
    pass


def load(text):
    return yaml.safe_load(text)


def dump(data):
    """Same options the records were written with, so a save changes only what was edited."""
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=1000, default_flow_style=None)


def split_header(text):
    """Leading comment lines of a record file, kept verbatim on save."""
    head = []
    for line in text.split("\n"):
        if line.startswith("#"):
            head.append(line)
        else:
            break
    return "".join(h + "\n" for h in head)
