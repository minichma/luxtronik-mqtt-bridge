"""Typed observations and controller-constrained write encoding."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

from .config import Sensor
from .protocol import CommandError, RawReading, now

UNITS = {
    "\u00b0C": "degC",
    "\u00b0 C": "degC",
    "h": "h",
    "kWh": "kWh",
    "kW": "kW",
    "W": "W",
    "K": "K",
    "%": "%",
    "bar": "bar",
    "V": "V",
    "l/h": "l/h",
    "l/min": "l/min",
    "Hz": "Hz",
    "s": "s",
    "min": "min",
    "rpm": "rpm",
    "A": "A",
    "": None,
}
NUMBER = re.compile(r"([+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*(.*?)\Z")


def constraints(spec: Sensor, reading: RawReading | None, enabled=True):
    if not enabled or reading is None or reading.write is None:
        return None
    w = reading.write
    if w.kind == "combo":
        # Unknown choices stay read-only until an English mapping is supplied.
        if any(code not in spec.options for code, _ in w.choices):
            return None
        return {"choices": [spec.options[code] for code, _ in w.choices]}
    if w.kind == "slider":
        return {
            "minimum": float(w.minimum / w.divisor),
            "maximum": float(w.maximum / w.divisor),
            "step": float(w.step / w.divisor),
        }
    if w.kind == "timer":
        return {"format": "HH:MM - HH:MM", "minimum": "00:00", "maximum": "23:59"}
    return None


def normalize(spec: Sensor, reading: RawReading | None, observed_at=None, *, writes=True) -> dict:
    value, quality = None, "unavailable" if reading is None else "invalid"
    possible = constraints(spec, reading, writes)
    if reading is not None and len(reading.values) == 1:
        raw = reading.values[0].strip()
        if not raw or re.fullmatch(r"---(?:\s.*)?", raw):
            quality = "unavailable"
        elif spec.type == "text" and raw:
            value, quality = spec.translations.get(raw, raw), "good"
        elif spec.type == "enum" and reading.write:
            matches = [code for code, label in reading.write.choices if label == raw]
            if len(matches) == 1 and matches[0] in spec.options:
                value, quality = spec.options[matches[0]], "good"
        elif spec.type == "boolean" and raw.lower() in (
            "ein",
            "aus",
            "true",
            "false",
            "on",
            "off",
            "ja",
            "nein",
            "yes",
            "no",
        ):
            value, quality = raw.lower() in ("ein", "true", "on", "ja", "yes"), "good"
        elif spec.type == "duration":
            match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)", raw)
            if match:
                h, m, seconds = map(int, match.groups())
                value, quality = h * 3600 + m * 60 + seconds, "good"
        elif spec.type == "timer":
            match = re.fullmatch(r"([0-2]\d:[0-5]\d)\s*-\s*([0-2]\d:[0-5]\d)", raw)
            if match and all(int(t[:2]) < 24 for t in match.groups()):
                value, quality = " - ".join(match.groups()), "good"
        elif spec.type == "number":
            match = NUMBER.fullmatch(raw)
            if match and match[2] in UNITS and UNITS[match[2]] == spec.unit:
                candidate = float(match[1].replace(",", "."))
                if math.isfinite(candidate):
                    value, quality = candidate, "good"
    return {
        "value": value,
        "unit": spec.unit,
        "observed_at": (reading.observed_at if reading else "") or observed_at or now(),
        "quality": quality,
        "path": list(reading.path if reading else spec.path),
        "writable": possible is not None,
        "possible_values": possible,
    }


def encode_command(spec: Sensor, reading: RawReading | None, payload: bytes):
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 256:
        raise CommandError("invalid_payload")
    try:
        text = payload.decode("utf-8").strip()
    except UnicodeError:
        raise CommandError("invalid_payload") from None
    possible = constraints(spec, reading)
    if possible is None:
        raise CommandError("read_only")
    w = reading.write
    if w.kind == "combo":
        codes = [code for code, _ in w.choices if spec.options[code] == text]
        if len(codes) != 1:
            raise CommandError("invalid_choice")
        return codes[0], text
    if w.kind == "slider":
        try:
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", text):
                raise ValueError
            value = Decimal(text)
            wire = value * w.divisor
            if not value.is_finite() or not w.minimum <= wire <= w.maximum:
                raise ValueError
            if (wire - w.minimum) % w.step != 0 or wire != wire.to_integral_value():
                raise ValueError
        except (InvalidOperation, ValueError):
            raise CommandError("outside_allowed_range_or_step") from None
        return str(int(wire)), float(value)
    if w.kind == "timer":
        match = re.fullmatch(r"([0-2]\d):([0-5]\d)\s*-\s*([0-2]\d):([0-5]\d)", text)
        if not match:
            raise CommandError("invalid_time_range")
        h1, m1, h2, m2 = map(int, match.groups())
        if max(h1, h2) > 23:
            raise CommandError("invalid_time_range")
        # Overnight ranges and equal start/end are controller-supported schedule values.
        wire = (h1 * 60 + m1) | ((h2 * 60 + m2) << 16)
        return str(wire), f"{h1:02}:{m1:02} - {h2:02}:{m2:02}"
    raise CommandError("unsupported_setting")


def scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def utc_now():
    return now()
