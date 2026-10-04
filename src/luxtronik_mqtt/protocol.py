"""Bounded Lux_WS XML decoding and session-local page identities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


class ProtocolError(ValueError):
    """Messages must never include controller contents or credentials."""


class AuthenticationError(ProtocolError):
    pass


class CommandError(ValueError):
    """A rejected command with a fixed, safe reason."""


@dataclass(frozen=True)
class WriteSpec:
    kind: str
    choices: tuple[tuple[str, str], ...] = ()
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    step: Decimal | None = None
    divisor: Decimal = Decimal(1)


@dataclass(frozen=True)
class RawReading:
    path: tuple[str, ...]
    values: tuple[str, ...]
    identifier: str = ""
    write: WriteSpec | None = None
    observed_at: str = ""


@dataclass
class PageSnapshot:
    ids: dict[tuple[str, ...], tuple[str, ...] | None] = field(default_factory=dict)
    values: dict[tuple[str, ...], RawReading] = field(default_factory=dict)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def decode(frame: str | bytes, max_bytes: int = 1048576):
    if len(frame.encode("utf-8") if isinstance(frame, str) else frame) > max_bytes:
        raise ProtocolError("Response exceeds frame limit")
    try:
        root = ET.fromstring(frame)
    except (ET.ParseError, DefusedXmlException, ValueError):
        raise ProtocolError("Unsupported or malformed XML response") from None
    stack = [(root, 0)]
    count = 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if depth > 32 or count > 10000:
            raise ProtocolError("Response exceeds structure limits")
        stack.extend((child, depth + 1) for child in element)
    return root


def item_id(element) -> str:
    identifier = element.get("id", "")
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", identifier):
        raise ProtocolError("Invalid item identifier")
    return identifier


def navigation(root) -> dict[tuple[str, ...], str]:
    if root.tag != "Navigation":
        raise AuthenticationError("Login did not return navigation")
    result = {}

    def visit(element, prefix):
        name = element.findtext("name")
        path = (*prefix, name) if name else prefix
        if name:
            result.setdefault(path, item_id(element))
        for child in element.findall("item"):
            visit(child, path)

    for item in root.findall("item"):
        visit(item, ())
    return result


def write_spec(element) -> WriteSpec | None:
    if element.find("raw") is None:
        return None
    kind = element.findtext("type")
    options = tuple((n.get("value", ""), n.text or "") for n in element.findall("option"))
    if kind == "combo" and options:
        if len({k for k, _ in options}) != len(options) or any(
            not re.fullmatch(r"-?[0-9]+", k) or not v for k, v in options
        ):
            raise ProtocolError("Invalid setting choices")
        return WriteSpec(kind, options)
    if kind == "timer":
        return WriteSpec(kind)
    if kind == "slider":
        try:
            lo, hi, step, divisor = (
                Decimal(element.findtext(n, "")) for n in ("min", "max", "step", "div")
            )
            if not all(v.is_finite() for v in (lo, hi, step, divisor)):
                raise ValueError
            if lo > hi or step <= 0 or divisor <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ProtocolError("Invalid setting limits") from None
        return WriteSpec(kind, minimum=lo, maximum=hi, step=step, divisor=divisor)
    return None


def content(root, page: tuple[str, ...]) -> PageSnapshot:
    if root.tag != "Content":
        raise ProtocolError("Expected page content")
    # Some pages have no root name. A present root name must match navigation.
    if root.findtext("name") not in (None, page[-1]):
        raise ProtocolError("Unexpected page name")
    snapshot = PageSnapshot()
    seen_ids = set()
    stamp = now()

    def visit(element, prefix, ancestry, position):
        identifier = item_id(element) if element.get("id") is not None else "@" + str(position)
        if element.find("value") is not None and identifier.startswith("@"):
            raise ProtocolError("Value item has no identifier")
        ids = (*ancestry, identifier)
        if ids in snapshot.ids:
            raise ProtocolError("Duplicate item identifier in hierarchy")
        name = element.findtext("name")
        if not name:
            raise ProtocolError("Content item has no name")
        path = (*prefix, name)
        values = tuple(v.text or "" for v in element.findall("value"))
        # IDs are reusable between pages, so identity is scoped to the active page.
        selected = bool(values) and path not in snapshot.values and identifier not in seen_ids
        snapshot.ids[ids] = path if selected else None
        if selected:
            seen_ids.add(identifier)
            snapshot.values[path] = RawReading(path, values, identifier, write_spec(element), stamp)
        for position, child in enumerate(element.findall("item")):
            visit(child, path, ids, position)

    for position, item in enumerate(root.findall("item")):
        visit(item, page, (), position)
    return snapshot


def refresh(root, snapshot: PageSnapshot) -> PageSnapshot:
    if root.tag != "values":
        raise ProtocolError("Expected refresh values")
    seen = set()
    updated = dict(snapshot.values)
    stamp = now()

    def visit(element, ancestry, position):
        identifier = item_id(element) if element.get("id") is not None else "@" + str(position)
        ids = (*ancestry, identifier)
        if ids in seen or ids not in snapshot.ids:
            raise ProtocolError("Unknown or duplicate refresh identifier")
        seen.add(ids)
        path = snapshot.ids[ids]
        values = tuple(v.text or "" for v in element.findall("value"))
        if path is not None and values:
            updated[path] = replace(updated[path], values=values, observed_at=stamp)
        for position, child in enumerate(element.findall("item")):
            visit(child, ids, position)

    for position, item in enumerate(root.findall("item")):
        visit(item, (), position)
    # Fields omitted by REFRESH retain their previous observation timestamp.
    return PageSnapshot(snapshot.ids, updated)
