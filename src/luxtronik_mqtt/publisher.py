"""Change-only retained MQTT state and namespace-scoped topic bookkeeping."""

import json
import logging
import re
import ssl
from pathlib import Path

import aiomqtt
from paho.mqtt.subscribeoptions import SubscribeOptions

from .config import ConfigError, Secrets, Settings
from .model import scalar

MQTT_LOG = logging.Logger("mqtt_wire_disabled")
MQTT_LOG.disabled = True
TOPIC = re.compile(r"[a-z][a-z0-9]*(?:/[a-z0-9]+)+\Z")


def mqtt_client(config: Settings, secrets: Secrets):
    context = ssl.create_default_context(cafile=config.ca_file) if config.mqtt_tls else None
    return aiomqtt.Client(
        config.mqtt_host,
        config.mqtt_port,
        username=secrets.username,
        password=secrets.password,
        identifier=config.client_id,
        protocol=aiomqtt.ProtocolVersion.V5,
        tls_context=context,
        timeout=config.timeout,
        keepalive=30,
        will=aiomqtt.Will(config.prefix + "/availability", "offline", qos=1, retain=True),
        max_queued_outgoing_messages=8,
        max_inflight_messages=8,
        max_concurrent_outgoing_calls=8,
        max_queued_incoming_messages=64,
        logger=MQTT_LOG,
    )


async def subscribe_commands(client, config):
    if config.writes:
        # noLocal prevents our scalar state from becoming a write command. Preserve
        # retain flags and never replay retained messages into the command consumer.
        await client.subscribe(
            config.prefix + "/#",
            options=SubscribeOptions(qos=1, noLocal=True, retainAsPublished=True, retainHandling=2),
        )


class Publisher:
    def __init__(self, client, config: Settings, stopping=None):
        self.client, self.config = client, config
        self.stopping = stopping
        self.manifest = config.state_dir / "published-topics.json"
        self.last = {}
        self.online = None
        self.prepared = False

    async def send(self, suffix, payload, *, retain=True):
        await self.client.publish(self.config.prefix + "/" + suffix, payload, qos=1, retain=retain)

    async def availability(self, online):
        if online != self.online:
            await self.send("availability", "online" if online else "offline")
            self.online = online

    async def prepare(self, values):
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        prior = set()
        if self.manifest.exists():
            try:
                if self.manifest.stat().st_size > 262144:
                    raise ValueError
                data = json.loads(self.manifest.read_text(encoding="utf-8"))
                keys = data["keys"]
                if (
                    data["prefix"] != self.config.prefix
                    or not isinstance(keys, list)
                    or len(keys) > 2048
                    or any(not isinstance(k, str) or not TOPIC.fullmatch(k) for k in keys)
                ):
                    raise ValueError
                prior = set(keys)
            except (ValueError, KeyError, TypeError, OSError):
                raise ConfigError(
                    "Invalid topic manifest or changed namespace; use a new state_dir"
                ) from None
        current = set(values)
        for key in sorted(prior - current):
            await self.send(key, b"")
            await self.send(key + "/value", b"")
        temporary = Path(str(self.manifest) + ".tmp")
        temporary.write_text(
            json.dumps({"prefix": self.config.prefix, "keys": sorted(current)}), encoding="utf-8"
        )
        temporary.replace(self.manifest)
        await self.send(
            "metadata",
            json.dumps(
                {
                    "schema_version": 2,
                    "device_id": self.config.device_id,
                    "language": self.config.language,
                    "topics": sorted(current),
                },
                allow_nan=False,
            ),
        )
        self.prepared = True

    async def cycle(self, values, *, initial=False):
        if not self.prepared or initial:
            await self.prepare(values)
        for key, reading in values.items():
            if self.stopping is not None and self.stopping.is_set():
                return
            previous = self.last.get(key)
            semantic = {k: v for k, v in reading.items() if k != "observed_at"}
            if initial or previous is None or previous[0] != semantic:
                await self.send(key, json.dumps(reading, ensure_ascii=False, allow_nan=False))
                if (
                    initial
                    or previous is None
                    or any(previous[0][k] != semantic[k] for k in ("value", "quality"))
                ):
                    await self.send(key + "/value", scalar(reading["value"]))
                self.last[key] = (semantic, reading)

    async def command_result(self, key, status):
        await self.send(key + "/result", json.dumps({"status": status}), retain=False)

    async def restore_scalar(self, key):
        if key in self.last:
            await self.send(key + "/value", scalar(self.last[key][0]["value"]))
