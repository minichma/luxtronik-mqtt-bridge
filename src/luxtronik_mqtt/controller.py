"""Serialized page sessions with bounded reads and validated setting transactions."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack

from websockets.asyncio.client import connect

from .compat import timeout
from .model import encode_command, normalize
from .protocol import CommandError, ProtocolError, content, decode, navigation, refresh

# Transport debug frames contain credentials. Never attach these loggers to root.
WIRE_LOG = logging.Logger("luxtronik_wire_disabled")
WIRE_LOG.disabled = True


class Session:
    def __init__(self, config, password):
        self.config, self.password = config, password
        self.page = None
        self.snapshot = None

    async def __aenter__(self):
        c = self.config
        self.connection = connect(
            c.url,
            subprotocols=["Lux_WS"],
            proxy=None,
            compression=None,
            open_timeout=c.timeout,
            close_timeout=2,
            ping_interval=None,
            max_size=c.max_frame,
            max_queue=4,
            logger=WIRE_LOG,
        )
        self.ws = await self.connection.__aenter__()
        try:
            if self.ws.subprotocol != "Lux_WS":
                raise ProtocolError("Lux_WS subprotocol was not negotiated")
            async with timeout(c.timeout):
                await self.ws.send("LOGIN;" + self.password)
                self.navigation = navigation(await self.receive())
        except BaseException:
            await self.connection.__aexit__(None, None, None)
            raise
        return self

    async def receive(self):
        return decode(await self.ws.recv(), self.config.max_frame)

    async def read(self, page, *, full=False):
        async with timeout(self.config.timeout):
            if full or page != self.page:
                await self.ws.send("GET;" + self.navigation[page])
                self.snapshot = content(await self.receive(), page)
                self.page = page
            else:
                await self.ws.send("REFRESH")
                self.snapshot = refresh(await self.receive(), self.snapshot)
        return self.snapshot

    async def save(self, reading, wire_value):
        # SET stages a value without a reply; SAVE returns Content on observed firmware.
        # Never automatically retry either operation after an uncertain transport failure.
        async with timeout(self.config.timeout):
            await self.ws.send("SET;set_" + reading.identifier + ";" + wire_value)
            await self.ws.send("SAVE;1")
            self.snapshot = content(await self.receive(), self.page)
        return await self.read(self.page, full=True)

    async def __aexit__(self, *exc):
        self.page = self.snapshot = None
        await self.connection.__aexit__(*exc)


def selected(snapshot, spec):
    if spec.position is None:
        return snapshot.values.get(spec.path)
    matches = [r for p, r in snapshot.values.items() if p[:-1] == spec.path[:-1]]
    return matches[spec.position - 1] if len(matches) >= spec.position else None


class Controller:
    def __init__(self, config, password):
        self.config, self.password = config, password
        self.cache = {}
        self.schedule_read = None

    async def __aenter__(self):
        self.stack = AsyncExitStack()
        try:
            self.primary = await self.stack.enter_async_context(Session(self.config, self.password))
            information = (self.config.information_label,)
            if information not in self.primary.navigation:
                raise ProtocolError("Controller language does not match configured mappings")
            self.pages = list(
                dict.fromkeys(
                    s.page for s in self.config.sensors if s.page in self.primary.navigation
                )
            )
            self.secondary = None
            if any(p != information for p in self.pages):
                self.secondary = await self.stack.enter_async_context(
                    Session(self.config, self.password)
                )
            self.information = information
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    def session_for(self, page):
        return self.primary if page == self.information else self.secondary

    def values(self):
        result = {}
        for spec in self.config.sensors:
            snapshot = self.cache.get(spec.page)
            if snapshot is not None:
                reading = selected(snapshot, spec)
                if reading is not None:
                    result[spec.key] = reading
        return result

    async def sample(self):
        due = (
            self.schedule_read is None
            or time.monotonic() - self.schedule_read >= self.config.schedules_interval
        )
        for page in self.pages:
            if len(page) > 1 and not due:
                continue
            session = self.session_for(page)
            if page not in session.navigation:
                raise ProtocolError("Session navigation changed")
            self.cache[page] = await session.read(page, full=due)
        if due:
            self.schedule_read = time.monotonic()
            # Return the secondary session to settings, enabling REFRESH between schedule scans.
            settings = next((p for p in self.pages if p != self.information and len(p) == 1), None)
            if settings and self.secondary.page != settings:
                self.cache[settings] = await self.secondary.read(settings)
        return self.values()

    async def write(self, spec, payload):
        if not self.config.writes or spec.page not in self.pages:
            raise CommandError("read_only")
        session = self.session_for(spec.page)
        snapshot = await session.read(spec.page, full=True)
        self.cache[spec.page] = snapshot
        reading = selected(snapshot, spec)
        wire, expected = encode_command(spec, reading, payload)
        actual = normalize(spec, reading, writes=self.config.writes)
        if actual["value"] == expected and actual["quality"] == "good":
            return "unchanged"
        snapshot = await session.save(reading, wire)
        self.cache[spec.page] = snapshot
        actual = normalize(spec, selected(snapshot, spec), writes=self.config.writes)
        if actual["quality"] != "good" or actual["value"] != expected:
            raise CommandError("readback_mismatch")
        if len(spec.page) > 1:
            self.schedule_read = None  # Schedule views can refer to the same underlying week.
        return "applied"

    async def idle(self, delay):
        tasks = [asyncio.create_task(self.primary.ws.wait_closed())]
        if self.secondary:
            tasks.append(asyncio.create_task(self.secondary.ws.wait_closed()))
        try:
            done, _ = await asyncio.wait(tasks, timeout=delay, return_when=asyncio.FIRST_COMPLETED)
            if done:
                raise ProtocolError("Controller disconnected")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def __aexit__(self, *exc):
        self.cache.clear()
        await self.stack.__aexit__(*exc)
