import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace

import aiomqtt
import pytest

from luxtronik_mqtt.config import Secrets
from luxtronik_mqtt.service import run

from .broker import Broker
from .fake_controller import FakeController


@pytest.fixture
async def broker(tmp_path):
    instance = Broker(tmp_path)
    try:
        await instance.start()
        yield instance
    finally:
        await instance.stop()


async def receive_until(client, predicate, seconds=8):
    async with asyncio.timeout(seconds):
        async for message in client.messages:
            if predicate(str(message.topic), bytes(message.payload)):
                return message


async def stop(task):
    task.cancel()
    async with asyncio.timeout(5):
        await asyncio.gather(task, return_exceptions=True)


async def test_mqtt5_changes_scalar_writes_retention_and_shutdown(
    config, fixture_dir, broker, caplog
):
    async with FakeController(fixture_dir) as fake:
        c = replace(
            config,
            url=f"ws://127.0.0.1:{fake.port}",
            mqtt_host="127.0.0.1",
            mqtt_port=broker.port,
            timeout=2,
            poll=0.2,
            stale=5,
        )
        key = "settings/temperatures/loweringto"
        root = c.prefix + "/" + key
        async with aiomqtt.Client(
            "127.0.0.1", broker.port, protocol=aiomqtt.ProtocolVersion.V5
        ) as subscriber:
            await subscriber.subscribe(c.prefix + "/#", qos=1)
            # A retained command from before connection must never be executed.
            await subscriber.publish(root + "/value", "-18", qos=1, retain=True)
            service = asyncio.create_task(run(c, Secrets("test-only")))
            try:
                await receive_until(
                    subscriber, lambda t, p: t.endswith("/availability") and p == b"online"
                )
                await asyncio.sleep(0.6)
                assert fake.saved == 0  # own scalar echoes and retained commands are ignored
                # Unchanged REFRESH cycles must not republish reading JSON or scalar values.
                with pytest.raises(TimeoutError):
                    await receive_until(subscriber, lambda t, p: t == root, seconds=0.3)
                await subscriber.publish(root + "/value", "-19.5", qos=1, retain=False)
                await receive_until(
                    subscriber,
                    lambda t, p: t == root + "/result" and json.loads(p)["status"] == "applied",
                )
                assert fake.saved == 1
                # Invalid writes cannot cause SET and get a bounded, explicit result.
                await subscriber.publish(root + "/value", "1000", qos=1, retain=False)
                await receive_until(
                    subscriber, lambda t, p: t == root + "/result" and b"outside_allowed" in p
                )
                assert fake.saved == 1
                # Live retained writes preserve their retain flag under MQTT 5 and are rejected.
                await subscriber.publish(root + "/value", "-18", qos=1, retain=True)
                await receive_until(
                    subscriber,
                    lambda t, p: t == root + "/result" and b"retained_command_rejected" in p,
                )
                assert fake.saved == 1
                async with aiomqtt.Client("127.0.0.1", broker.port) as late:
                    await late.subscribe(root + "/value", qos=1)
                    message = await receive_until(late, lambda *_: True)
                    assert message.retain and message.payload == b"-19.5"
                fake.drop_save_reply = True
                await subscriber.publish(root + "/value", "-19", qos=1, retain=False)
                await receive_until(
                    subscriber, lambda t, p: t == root + "/result" and b"outcome_unknown" in p
                )
                await receive_until(
                    subscriber, lambda t, p: t.endswith("/availability") and p == b"online"
                )
                assert fake.saved == 2  # Applied once, never retried after the lost response.
                # A true controller change is published with its hierarchy intact.
                fake.set_value("Vorlauf", "42.5°C")
                topic = c.prefix + "/information/temperatures/flow"
                await receive_until(
                    subscriber, lambda t, p: t == topic and json.loads(p)["value"] == 42.5
                )
                assert not any("Published" in r.message for r in caplog.records)
                await stop(service)
                await receive_until(
                    subscriber, lambda t, p: t.endswith("/availability") and p == b"offline"
                )
            finally:
                await stop(service)


async def test_broker_restart_discards_state_and_rediscover(
    config, fixture_dir, broker, monkeypatch
):
    monkeypatch.setattr("luxtronik_mqtt.service.retry_delay", lambda *a, **k: 0.05)
    async with FakeController(fixture_dir) as fake:
        c = replace(
            config,
            url=f"ws://127.0.0.1:{fake.port}",
            mqtt_host="127.0.0.1",
            mqtt_port=broker.port,
            timeout=1,
        )
        service = asyncio.create_task(run(c, Secrets("test")))
        try:
            async with aiomqtt.Client("127.0.0.1", broker.port) as subscriber:
                await subscriber.subscribe(c.prefix + "/availability", qos=1)
                await receive_until(subscriber, lambda t, p: p == b"online")
            await broker.stop()
            fake.set_value("Vorlauf", "31.5°C")
            await broker.start()
            async with aiomqtt.Client("127.0.0.1", broker.port) as subscriber:
                await subscriber.subscribe(c.prefix + "/information/temperatures/flow", qos=1)
                await receive_until(subscriber, lambda t, p: json.loads(p)["value"] == 31.5)
            assert fake.connections >= 4
        finally:
            await stop(service)


async def test_crash_last_will(config_files, fixture_dir, broker, tmp_path):
    async with FakeController(fixture_dir) as fake:
        base = config_files / "base.toml"
        text = (
            base.read_text("utf-8")
            .replace("mqtt.example.invalid", "127.0.0.1")
            .replace("port = 1883", f"port = {broker.port}")
        )
        base.write_text(text, encoding="utf-8")
        device = config_files / "device.toml"
        device.write_text(
            device.read_text("utf-8").replace(
                "ws://192.0.2.10:8214/", f"ws://127.0.0.1:{fake.port}/"
            ),
            encoding="utf-8",
        )
        password = tmp_path / "secret"
        password.write_text("test-only")
        env = dict(os.environ, LUXTRONIK_PASSWORD_FILE=str(password))
        process = None
        async with aiomqtt.Client("127.0.0.1", broker.port) as subscriber:
            await subscriber.subscribe("luxtronik/test/availability", qos=1)
            try:
                process = subprocess.Popen(
                    [sys.executable, "-m", "luxtronik_mqtt", "--config", str(device), "run"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                await receive_until(subscriber, lambda t, p: p == b"online", seconds=15)
                process.kill()
                await receive_until(subscriber, lambda t, p: p == b"offline")
            finally:
                if process and process.poll() is None:
                    process.kill()
                if process:
                    process.wait(timeout=5)
        async with aiomqtt.Client("127.0.0.1", broker.port) as late:
            await late.subscribe("luxtronik/test/availability", qos=1)
            message = await receive_until(late, lambda *_: True)
            assert message.retain and message.payload == b"offline"
