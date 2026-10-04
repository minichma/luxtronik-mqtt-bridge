"""Stateful controller double using sanitized bilingual page fixtures."""

import copy
import json
import logging
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

from websockets.asyncio.server import serve

from luxtronik_mqtt.protocol import decode, navigation


class FakeController:
    def __init__(self, fixture_dir):
        self.fixture_dir = fixture_dir
        self.nav = decode((fixture_dir / "navigation.xml").read_bytes())
        self.pages = {
            tuple(m["path"]): decode((fixture_dir / m["file"]).read_bytes())
            for m in json.loads((fixture_dir / "pages.json").read_text("utf-8"))
        }
        self.commands = []
        self.connections = 0
        self.saved = 0
        self.drop_save_reply = False
        self.omit = set()
        self.active = set()

    def set_value(self, name, value):
        for root in self.pages.values():
            for node in root.iter("item"):
                if node.findtext("name") == name and node.find("value") is not None:
                    node.find("value").text = value

    async def __aenter__(self):
        log = logging.Logger("test-controller-silent")
        log.disabled = True
        self.server = await serve(self.handle, "0.0.0.0", 0, subprotocols=["Lux_WS"], logger=log)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, ws):
        self.connections += 1
        connection = self.connections
        self.active.add(ws)

        def wire(root):
            root = copy.deepcopy(root)
            for node in root.iter("item"):
                if node.get("id"):
                    node.set("id", "0x" + str(connection) + node.get("id")[2:])
            return root

        nav = wire(self.nav)
        ids = {v: k for k, v in navigation(nav).items()}
        page = None
        pending = None
        try:
            assert (await ws.recv()).startswith("LOGIN;")
            await ws.send(tostring(nav, encoding="unicode"))
            async for command in ws:
                self.commands.append((connection, command))
                if command.startswith("GET;"):
                    page = ids[command.split(";")[1]]
                    await ws.send(tostring(wire(self.pages[page]), encoding="unicode"))
                elif command == "REFRESH":
                    root = wire(self.pages[page])
                    update = Element("values")

                    def visit(source, target):
                        for node in source.findall("item"):
                            if node.findtext("name") in self.omit:
                                continue
                            child = SubElement(target, "item", dict(node.attrib))
                            for value in node.findall("value"):
                                child.append(copy.deepcopy(value))
                            visit(node, child)

                    visit(root, update)
                    await ws.send(tostring(update, encoding="unicode"))
                elif command.startswith("SET;"):
                    _, identifier, value = command.split(";")
                    actual = "0x" + identifier[len("set_0x") + len(str(connection)) :]
                    node = next(n for n in self.pages[page].iter("item") if n.get("id") == actual)
                    assert node.find("raw") is not None
                    pending = (node, value)
                elif command == "SAVE;1":
                    node, value = pending
                    kind = node.findtext("type")
                    if kind == "slider":
                        text = format(
                            Decimal(value) / Decimal(node.findtext("div")), "f"
                        ) + node.findtext("unit", "")
                    elif kind == "combo":
                        text = next(
                            n.text for n in node.findall("option") if n.get("value") == value
                        )
                    else:
                        start, end = int(value) & 65535, int(value) >> 16
                        text = f"{start // 60:02}:{start % 60:02} - {end // 60:02}:{end % 60:02}"
                    node.find("value").text = text
                    node.find("raw").text = value
                    self.saved += 1
                    if self.drop_save_reply:
                        self.drop_save_reply = False
                        await ws.close()
                        return
                    await ws.send(tostring(wire(self.pages[page]), encoding="unicode"))
                else:
                    raise AssertionError("Unexpected command")
        finally:
            self.active.discard(ws)
