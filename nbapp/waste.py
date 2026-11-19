"""Waste bottle settings, logged totals and the pickup CSV."""
import csv
from decimal import Decimal, InvalidOperation
import io
import math


DEFAULT_STREAMS = ("halogenated organic", "non-halogenated organic", "aqueous", "solid", "other")
STATES = ("open", "full", "picked-up")


def _number(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and math.isfinite(float(number)) else None


def settings(config):
    streams = config.get("waste_streams")
    if not isinstance(streams, list):
        streams = list(DEFAULT_STREAMS)
    streams = [label.strip() for label in streams if isinstance(label, str) and label.strip()]
    fraction = _number(config.get("waste_reminder_fraction"))
    if fraction is None or not 0 < fraction <= 1:
        fraction = Decimal("0.75")
    return streams, fraction


def bottle_entries(bottle):
    entries = bottle.get("entries")
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def status(bottles, fraction):
    result = {}
    for bottle in bottles:
        total = sum((_number(entry.get("volume_mL")) or Decimal(0) for entry in bottle_entries(bottle)), Decimal(0))
        capacity = _number(bottle.get("capacity_mL"))
        nearly_full = (bottle.get("state") == "open" and capacity is not None and capacity > 0
                       and total >= capacity * fraction)
        logged = int(total) if total == total.to_integral_value() else float(total)
        result[str(bottle.get("id"))] = {"total_mL": logged, "nearly_full": nearly_full}
    return result


def validate(bottles):
    """Return a short form error, or None if the bottle list can be saved."""
    if not isinstance(bottles, list):
        return "Waste bottles must be a list."
    seen = set()
    for bottle in bottles:
        if not isinstance(bottle, dict):
            return "Each waste bottle needs its own row."
        identifier = bottle.get("id")
        if type(identifier) not in (int, str) or not str(identifier).strip() or str(identifier) in seen:
            return "Each waste bottle needs a unique ID."
        seen.add(str(identifier))
        if not all(isinstance(bottle.get(field), str) and bottle[field].strip() for field in ("label", "stream")):
            return "Give each waste bottle a label and a stream."
        if bottle.get("state") not in STATES:
            return "Choose open, full or picked up for each bottle."
        capacity = bottle.get("capacity_mL")
        if capacity not in (None, "") and (_number(capacity) or 0) <= 0:
            return "Bottle capacity must be a positive volume in mL."
        if not isinstance(bottle.get("entries"), list):
            return "Bottle entries must be a list."
        for entry in bottle["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("contents"), str) or not entry["contents"].strip():
                return "Describe what went into the bottle."
            if (_number(entry.get("volume_mL")) or 0) <= 0:
                return "Enter a positive volume in mL."
    return None


def csv_log(bottle):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(("date", "experiment", "contents", "volume_mL", "by"))
    for entry in bottle_entries(bottle):
        writer.writerow(entry.get(field, "") for field in ("date", "exp", "contents", "volume_mL", "by"))
    return out.getvalue()
