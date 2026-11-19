"""Read Bruker processed spectra (pdata/1/1r) and integrate spectra from either source.

Every value is a check for the researcher to review. Instrument folders are read-only.
"""
import array
import datetime
import os
import re
import sys

SOLVENT_1H = {"CDCl3": 7.26, "DMSO": 2.50, "MeOD": 3.31, "CD3CN": 1.94, "C6D6": 7.16, "Acetone": 2.05, "D2O": 4.79, "CD2Cl2": 5.32}
SOLVENT_13C = {"CDCl3": 77.16, "DMSO": 39.52, "MeOD": 49.00, "CD3CN": 1.32, "C6D6": 128.06, "Acetone": 29.84, "CD2Cl2": 53.84}


class NmrError(Exception):
    pass


def _jcamp(path):
    with open(path, encoding="latin-1") as fh:
        text = fh.read()
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"##\$?([A-Za-z0-9_]+)= ?(.*)", text)}


def _clean(v):
    return (v or "").strip("<>")


def acquisition_info(acq_dir):
    """Nucleus, spectrometer frequency (MHz) and acquisition date of one acquisition, or None if it is not one."""
    path = os.path.join(acq_dir, "acqus")
    if not os.path.isfile(path):
        return None
    aq = _jcamp(path)
    nucleus = _clean(aq.get("NUC1"))
    try:
        mhz = int(round(float(aq.get("SFO1", "0") or 0)))
        date = datetime.date.fromtimestamp(int(aq.get("DATE", "0") or 0)).isoformat() if aq.get("DATE") else ""
    except (ValueError, OverflowError, OSError):
        return None
    if not nucleus or not mhz:
        return None
    return {"nucleus": nucleus, "mhz": mhz, "date": date,
            "processed": os.path.isfile(os.path.join(acq_dir, "pdata", "1", "1r"))}


