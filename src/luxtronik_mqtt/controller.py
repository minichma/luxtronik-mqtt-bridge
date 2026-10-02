"""One read-only session, no persistent protocol IDs or arbitrary commands."""

import asyncio
import logging

from websockets.asyncio.client import connect

from .compat import timeout
from .config import Settings
from .protocol import ProtocolError, decode, information_id, readings

# WebSocket debug logging includes outgoing authentication frames. Use a private,
# permanently disabled logger even if the host enables root DEBUG logging.
WIRE_LOG = logging.Logger("luxtronik_wire_disabled")
WIRE_LOG.disabled = True


class Controller:
    def __init__(self, config: Settings, password: str):
        self.config = config
        self._password = password
        self._ws = None
        self._information_id = None

    async def __aenter__(self):
        c = self.config
        self._connection = connect(
            c.url,
            subprotocols=["Lux_WS"],
            proxy=None,
            compression=None,
            open_timeout=c.timeout,
            close_timeout=2,
            ping_interval=20,
            ping_timeout=c.timeout,
            max_size=c.max_frame,
            max_queue=4,
            logger=WIRE_LOG,
        )
        self._ws = await self._connection.__aenter__()
        try:
            if self._ws.subprotocol != "Lux_WS":
                raise ProtocolError("Lux_WS subprotocol was not negotiated")
            async with timeout(c.timeout):
                await self._ws.send("LOGIN;" + self._password)
                self._information_id = information_id(
                    decode(await self._ws.recv(), c.max_frame), c.information_label
                )
        except BaseException:
            await self._connection.__aexit__(None, None, None)
            raise
        return self

    async def sample(self):
        async with timeout(self.config.timeout):
            await self._ws.send("GET;" + self._information_id)
            root = decode(await self._ws.recv(), self.config.max_frame)
            return readings(root, self.config.information_label)

    async def idle(self, delay: float):
        """Notice controller disconnects even while waiting for the next poll."""
        try:
            async with timeout(delay):
                await self._ws.wait_closed()
        except asyncio.TimeoutError:
            return
        raise ProtocolError("Controller disconnected")

    async def __aexit__(self, *exc):
        await self._connection.__aexit__(*exc)
        self._information_id = None
