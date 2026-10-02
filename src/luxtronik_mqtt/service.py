"""Reconnect and freshness lifecycle; no sample queue or stale replay."""

import asyncio
import contextlib
import logging
import random
import time

import aiomqtt
from websockets.exceptions import WebSocketException

from .compat import timeout
from .config import ConfigError, Secrets, Settings
from .controller import Controller
from .model import normalize, utc_now
from .protocol import AuthenticationError, ProtocolError
from .publisher import Publisher, mqtt_client

LOG = logging.getLogger(__name__)
CONTROLLER_ERRORS = (OSError, asyncio.TimeoutError, ProtocolError, WebSocketException)


def retry_delay(attempt: int, *, authentication: bool = False) -> float:
    floor = 30 if authentication else min(2 ** min(attempt, 6), 48)
    return min(60, random.uniform(floor, floor * 1.25))


async def controller_loop(
    config,
    secrets,
    publisher,
    *,
    once=False,
    controller_factory=Controller,
    on_success=None,
    stopping=None,
):
    stopping = stopping or asyncio.Event()
    attempt = 0
    while not stopping.is_set():
        try:
            async with controller_factory(config, secrets.controller) as controller:
                last_success = None
                while not stopping.is_set():
                    start = time.monotonic()
                    remaining = (
                        config.stale
                        if last_success is None
                        else (config.stale - (start - last_success))
                    )
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    async with timeout(remaining):
                        raw = await controller.sample()
                        if stopping.is_set():
                            return
                        observed = utc_now()
                        values = {
                            s.key: normalize(s, raw.get(s.path), observed) for s in config.sensors
                        }
                        await publisher.cycle(values)
                        if stopping.is_set():
                            return
                        await publisher.availability(True)
                    last_success = time.monotonic()
                    attempt = 0
                    if on_success is not None:
                        on_success()
                    LOG.info("Published %d readings", len(values))
                    if once or stopping.is_set():
                        return
                    await controller.idle(max(0, config.poll - (time.monotonic() - start)))
        except CONTROLLER_ERRORS as exc:
            # Never log exception text: transport errors can contain frame contents.
            await publisher.availability(False)
            if stopping.is_set():
                return
            LOG.warning("Controller unavailable (%s)", type(exc).__name__)
            if once:
                raise
            await asyncio.sleep(
                retry_delay(attempt, authentication=isinstance(exc, AuthenticationError))
            )
            attempt += 1


async def _watch_broker(client):
    # No subscriptions; the iterator unblocks on broker disconnection.
    async for _ in client.messages:
        pass
    raise aiomqtt.MqttError("Broker disconnected")


async def _connected(config, secrets, client, *, once, on_success=None):
    # Older asyncio.wait_for implementations (also used inside MQTT libraries)
    # can consume cancellation when an acknowledgement races with shutdown.
    # A cooperative flag prevents the polling worker from starting another cycle.
    stopping = asyncio.Event()
    publisher = Publisher(client, config, stopping)
    await publisher.availability(False)
    tasks = []
    try:
        await publisher.prepare()
        worker = asyncio.create_task(
            controller_loop(
                config, secrets, publisher, once=once, on_success=on_success, stopping=stopping
            )
        )
        watcher = asyncio.create_task(_watch_broker(client))
        tasks = [worker, watcher]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Prefer broker errors if both tasks completed simultaneously.
        for task in (watcher, worker):
            if task in done:
                task.result()
    finally:
        stopping.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(aiomqtt.MqttError, asyncio.TimeoutError):
            await asyncio.wait_for(publisher.availability(False), 3)


async def run(config: Settings, secrets: Secrets, *, once=False):
    if not config.sensors:
        raise ConfigError("Configure at least one sensor before publishing")
    attempt = 0

    def succeeded():
        nonlocal attempt
        attempt = 0

    while True:
        try:
            async with mqtt_client(config, secrets) as client:
                await _connected(config, secrets, client, once=once, on_success=succeeded)
                return
        except (aiomqtt.MqttError, OSError, asyncio.TimeoutError) as exc:
            LOG.warning("Broker unavailable (%s)", type(exc).__name__)
            if once:
                raise
            # MQTT reconnect always creates a new controller session and fresh cycle.
            await asyncio.sleep(retry_delay(attempt))
            attempt += 1
