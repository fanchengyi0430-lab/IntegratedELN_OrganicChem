"""Conservative first-order proposals for a picked 1D proton spectrum."""
from itertools import combinations
from math import comb

from . import nmr, si_format
from .formatting import markup, plain

# Number of equivalent couplings at each splitting, largest J first.
PATTERNS = {2: {"d": (1,)}, 3: {"t": (2,)}, 4: {"q": (3,), "dd": (1, 1)},
            6: {"dt": (1, 2), "td": (2, 1)}, 8: {"ddd": (1, 1, 1)}}


def pattern(peaks, mhz, resolution):
    """Check all line positions AND relative heights against resolved binomial splittings."""
    if len(peaks) == 1:
        return "s", []
    choices = PATTERNS.get(len(peaks))
    if not choices or mhz <= 0:
        return "m", []
    peaks = sorted(peaks)
    start = peaks[0][0]
    x = [(p - start) * mhz for p, _ in peaks]
    top = max(h for _, h in peaks)
    if top <= 0:
        return "m", []
    intensity = [h / top for _, h in peaks]
    tolerance = max(0.15, min(0.45, resolution))
    # Each resolved elementary splitting is a difference between two observed lines.
    differences = sorted({round(b - a, 2) for a, b in combinations(x, 2)
                          if b - a > 2 * tolerance}, reverse=True)
    fits = {}
    for name, splits in choices.items():
        for js in combinations(differences, len(splits)):
            if abs(sum(j * n for j, n in zip(js, splits)) - x[-1]) > tolerance:
                continue
            lines = [(0.0, 1)]
            for count, j in zip(splits, js):
                lines = [(p + k * j, h * comb(count, k)) for p, h in lines for k in range(count + 1)]
            lines.sort()
            if any(b[0] - a[0] <= 2 * tolerance for a, b in zip(lines, lines[1:])):
                continue
            weight = max(h for _, h in lines)
            if any(abs(obs - h / weight) > 0.20 * h / weight for obs, (_, h) in zip(intensity, lines)):
                continue
            error = max(abs(obs - p) for obs, (p, _) in zip(x, lines))
            if error <= tolerance and (name not in fits or error < fits[name][0]):
                fits[name] = (error, js)
    if len(fits) != 1:
        return "m", []
    name, (_, js) = fits.popitem()
    return name, list(js)


def proposal(spec, impurities=(), reference_group=None, count=None):
    if spec.nucleus != "1H" or spec.sfo1 <= 0:
        raise ValueError("Select a proton spectrum with a recorded frequency.")
    picked = nmr.peaklist(spec.dir) if spec.processing["source"] == "topspin" else []
    ref = spec.solvent_shift()
    if not picked:
        # A strong solvent signal can dwarf every analyte peak. Pick outside its window.
        windows = [(spec.lo, spec.offset)] if not ref else [
            (spec.lo, ref["found"] - 0.03), (ref["found"] + 0.03, spec.offset)]
        picked = [peak for lo, hi in windows if hi > lo for peak in spec.pick(lo, hi, 0.02)]
    correction = ref["correction"] if ref else 0
    kept = []
    for ppm, height in picked:
        pos = ppm + correction
        if height <= 0 or (ref and abs(pos - ref["target"]) <= 0.03):
            continue
        if "CDCl3" in spec.solvent and any(abs(pos - p) <= 0.03 for p, _ in impurities):
            continue
        kept.append((pos, height))
    threshold = max((h for _, h in kept), default=0) * 0.03
    groups = []
    for ppm, h in sorted(kept, reverse=True):
        if h < threshold:
            continue
        if not groups or (groups[-1][-1][0] - ppm) * spec.sfo1 > 18:
            groups.append([])
        groups[-1].append((ppm, h))

    rows = []
    for i, group in enumerate(groups):
        hi, lo = group[0][0], group[-1][0]
        # Limit integration to the midpoint to each neighbour; use the yield tool's baseline.
        left = max(lo - 0.025, (lo + groups[i + 1][0][0]) / 2) if i + 1 < len(groups) else lo - 0.025
        right = min(hi + 0.025, (hi + groups[i - 1][-1][0]) / 2) if i else hi + 0.025
        area = max(0, spec.integrate(left - correction, right - correction, baseline=True))
        mult, js = pattern(group, spec.sfo1, spec.step * spec.sfo1)
        rows.append(dict(shift=(lo + hi) / 2, lo=lo, hi=hi, multiplicity=mult, j=js, area=area))
    unit = min((r["area"] for r in rows if r["area"] > 0), default=1)
    if count is not None:
        if (type(count) is not int or count < 1 or type(reference_group) is not int
                or not 0 <= reference_group < len(rows) or not rows[reference_group]["area"]):
            raise ValueError("Choose a reference group with a positive area and a positive whole proton count.")
        unit = rows[reference_group]["area"] / count
    parts = []
    for r in rows:
        mult = r["multiplicity"]
        shift = "%.2f–%.2f" % (r["hi"], r["lo"]) if mult == "m" else "%.2f" % r["shift"]
        detail = [mult]
        if r["j"]:
            detail.append("J = " + ", ".join("%.1f" % j for j in r["j"]) + " Hz")
        relative = r["area"] / unit
        r.update(label=shift.replace("-", "−"), relative=relative, protons=None)
        if count is not None:
            r["protons"] = round(relative, 1)
            detail.append("%gH" % r["protons"])
        parts.append(shift + " (" + ", ".join(detail) + ")")
    line = "¹H NMR (%g MHz, %s) δ %s." % (round(spec.sfo1), spec.solvent, ", ".join(parts))
    runs = si_format.characterization(line)[1] if rows else []
    return {"rows": rows, "line": plain(runs), "editor_line": line, "html": markup(runs), "processing": spec.processing}
