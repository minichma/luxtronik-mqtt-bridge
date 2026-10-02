"""Read-only protocol inspection; raw frames stay in an external directory.

Developer tool, not a service entry point. Never prints login frames or raw data.
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from defusedxml import ElementTree as ET
from websockets.asyncio.client import connect


async def inspect(url, output):
    secret = Path(os.environ["LUXTRONIK_PASSWORD_FILE"]).read_text(encoding="utf-8")
    secret = secret.removesuffix("\n").removesuffix("\r")
    output.mkdir(parents=True, exist_ok=True)
    async with connect(url, subprotocols=["Lux_WS"], proxy=None, close_timeout=2) as ws:
        await ws.send("LOGIN;" + secret)
        raw = await asyncio.wait_for(ws.recv(), 10)
        root = ET.fromstring(raw)
        (output / "navigation.xml").write_text(
            raw.decode() if isinstance(raw, bytes) else raw, encoding="utf-8"
        )
        print("Login response type:", root.tag)
        print("Navigation labels:", [item.findtext("name") for item in root.findall("item")])
        infos = [i for i in root.findall("item") if i.findtext("name") == "Informationen"]
        if len(infos) != 1:
            raise ValueError("Expected one information menu")
        await ws.send("GET;" + infos[0].attrib["id"])
        raw = await asyncio.wait_for(ws.recv(), 10)
        root = ET.fromstring(raw)
        (output / "information.xml").write_text(
            raw.decode() if isinstance(raw, bytes) else raw, encoding="utf-8"
        )
        print("Information response:", root.tag, "attributes:", sorted(root.attrib))
        for section in root.findall("item"):
            print("Section:", section.findtext("name"), "children:", len(section.findall("item")))
            for item in section.findall("item"):
                name = item.findtext("name", "")
                if (
                    section.findtext("name") in ("Temperaturen", "Betriebsstunden")
                    or "Software" in name
                ):
                    print("  ", name, "=", item.findtext("value"))
        await ws.send("REFRESH")
        raw = await asyncio.wait_for(ws.recv(), 10)
        root = ET.fromstring(raw)
        (output / "refresh.xml").write_text(
            raw.decode() if isinstance(raw, bytes) else raw, encoding="utf-8"
        )
        print("Refresh response:", root.tag, "children:", len(root))
        await ws.send("GET;" + infos[0].attrib["id"])
        root = ET.fromstring(await asyncio.wait_for(ws.recv(), 10))
        print("Repeated GET:", root.tag, "name:", root.findtext("name"))


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("captures must be outside the repository")
    try:
        asyncio.run(inspect(args.url, args.output))
    except Exception as exc:
        print("Inspection failed:", type(exc).__name__)
        raise SystemExit(1) from None
