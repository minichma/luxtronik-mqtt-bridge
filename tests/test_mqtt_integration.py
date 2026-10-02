import asyncio
import contextlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import aiomqtt
import pytest
from amqtt.broker import Broker
from websockets.asyncio.server import serve

from luxtronik_mqtt.config import Secrets
from luxtronik_mqtt.service import run


async def start_broker(port=0):
    broker = Broker(
        {
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
            "plugins": {
                "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}
            },
        }
    )
    await broker.start()
    actual_port = broker._servers["default"].instance.sockets[0].getsockname()[1]
    return broker, actual_port


@pytest.fixture
async def broker():
    instance, port = await start_broker()
    try:
        yield port
    finally:
        await instance.shutdown()


async def receive_until(client, predicate, timeout=5):
    async with asyncio.timeout(timeout):
        async for message in client.messages:
            if predicate(str(message.topic), bytes(message.payload)):
                return message


async def test_full_bridge_retained_and_orderly_shutdown(config, fixture_dir, broker):
    async def controller(ws):
        assert await ws.recv() == "LOGIN;test-only"
        await ws.send((fixture_dir / "navigation.xml").read_text("utf-8"))
        async for command in ws:
            assert command == "GET;0x100"
            await ws.send((fixture_dir / "information.xml").read_text("utf-8"))

    async with serve(controller, "127.0.0.1", 0, subprotocols=["Lux_WS"]) as server:
        c = replace(
            config,
            mqtt_host="127.0.0.1",
            mqtt_port=broker,
            url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
            timeout=2,
        )
        async with aiomqtt.Client("127.0.0.1", broker) as subscriber:
            await subscriber.subscribe(c.prefix + "/#", qos=1)
            await run(c, Secrets("test-only"), once=True)
            events = []
            async with asyncio.timeout(5):
                async for message in subscriber.messages:
                    events.append((str(message.topic), bytes(message.payload)))
                    if len(events) > 2 and events[-1] == (c.prefix + "/availability", b"offline"):
                        break
            assert events[0] == (c.prefix + "/availability", b"offline")
            assert events[-2:] == [
                (c.prefix + "/availability", b"online"),
                (c.prefix + "/availability", b"offline"),
            ]
            values = [json.loads(p) for t, p in events if "/readings/" in t]
            assert len(values) == len(c.sensors)
            assert all(v["quality"] == "good" and v["observed_at"].endswith("Z") for v in values)
        # A new subscriber sees retained state, including offline after one-shot exit.
        async with aiomqtt.Client("127.0.0.1", broker) as late:
            await late.subscribe(c.prefix + "/readings/outdoor_temperature", qos=1)
            message = await receive_until(
                late, lambda t, p: t == c.prefix + "/readings/outdoor_temperature"
            )
            assert message.retain
            assert json.loads(message.payload)["value"] == 17.0


async def test_crashed_bridge_emits_retained_last_will(config, fixture_dir, broker, tmp_path):
    async def controller(ws):
        await ws.recv()
        await ws.send((fixture_dir / "navigation.xml").read_text("utf-8"))
        with contextlib.suppress(Exception):
            async for _ in ws:
                await ws.send((fixture_dir / "information.xml").read_text("utf-8"))

    async with serve(controller, "127.0.0.1", 0, subprotocols=["Lux_WS"]) as server:
        text = (Path(__file__).parents[1] / "config/bridge.example.toml").read_text("utf-8")
        text = (
            text.replace("192.0.2.10:8214", f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
            .replace("mqtt.example.invalid", "127.0.0.1")
            .replace("port = 8883", f"port = {broker}")
            .replace("tls = true", "tls = false")
            .replace('authentication = "password"', 'authentication = "none"')
            .replace("/var/lib/luxtronik-mqtt-bridge", (tmp_path / "state").as_posix())
        )
        path = tmp_path / "child.toml"
        path.write_text(text, encoding="utf-8")
        password = tmp_path / "secret"
        password.write_text("test-only")
        env = dict(os.environ, LUXTRONIK_PASSWORD_FILE=str(password))
        async with aiomqtt.Client("127.0.0.1", broker) as subscriber:
            await subscriber.subscribe(config.prefix + "/availability", qos=1)
            process = subprocess.Popen(
                [sys.executable, "-m", "luxtronik_mqtt", "--config", str(path), "run"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            try:
                await receive_until(subscriber, lambda t, p: p == b"online")
                process.kill()
                await receive_until(subscriber, lambda t, p: p == b"offline")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        async with aiomqtt.Client("127.0.0.1", broker) as late:
            await late.subscribe(config.prefix + "/availability", qos=1)
            message = await receive_until(late, lambda *_: True)
            assert message.retain and message.payload == b"offline"


async def test_broker_restart_collects_fresh_values(config, fixture_dir, monkeypatch):
    monkeypatch.setattr("luxtronik_mqtt.service.retry_delay", lambda *a, **k: 0.05)
    connections = 0

    async def controller(ws):
        nonlocal connections
        connections += 1
        current = connections
        await ws.recv()
        await ws.send((fixture_dir / "navigation.xml").read_text("utf-8"))
        with contextlib.suppress(Exception):
            async for _ in ws:
                content = (fixture_dir / "information.xml").read_text("utf-8")
                await ws.send(content.replace("17.0°C", f"{current}.0°C"))

    broker, port = await start_broker()
    service = None
    try:
        async with serve(controller, "127.0.0.1", 0, subprotocols=["Lux_WS"]) as server:
            c = replace(
                config,
                mqtt_host="127.0.0.1",
                mqtt_port=port,
                timeout=1,
                url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
            )
            async with aiomqtt.Client("127.0.0.1", port) as subscriber:
                await subscriber.subscribe(c.prefix + "/availability", qos=1)
                service = asyncio.create_task(run(c, Secrets("test-only")))
                await receive_until(subscriber, lambda t, p: p == b"online")
            await asyncio.wait_for(broker.shutdown(), 5)
            broker, _ = await start_broker(port)
            async with aiomqtt.Client("127.0.0.1", port) as subscriber:
                await subscriber.subscribe(c.prefix + "/readings/outdoor_temperature", qos=1)
                message = await receive_until(subscriber, lambda t, p: json.loads(p)["value"] >= 2)
                assert json.loads(message.payload)["quality"] == "good"
            assert connections >= 2
            service.cancel()
            async with asyncio.timeout(5):
                await asyncio.gather(service, return_exceptions=True)
    finally:
        if service is not None:
            service.cancel()
            await asyncio.gather(service, return_exceptions=True)
        await broker.shutdown()
