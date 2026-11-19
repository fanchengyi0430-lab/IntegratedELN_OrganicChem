"""Case-relative attachment paths and file or folder fingerprints."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat

KINDS = ("scheme", "chemdraw", "sketch", "nmr-raw", "nmr-processed", "mnova", "ms", "chromatogram", "report", "image", "other")
SHALLOW_LIMIT = 20 * 1024 * 1024
_CHUNK = 1024 * 1024
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])", re.I)


class AttachmentError(ValueError):
    pass


def check_name(name):
    if (not isinstance(name, str) or not name or name.endswith((".", " "))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or _RESERVED.fullmatch(name.split(".", 1)[0].rstrip())):
        raise AttachmentError("Choose an attachment file name without path separators or reserved characters.")
    return name


def relative_parts(rel):
    if not isinstance(rel, str):
        raise AttachmentError("Attachment path must be relative to the case folder.")
    try:
        return [check_name(part) for part in rel.split("/")]
    except AttachmentError:
        raise AttachmentError("Attachment path must be relative to the case folder.") from None


def _entry(path):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in
            (stat.IO_REPARSE_TAG_SYMLINK, stat.IO_REPARSE_TAG_MOUNT_POINT)):
        raise AttachmentError("Attachments cannot include links: %s" % path.name)
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise AttachmentError("Attachments must be files or folders: %s" % path.name)
    return info


def _walk_error(error):
    raise error


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path, deep=False):
    """Return (directory, size, sha256); skip large hashes unless requested."""
    info = _entry(path)
    directory = stat.S_ISDIR(info.st_mode)
    if not directory:
        size = info.st_size
        return False, size, _hash_file(path) if deep or size <= SHALLOW_LIMIT else None

    files = []
    size = 0
    for parent, dirs, names in os.walk(path, onerror=_walk_error):
        for name in dirs:
            _entry(Path(parent) / name)
        for name in names:
            child = Path(parent) / name
            size += _entry(child).st_size
            files.append((child.relative_to(path).as_posix(), child))
    digest = None
    if deep or size <= SHALLOW_LIMIT:
        lines = [name + "\0" + _hash_file(child) for name, child in sorted(files)]
        digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return True, size, digest


def destination(folder, name, fingerprint_value):
    """Find the existing identical attachment or the first free file name."""
    stem, ext = os.path.splitext(name)
    if fingerprint_value[0]:
        stem, ext = name, ""
    numbered = re.compile(re.escape(os.path.normcase(stem)) + r" \(([1-9][0-9]*)\)" + re.escape(os.path.normcase(ext)))
    occupied = {}
    try:
        for path in folder.iterdir():
            key = os.path.normcase(path.name)
            if key == os.path.normcase(name):
                occupied[1] = path
            else:
                match = numbered.fullmatch(key)
                if match and match[1] != "1":
                    occupied[int(match[1])] = path
    except FileNotFoundError:
        return folder / name, False
    for _, path in sorted(occupied.items()):
        try:
            current = fingerprint(path)
            if current[:2] == fingerprint_value[:2] and current[2] is None:
                current = fingerprint(path, deep=True)
            if current == fingerprint_value:
                return path, True
        except (AttachmentError, OSError):
            pass  # Another object occupies this name.
    suffix = 1
    while suffix in occupied:
        suffix += 1
    return folder / (name if suffix == 1 else "%s (%d)%s" % (stem, suffix, ext)), False


def copy(source, target, fingerprint_value):
    """Copy into a staging area and confirm the bytes before installation."""
    if fingerprint_value[0]:
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target, follow_symlinks=False)
    if fingerprint(target, deep=True) != fingerprint_value:
        raise AttachmentError("The attachment changed while it was being copied. Try again.")
