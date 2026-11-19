"""Read-only processing of a Bruker 1D FID. All angles use TopSpin's degrees."""
import array
from functools import lru_cache
import math
from pathlib import Path

from . import nmr, runtime_info
from .nmr import NmrError

MAX_POINTS = 4 * 1024 * 1024
PHASE_MODES = ("topspin", "manual", "auto0")


def _number(value, name):
    try:
        if isinstance(value, bool):
            raise ValueError
        v = float(value)
        if math.isfinite(v):
            return v
    except (TypeError, ValueError, OverflowError):
        pass
    raise NmrError("%s must be a finite number." % name)


def _integer(value, name):
    v = _number(value, name)
    if not v.is_integer():
        raise NmrError("%s must be a whole number." % name)
    return int(v)


def _auto0(np, spectrum, centre, bounded):
    # The probe scores every eighth point using derivative entropy and negative power.
    sample = spectrum[::8]
    amplitude = np.max(np.abs(sample))
    if amplitude == 0:
        raise NmrError("Automatic phasing needs a signal in the FID.")
    sample = sample / amplitude

    def score(degrees):
        r = (sample * np.exp(-1j * np.deg2rad(degrees))).real
        d = np.abs(np.diff(r))
        total, power = d.sum(), np.sum(r * r)
        if total == 0 or power == 0:
            return math.inf
        q = d[d > 0] / total
        return -np.sum(q * np.log(q)) + 1000 * np.sum(r[r < 0] ** 2) / power

    width = 10 if bounded else 180
    low, high = centre - width, centre + width
    angle = min(np.arange(low, high + 1, 2), key=score)
    for step in (0.2, 0.02):
        grid = angle + np.arange(-10, 11) * step
        if bounded:
            grid = np.clip(grid, low, high)
        angle = min(grid, key=score)
    if not math.isfinite(score(angle)):
        raise NmrError("Automatic phasing needs a varying signal in the FID.")
    return round(float(angle if bounded else (angle + 180) % 360 - 180), 10)


