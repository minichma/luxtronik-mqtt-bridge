"""Bounded XML decoder for the observed Lux_WS information page."""

from __future__ import annotations

import re
from dataclasses import dataclass

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


class ProtocolError(ValueError):
    """No response contents in error messages."""


class AuthenticationError(ProtocolError):
    pass


@dataclass(frozen=True)
class RawReading:
    path: tuple[str, ...]
    values: tuple[str, ...]
    ambiguous: bool = False


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


def information_id(root, label: str) -> str:
    if root.tag != "Navigation":
        raise AuthenticationError("Login did not return navigation")
    items = [item for item in root.findall("item") if item.findtext("name") == label]
    if len(items) != 1:
        raise ProtocolError("Information menu missing or ambiguous")
    identifier = items[0].get("id", "")
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", identifier):
        raise ProtocolError("Invalid information menu identifier")
    return identifier


def readings(root, label: str) -> dict[tuple[str, ...], RawReading]:
    if root.tag != "Content" or root.findtext("name") != label:
        raise ProtocolError("Expected complete information content")
    result = {}

    def visit(element, prefix):
        name = element.findtext("name")
        if not name:
            raise ProtocolError("Content item missing its name")
        path = (*prefix, name)
        values = tuple(v.text or "" for v in element.findall("value"))
        if values:
            if path in result:
                result[path] = RawReading(path, (), ambiguous=True)
            else:
                result[path] = RawReading(path, values)
        for child in element.findall("item"):
            visit(child, path)

    for item in root.findall("item"):
        visit(item, ())
    return result
