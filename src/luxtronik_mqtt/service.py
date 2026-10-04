"""Polling, serialized command handling, reconnects, and bounded shutdown."""

import asyncio
import contextlib
import logging
import random
import time
from dataclasses import dataclass

import aiomqtt
from websockets.exceptions import WebSocketException

from .compat import timeout
from .config import ConfigError, Secrets, Settings
from .controller import Controller
from .model import normalize
from .protocol import AuthenticationError, CommandError, ProtocolError
from .publisher import Publisher, mqtt_client, subscribe_commands

LOG = logging.getLogger(__name__)
CONTROLLER_ERRORS = (OSError, asyncio.TimeoutError, ProtocolError, WebSocketException)


@dataclass(frozen=True)
class Command:
    key: str
    payload: bytes
    received: float


def retry_delay(attempt, *, authentication=False):
    floor = 30 if authentication else min(2 ** min(attempt, 6), 48)
    return min(60, random.uniform(floor, floor * 1.25))


def normalized(config, raw):
    return {
        s.key: normalize(s, raw[s.key], writes=config.writes)
        for s in config.sensors
        if s.key in raw
    }


async def wait_for_command(controller, commands, delay):
    idle = asyncio.create_task(controller.idle(delay))
    incoming = asyncio.create_task(commands.get())
    try:
        done, _ = await asyncio.wait((idle, incoming), return_when=asyncio.FIRST_COMPLETED)
        if idle in done:
            idle.result()
        if incoming in done:
            return incoming.result()
        return None
    finally:
        for task in (idle, incoming):
            task.cancel()
        await asyncio.gather(idle, incoming, return_exceptions=True)


async def controller_loop(
    config,
    secrets,
    publisher,
    *,
    once=False,
    controller_factory=Controller,
    on_success=None,
    stopping=None,
    commands=None,
    ready=None,
):
    stopping = stopping or asyncio.Event()
    commands = commands or asyncio.Queue(maxsize=16)
    ready = ready or asyncio.Event()
    attempt = 0
    specs = {s.key: s for s in config.sensors}
    while not stopping.is_set():
        try:
            async with controller_factory(config, secrets.controller) as controller:
                last_success = None
                initial = True
                while not stopping.is_set():
                    start = time.monotonic()
                    remaining = (
                        config.stale
                        if last_success is None
                        else config.stale - (start - last_success)
                    )
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    async with timeout(remaining):
                        raw = await controller.sample()
                        if stopping.is_set():
                            return
                        await publisher.cycle(normalized(config, raw), initial=initial)
                        if stopping.is_set():
                            return
                        await publisher.availability(True)
                    initial = False
                    last_success = time.monotonic()
                    ready.set()
                    attempt = 0
                    if on_success:
                        on_success()
                    if once:
                        return
                    deadline = start + config.poll
                    while not stopping.is_set() and time.monotonic() < deadline:
                        command = await wait_for_command(
                            controller, commands, deadline - time.monotonic()
                        )
                        if command is None:
                            break
                        if time.monotonic() - command.received > config.timeout:
                            await publisher.restore_scalar(command.key)
                            await publisher.command_result(command.key, "expired")
                            continue
                        try:
                            async with timeout(config.timeout * 3):
                                status = await controller.write(specs[command.key], command.payload)
                            await publisher.cycle(normalized(config, controller.values()))
                            await publisher.restore_scalar(command.key)
                            await publisher.command_result(command.key, status)
                        except CommandError as exc:
                            await publisher.restore_scalar(command.key)
                            await publisher.command_result(command.key, str(exc))
                            LOG.warning("Controller command rejected")
                        except CONTROLLER_ERRORS:
                            await publisher.command_result(command.key, "outcome_unknown")
                            raise
        except CONTROLLER_ERRORS as exc:
            ready.clear()
            # Never retain commands across controller sessions or retry uncertain writes.
            while not commands.empty():
                discarded = commands.get_nowait()
                await publisher.command_result(discarded.key, "disconnected")
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


async def watch_broker(client, config, publisher, commands, ready):
    allowed = {s.key for s in config.sensors}
    prefix = config.prefix + "/"
    async for message in client.messages:
        topic = str(message.topic)
        if not topic.startswith(prefix) or not topic.endswith("/value"):
            continue
        key = topic[len(prefix) : -len("/value")]
        if key not in allowed:
            continue
        if message.retain:
            await publisher.restore_scalar(key)
            await publisher.command_result(key, "retained_command_rejected")
            continue
        if not config.writes or not ready.is_set():
            await publisher.restore_scalar(key)
            await publisher.command_result(key, "offline")
            continue
        payload = bytes(message.payload)
        if not 1 <= len(payload) <= 256:
            await publisher.restore_scalar(key)
            await publisher.command_result(key, "invalid_payload")
            continue
        try:
            commands.put_nowait(Command(key, payload, time.monotonic()))
        except asyncio.QueueFull:
            await publisher.restore_scalar(key)
            await publisher.command_result(key, "busy")
    raise aiomqtt.MqttError("Broker disconnected")


async def _connected(config, secrets, client, *, once, on_success=None):
    stopping, ready = asyncio.Event(), asyncio.Event()
    publisher = Publisher(client, config, stopping)
    commands = asyncio.Queue(maxsize=16)
    await publisher.availability(False)
    tasks = []
    try:
        await subscribe_commands(client, config)
        worker = asyncio.create_task(
            controller_loop(
                config,
                secrets,
                publisher,
                once=once,
                on_success=on_success,
                stopping=stopping,
                commands=commands,
                ready=ready,
            )
        )
        watcher = asyncio.create_task(watch_broker(client, config, publisher, commands, ready))
        tasks = [worker, watcher]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in (watcher, worker):
            if task in done:
                task.result()
    finally:
        stopping.set()
        ready.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(aiomqtt.MqttError, asyncio.TimeoutError):
            await asyncio.wait_for(publisher.availability(False), 3)


async def run(config: Settings, secrets: Secrets, *, once=False):
    if not config.sensors:
        raise ConfigError("Configure at least one mapping")
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
            await asyncio.sleep(retry_delay(attempt))
            attempt += 1