class FidSpectrum(nmr.Spectrum):
    def __init__(self, np, folder, lb_hz, points, phase_mode, ph0, ph1):
        self.dir = folder
        pdata = folder / "pdata" / "1"
        aq = nmr._jcamp(folder / "acqus")
        if int(aq.get("PARMODE", 0)) != 0 or (folder / "acqu2s").is_file():
            raise NmrError("Only one-dimensional Bruker acquisitions are supported.")
        delay = _number(aq.get("GRPDLY", -1), "GRPDLY")
        if delay < 0:
            raise NmrError("This data set is unsupported: GRPDLY is missing or negative.")
        order, dtype = aq["BYTORDA"], aq["DTYPA"]
        if order not in ("0", "1") or dtype not in ("0", "2"):
            raise NmrError("Unsupported FID format. Use 32-bit integers or 64-bit floats with BYTORDA 0 or 1.")
        dtype = ("<" if order == "0" else ">") + ("i4" if dtype == "0" else "f8")
        td = _integer(aq["TD"], "TD")
        n = td // 2
        keep = n - math.ceil(delay)
        if td % 2 or keep < 2:
            raise NmrError("TD and GRPDLY must leave at least two complex points.")
        if n > MAX_POINTS or td * np.dtype(dtype).itemsize > (folder / "fid").stat().st_size:
            raise NmrError("TD exceeds the available FID data or the supported transform size.")
        sw, bf, o1 = (_number(aq[k], k) for k in ("SW_h", "BF1", "O1"))
        if min(sw, bf) <= 0:
            raise NmrError("SW_h and BF1 must be positive.")
        procs = pdata / "procs"
        has_procs = procs.is_file()
        pr = nmr._jcamp(procs) if has_procs else {}
        self.si = _integer(pr.get("SI", 1 << (2 * n - 1).bit_length()) if points is None else points, "points")
        if not keep <= self.si <= MAX_POINTS:
            raise NmrError("Choose between %d and %d transform points for this FID." % (keep, MAX_POINTS))
        lb = _number(pr.get("LB", 0.3) if lb_hz is None else lb_hz, "lb_hz")
        p0, p1 = (_number(pr.get(k, 0), k) for k in ("PHC0", "PHC1"))
        sf = _number(pr.get("SF", bf), "SF")
        width = _number(pr.get("SW_p", sw), "SW_p")
        if min(sf, width) <= 0:
            raise NmrError("The spectral width and referencing frequency must be positive.")
        self.offset = _number(pr.get("OFFSET", (o1 + sw / 2) / bf), "OFFSET")
        self.sw_ppm = width / sf
        self.step = self.sw_ppm / self.si
        self._read_metadata(aq, pdata)
        if not self.sfo1:
            self.sfo1 = bf + o1 / 1e6
        raw = np.fromfile(folder / "fid", dtype=dtype, count=td)
        if raw.size != td:
            raise NmrError("The FID ended before TD points could be read.")
        signal = raw.astype(np.float64).view(np.complex128)
        if delay.is_integer():
            signal = signal[int(delay):]
        else:
            cycles = delay * np.arange(n) / n
            if pr.get("PKNL") == "yes":
                # TopSpin references its fractional digital-filter phase to the high
                # edge. The integer part is an ordinary translation in dwell times.
                cycles = delay * np.fft.fftfreq(n) - (delay - round(delay)) / 2
            ramp = np.exp(2j * np.pi * cycles)
            signal = np.fft.ifft(np.fft.fft(signal) * ramp)[:keep]
        with np.errstate(over="ignore", invalid="ignore"):
            signal *= np.exp(-np.pi * lb * np.arange(keep) / sw)
        if not np.isfinite(signal).all():
            raise NmrError("The FID or the window contains non-finite intensities.")
        signal[0] *= 0.5
        # Positive frequency is high ppm. Bin zero is the Nyquist edge itself:
        # reversing an fftshift(fft) by slicing alone puts that edge one bin late.
        spectrum = np.fft.fftshift(np.fft.ifft(signal, self.si, norm="forward"))
        if phase_mode == "manual":
            p0 = p0 if ph0 is None else ph0
            p1 = p1 if ph1 is None else ph1
        elif phase_mode == "auto0":
            phased = spectrum * np.exp(-1j * np.deg2rad(p1 * np.arange(self.si) / self.si))
            p0 = _auto0(np, phased, p0, has_procs)
        ramp = np.exp(-1j * np.deg2rad(p0 + p1 * np.arange(self.si) / self.si))
        real = (spectrum * ramp).real
        if not np.isfinite(real).all():
            raise NmrError("The transform produced non-finite intensities.")
        self.y = array.array("d")
        self.y.frombytes(real.tobytes())
        self.processing = dict(source="fid", lb_hz=lb, points=self.si, phase_mode=phase_mode,
                               ph0=p0, ph1=p1, numpy=np.__version__)
        if phase_mode == "auto0":
            self.processing["delta_ph0"] = p0 - float(pr.get("PHC0", 0)) if has_procs else None


@lru_cache(maxsize=6)
def _cached(folder, stamps, lb_hz, points, phase_mode, ph0, ph1):
    np, _ = runtime_info.numpy_support()
    return FidSpectrum(np, folder, lb_hz, points, phase_mode, ph0, ph1)


def process(acq_dir, *, lb_hz=None, points=None, phase_mode="topspin", ph0=None, ph1=None):
    np, reason = runtime_info.numpy_support()
    if np is None:
        raise NmrError(reason)
    if phase_mode not in PHASE_MODES:
        raise NmrError("Choose TopSpin, manual or automatic zero-order phase.")
    folder = Path(acq_dir).resolve()
    try:
        stamps = []
        for name in ("acqus", "fid", "pdata/1/procs", "pdata/1/title", "acqu2s"):
            file = folder / name
            if not file.is_file():
                if name in ("acqus", "fid"):
                    raise NmrError("No raw FID acquisition here: %s is missing." % name)
                stamps.append(None)
            else:
                stat = file.stat()
                stamps.append((stat.st_mtime_ns, stat.st_size))
        return _cached(folder, tuple(stamps), None if lb_hz is None else _number(lb_hz, "lb_hz"),
                       None if points is None else _integer(points, "points"), phase_mode,
                       _number(ph0, "ph0") if phase_mode == "manual" and ph0 is not None else None,
                       _number(ph1, "ph1") if phase_mode == "manual" and ph1 is not None else None)
    except KeyError as exc:
        raise NmrError("Missing Bruker parameter %s." % exc.args[0]) from exc
    except (OSError, ValueError) as exc:
        raise NmrError("Cannot read this Bruker acquisition: %s" % exc) from exc
