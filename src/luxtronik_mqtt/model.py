"""Explicit conversions; missing/invalid data never becomes zero."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .config import Sensor
from .protocol import ProtocolError, RawReading

UNITS = {
    "°C": "degC",
    "° C": "degC",
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
    "": None,
}
NUMBER = re.compile(r"([+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*(.*?)\Z")


def normalize(spec: Sensor, reading: RawReading | None, observed_at: str) -> dict:
    if reading is not None and reading.ambiguous:
        raise ProtocolError("Configured sensor path is ambiguous")
    value, quality = None, "unavailable" if reading is None else "invalid"
    if reading is not None and len(reading.values) == 1:
        raw = reading.values[0].strip()
        if spec.type == "text" and raw:
            value, quality = raw, "good"
        elif spec.type == "boolean" and raw in ("Ein", "Aus", "true", "false", "On", "Off"):
            value, quality = raw in ("Ein", "true", "On"), "good"
        elif spec.type == "duration":
            match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)", raw)
            if match:
                h, m, s = map(int, match.groups())
                value, quality = h * 3600 + m * 60 + s, "good"
        elif spec.type == "number":
            match = NUMBER.fullmatch(raw)
            if match and match[2] in UNITS and UNITS[match[2]] == spec.unit:
                candidate = float(match[1].replace(",", "."))
                if math.isfinite(candidate):
                    value, quality = candidate, "good"
    return {"value": value, "unit": spec.unit, "observed_at": observed_at, "quality": quality}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