class Spectrum:
    processing = {"source": "topspin"}

    def __init__(self, acq_dir):
        self.dir = acq_dir
        pdata = os.path.join(acq_dir, "pdata", "1")
        for need in (os.path.join(acq_dir, "acqus"), os.path.join(pdata, "procs"), os.path.join(pdata, "1r")):
            if not os.path.isfile(need):
                raise NmrError("No processed spectrum here: %s is missing." % os.path.basename(need))
        aq = _jcamp(os.path.join(acq_dir, "acqus"))
        pr = _jcamp(os.path.join(pdata, "procs"))
        self._read_metadata(aq, pdata)
        self.si = int(pr["SI"])
        self.offset = float(pr["OFFSET"])
        self.sw_ppm = float(pr["SW_p"]) / float(pr["SF"])
        self.step = self.sw_ppm / self.si
        typecode = "d" if pr.get("DTYPP", "0").strip() == "2" else "i"
        y = array.array(typecode)
        with open(os.path.join(pdata, "1r"), "rb") as fh:
            y.frombytes(fh.read())
        big_endian_file = pr.get("BYTORDP", "0").strip() == "1"
        if big_endian_file != (sys.byteorder == "big"):
            y.byteswap()
        if len(y) != self.si:
            raise NmrError("Spectrum has %d points but its parameters say %d." % (len(y), self.si))
        self.y = y

    def _read_metadata(self, aq, pdata):
        self.nucleus = _clean(aq.get("NUC1"))
        self.solvent = _clean(aq.get("SOLVENT"))
        self.pulprog = _clean(aq.get("PULPROG"))
        self.sfo1 = float(aq.get("SFO1", "0") or 0)
        self.scans = aq.get("NS", "")
        title = os.path.join(pdata, "title")
        self.title = ""
        if os.path.isfile(title):
            with open(title, encoding="latin-1") as fh:
                lines = fh.read().strip().splitlines()
            self.title = lines[0] if lines else ""

    # ppm <-> index (index 0 is the high-ppm edge)
    def index(self, ppm):
        return max(0, min(self.si - 1, int(round((self.offset - ppm) / self.step))))

    def ppm(self, i):
        return self.offset - i * self.step

    @property
    def lo(self):
        return self.offset - self.sw_ppm

    def meta(self):
        return {"nucleus": self.nucleus, "solvent": self.solvent, "mhz": round(self.sfo1, 1), "pulprog": self.pulprog,
                "scans": self.scans, "points": self.si, "hi": round(self.offset, 4), "lo": round(self.lo, 4), "title": self.title}

    def envelope(self, lo, hi, bins=1200):
        """Min/max per pixel column for drawing, left edge = high ppm."""
        lo, hi = max(self.lo, min(lo, hi)), min(self.offset, max(lo, hi))
        i0, i1 = self.index(hi), self.index(lo)
        n = max(1, i1 - i0 + 1)
        bins = max(10, min(int(bins), n))
        mins, maxs = [], []
        for b in range(bins):
            a = i0 + (b * n) // bins
            z = i0 + ((b + 1) * n) // bins
            seg = self.y[a:max(z, a + 1)]
            mins.append(min(seg))
            maxs.append(max(seg))
        return {"lo": lo, "hi": hi, "min": mins, "max": maxs}

    def tallest(self, lo, hi):
        i0, i1 = self.index(max(lo, hi)), self.index(min(lo, hi))
        k = max(range(i0, i1 + 1), key=lambda i: self.y[i])
        return self.ppm(k), self.y[k]

    def noise(self):
        """Standard deviation of a signal-free strip at the high-ppm edge (crude, for a detection limit)."""
        n = max(200, self.si // 50)
        seg = self.y[:n]
        mean = sum(seg) / float(n)
        return (sum((v - mean) ** 2 for v in seg) / float(n)) ** 0.5

    def integrate(self, lo, hi, baseline=True):
        """Area between lo and hi (ppm). With baseline=True a straight line through the mean
        of the points just outside each edge is subtracted first."""
        lo, hi = min(lo, hi), max(lo, hi)
        i0, i1 = self.index(hi), self.index(lo)
        seg = self.y[i0:i1 + 1]
        total = float(sum(seg))
        if baseline and seg:
            k = max(4, len(seg) // 10)
            left = self.y[max(0, i0 - k):i0] or seg[:1]
            right = self.y[i1 + 1:i1 + 1 + k] or seg[-1:]
            total -= (sum(left) / float(len(left)) + sum(right) / float(len(right))) / 2.0 * len(seg)
        return total * self.step

    def solvent_shift(self):
        """Correction (ppm) that puts the residual solvent peak on its literature value, or None.

        1H: the tallest peak within 0.15 ppm of the expected position, accepted only when it
        clearly dominates that window. 13C (CDCl3): the centre of the 1:1:1 triplet."""
        key = next((k for k in SOLVENT_1H if k.lower() in self.solvent.lower()), None)
        if not key:
            return None
        if self.nucleus == "1H":
            target = SOLVENT_1H[key]
            ppm, height = self.tallest(target - 0.15, target + 0.15)
            if height < 8 * self.noise():
                return None
            return {"correction": target - ppm, "found": ppm, "target": target, "solvent": key}
        if self.nucleus == "13C" and key in SOLVENT_13C:
            target = SOLVENT_13C[key]
            ppm, height = self.tallest(target - 0.6, target + 0.6)
            if height < 8 * self.noise():
                return None
            if key == "CDCl3":  # tallest line may be an outer line of the triplet: use the middle of the three
                lines = [p for p, _ in self.pick(target - 0.7, target + 0.7, 0.5)]
                if len(lines) >= 3:
                    lines.sort()
                    ppm = lines[len(lines) // 2]
            return {"correction": target - ppm, "found": ppm, "target": target, "solvent": key}
        return None

    def pick(self, lo, hi, rel=0.03):
        """Local maxima above rel x the tallest point in the window: [(ppm, height)]."""
        i0, i1 = self.index(max(lo, hi)), self.index(min(lo, hi))
        y = self.y
        top = max(y[i0:i1 + 1])
        floor = max(top * rel, 6 * self.noise())
        out = []
        for i in range(max(i0, 2), min(i1, self.si - 3) + 1):
            v = y[i]
            if v > floor and v >= y[i - 1] and v > y[i + 1] and v >= y[i - 2] and v > y[i + 2]:
                out.append((self.ppm(i), v))
        return out


def peaklist(acq_dir):
    """Peaks TopSpin picked at acquisition (pdata/1/peaklist.xml): [(ppm, intensity)], or [] when absent."""
    path = os.path.join(acq_dir, "pdata", "1", "peaklist.xml")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return [(float(a), float(b)) for a, b in re.findall(r'F1="([-\d.]+)"\s+intensity="([-\d.eE+]+)"', text)]


def nmr_yield(spec, product, standard, std_mmol, limiting_mmol, baseline=True, reference=True, snap=True):
    """NMR yield (%) of a product against an internal standard.

    product / standard: {"lo", "hi", "nH"} in ppm on the CDCl3 = 7.26 scale when reference=True.
    reference: shift both regions by this spectrum's solvent correction first.
    snap: re-centre the standard region on the tallest peak within 0.12 ppm of its centre.
    """
    shift = 0.0
    ref = spec.solvent_shift() if reference else None
    if ref:
        shift = -ref["correction"]
    p_lo, p_hi = product["lo"] + shift, product["hi"] + shift
    s_lo, s_hi = standard["lo"] + shift, standard["hi"] + shift
    if snap:
        centre = (s_lo + s_hi) / 2.0
        peak, _ = spec.tallest(centre - 0.12, centre + 0.12)
        half = (s_hi - s_lo) / 2.0
        s_lo, s_hi = peak - half, peak + half
    ip = spec.integrate(p_lo, p_hi, baseline)
    istd = spec.integrate(s_lo, s_hi, baseline)
    out = {"product": {"lo": round(p_lo, 4), "hi": round(p_hi, 4), "nH": product["nH"], "area": ip},
           "standard": {"lo": round(s_lo, 4), "hi": round(s_hi, 4), "nH": standard["nH"], "area": istd},
           "reference": ref, "baseline": baseline, "yield": None, "note": ""}
    seg_n = max(1, abs(spec.index(s_lo) - spec.index(s_hi)))
    if istd <= 0 or istd < 5 * spec.noise() * spec.step * seg_n ** 0.5:
        out["note"] = "No internal standard signal found in the standard region."
        return out
    if not std_mmol or not limiting_mmol:
        out["note"] = "Standard and limiting-reagent amounts (mmol) are needed."
        return out
    out["yield"] = (ip / product["nH"]) / (istd / standard["nH"]) * std_mmol / limiting_mmol * 100.0
    if out["yield"] > 105:
        out["note"] = "Over 100%: check that the standard is in this sample and that the regions are right."
    return out
