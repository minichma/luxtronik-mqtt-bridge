import asyncio
import json
from dataclasses import replace

import pytest

from luxtronik_mqtt.config import ConfigError, Secrets
from luxtronik_mqtt.protocol import ProtocolError
from luxtronik_mqtt.publisher import Publisher
from luxtronik_mqtt.service import controller_loop, retry_delay


class RecordingPublisher:
    def __init__(self):
        self.events = []

    async def availability(self, online):
        self.events.append(("availability", online))

    async def cycle(self, values, **kwargs):
        self.events.append(("cycle", values))


async def test_stalled_cycle_goes_offline(config):
    class StalledController:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def sample(self):
            await asyncio.sleep(30)

    publisher = RecordingPublisher()
    with pytest.raises(TimeoutError):
        await controller_loop(
            replace(config, stale=0.05),
            Secrets("test"),
            publisher,
            once=True,
            controller_factory=StalledController,
        )
    assert publisher.events == [("availability", False)]


async def test_disconnect_retries_and_uses_new_sample(config, monkeypatch):
    connections = 0
    finished = asyncio.Event()

    class RecoveringController:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            nonlocal connections
            connections += 1
            if connections == 1:
                raise ProtocolError("synthetic failure")
            return self

        async def __aexit__(self, *_):
            pass

        async def sample(self):
            return {}

        async def idle(self, *_):
            finished.set()
            await asyncio.sleep(30)

    monkeypatch.setattr("luxtronik_mqtt.service.retry_delay", lambda *a, **k: 0)
    publisher = RecordingPublisher()
    task = asyncio.create_task(
        controller_loop(config, Secrets("test"), publisher, controller_factory=RecoveringController)
    )
    await asyncio.wait_for(finished.wait(), 1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert connections == 2
    assert [e[0] for e in publisher.events] == ["availability", "cycle", "availability"]
    assert publisher.events[0][1] is False
    assert publisher.events[-1][1] is True
    assert all(v["quality"] == "unavailable" for v in publisher.events[1][1].values())


def test_retry_is_bounded_and_authentication_is_slower():
    assert 1 <= retry_delay(0) <= 1.25
    assert 30 <= retry_delay(0, authentication=True) <= 37.5
    assert 48 <= retry_delay(99999) <= 60


async def test_shutdown_after_library_consumes_cancellation(config):
    started = asyncio.Event()
    stopping = asyncio.Event()

    class Controller:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def sample(self):
            return {}

        async def idle(self, *_):
            pytest.fail("A cancelled worker must not start another polling interval")

    class RacingPublisher(RecordingPublisher):
        async def cycle(self, values, **kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                pass  # Simulate an old asyncio/MQTT acknowledgement race.

    publisher = RacingPublisher()
    task = asyncio.create_task(
        controller_loop(
            config, Secrets("test"), publisher, controller_factory=Controller, stopping=stopping
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    stopping.set()
    task.cancel()
    async with asyncio.timeout(1):
        await task
    assert publisher.events == []


async def test_manifest_cleanup_is_scoped_and_change_only(config):
    class Client:
        def __init__(self):
            self.sent = []

        async def publish(self, topic, payload, **kwargs):
            self.sent.append((topic, payload, kwargs))

    client = Client()
    config.state_dir.mkdir(parents=True)
    manifest = config.state_dir / "published-topics.json"
    manifest.write_text(json.dumps({"prefix": config.prefix, "keys": ["old/sensor"]}))
    publisher = Publisher(client, config)
    key = config.sensors[0].key
    reading = {
        "value": 1,
        "quality": "good",
        "observed_at": "old",
        "unit": "degC",
        "path": ["actual", "path"],
        "writable": False,
        "possible_values": None,
    }
    await publisher.cycle({key: reading})
    assert client.sent[0][:2] == (config.prefix + "/old/sensor", b"")
    assert client.sent[1][:2] == (config.prefix + "/old/sensor/value", b"")
    client.sent.clear()
    await publisher.cycle({key: dict(reading, observed_at="new")})
    assert not client.sent
    await publisher.cycle({key: dict(reading, value=2)})
    assert len(client.sent) == 2
    client.sent.clear()
    await publisher.cycle({key: dict(reading, value=2, writable=True)})
    assert len(client.sent) == 1  # metadata change doesn't duplicate scalar state
    await publisher.availability(True)
    count = len(client.sent)
    await publisher.availability(True)
    assert len(client.sent) == count
    for keys in (["../../other"], ["x/#"], "not-a-list"):
        manifest.write_text(json.dumps({"prefix": config.prefix, "keys": keys}))
        client.sent.clear()
        with pytest.raises(ConfigError):
            await Publisher(client, config).prepare({key: reading})
        assert not client.sent


def test_rate_limited_error_only_logging(monkeypatch):
    import logging

    from luxtronik_mqtt.logging_config import RateLimit

    current = [0]
    monkeypatch.setattr("luxtronik_mqtt.logging_config.time.monotonic", lambda: current[0])
    limiter = RateLimit()
    record = logging.LogRecord("service", logging.WARNING, "", 1, "error", (), None)
    assert limiter.filter(record)
    assert not limiter.filter(record)
    current[0] = 61
    assert limiter.filter(record)


def test_log_rotation_bounds_disk_use(tmp_path):
    import logging

    from luxtronik_mqtt.logging_config import configure

    old = logging.getLogger().handlers[:]
    try:
        configure(tmp_path)
        handler = logging.getLogger().handlers[0]
        record = logging.LogRecord("test", logging.WARNING, "", 1, "x" * 16000, (), None)
        for _ in range(400):
            handler.emit(record)  # Exercise rotation independently of the rate limiter.
        handler.close()
        files = list(tmp_path.glob("bridge.log*"))
        assert len(files) == 3
        assert sum(p.stat().st_size for p in files) <= 3 * 1024 * 1024
    finally:
        logging.getLogger().handlers = old
