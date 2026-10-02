import logging
from dataclasses import replace

import pytest
from websockets.asyncio.server import serve

from luxtronik_mqtt.config import Sensor
from luxtronik_mqtt.controller import Controller
from luxtronik_mqtt.model import normalize
from luxtronik_mqtt.protocol import (
    AuthenticationError,
    ProtocolError,
    decode,
    information_id,
    readings,
)


def test_real_xml_shape(fixture_dir):
    nav = decode((fixture_dir / "navigation.xml").read_bytes())
    assert information_id(nav, "Informationen") == "0x100"
    raw = readings(decode((fixture_dir / "information.xml").read_bytes()), "Informationen")
    assert raw[("Temperaturen", "Außentemperatur")].values == ("17.0°C",)


@pytest.mark.parametrize(
    "frame",
    [
        '{"type":"Navigation"}',
        "<broken>",
        '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>',
        "<x>" * 35 + "</x>" * 35,
    ],
)
def test_rejects_unsafe_or_unknown_frames(frame):
    with pytest.raises(ProtocolError):
        decode(frame)


def test_partial_refresh_and_ambiguous_paths_rejected(fixture_dir):
    with pytest.raises(ProtocolError):
        readings(decode((fixture_dir / "refresh.xml").read_bytes()), "Informationen")
    raw = readings(
        decode(
            "<Content><name>Informationen</name>"
            "<item><name>x</name><value>1</value></item>"
            "<item><name>x</name><value>2</value></item></Content>"
        ),
        "Informationen",
    )
    assert raw[("x",)].ambiguous
    with pytest.raises(ProtocolError):
        normalize(Sensor("x", ("x",), "number"), raw[("x",)], "now")
    with pytest.raises(ProtocolError):
        decode("<x/>", max_bytes=1)


async def test_reconnect_rediscovers_ids_read_only_and_redacts(config, fixture_dir, caplog):
    commands = []
    connection_count = 0
    server_log = logging.Logger("test-server-silent")
    server_log.disabled = True

    async def handler(ws):
        nonlocal connection_count
        connection_count += 1
        identifier = f"0x{connection_count + 100:x}"
        login = await ws.recv()
        assert login == "LOGIN;TEST_SECRET"
        await ws.send(
            f'<Navigation><item id="{identifier}"><name>Informationen</name></item></Navigation>'
        )
        async for message in ws:
            commands.append(message)
            assert message == "GET;" + identifier
            await ws.send((fixture_dir / "information.xml").read_text("utf-8"))

    async with serve(handler, "127.0.0.1", 0, subprotocols=["Lux_WS"], logger=server_log) as server:
        port = server.sockets[0].getsockname()[1]
        local = replace(config, url=f"ws://127.0.0.1:{port}")
        with caplog.at_level(logging.DEBUG):
            for _ in range(2):
                async with Controller(local, "TEST_SECRET") as controller:
                    assert await controller.sample()
                    assert await controller.sample()
    assert commands == ["GET;0x65", "GET;0x65", "GET;0x66", "GET;0x66"]
    assert "TEST_SECRET" not in caplog.text


async def test_rejected_login(config):
    async def handler(ws):
        await ws.recv()
        await ws.send("<Error>synthetic rejection</Error>")

    async with serve(handler, "127.0.0.1", 0, subprotocols=["Lux_WS"]) as server:
        local = replace(config, url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        with pytest.raises(AuthenticationError):
            async with Controller(local, "test-only"):
                pytest.fail("Login rejection must not create a session")
