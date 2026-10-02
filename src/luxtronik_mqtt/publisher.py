"""MQTT contract and namespace-scoped retained topic bookkeeping."""

import json
import logging
import re
import ssl
from pathlib import Path

import aiomqtt

from .config import ConfigError, Secrets, Settings

MQTT_LOG = logging.Logger("mqtt_wire_disabled")
MQTT_LOG.disabled = True


def mqtt_client(config: Settings, secrets: Secrets):
    context = ssl.create_default_context(cafile=config.ca_file) if config.mqtt_tls else None
    return aiomqtt.Client(
        config.mqtt_host,
        config.mqtt_port,
        username=secrets.username,
        password=secrets.password,
        identifier=config.client_id,
        protocol=aiomqtt.ProtocolVersion.V311,
        clean_session=True,
        tls_context=context,
        timeout=config.timeout,
        keepalive=30,
        will=aiomqtt.Will(config.prefix + "/availability", "offline", qos=1, retain=True),
        max_queued_outgoing_messages=1,
        max_inflight_messages=1,
        max_concurrent_outgoing_calls=1,
        max_queued_incoming_messages=1,
        logger=MQTT_LOG,
    )


class Publisher:
    def __init__(self, client, config: Settings, stopping=None):
        self.client, self.config = client, config
        self.stopping = stopping
        self.manifest = config.state_dir / "published-topics.json"

    async def send(self, suffix: str, payload):
        await self.client.publish(self.config.prefix + "/" + suffix, payload, qos=1, retain=True)

    async def availability(self, online: bool):
        await self.send("availability", "online" if online else "offline")

    async def prepare(self):
        """Journal intended publications before sending, for recovery after a crash."""
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        prior = set()
        if self.manifest.exists():
            try:
                if self.manifest.stat().st_size > 65536:
                    raise ValueError
                data = json.loads(self.manifest.read_text(encoding="utf-8"))
                if data["prefix"] != self.config.prefix:
                    raise ValueError
                keys = data["keys"]
                if (
                    not isinstance(keys, list)
                    or len(keys) > 512
                    or any(
                        not isinstance(k, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", k)
                        for k in keys
                    )
                ):
                    raise ValueError
                prior = set(keys)
            except (ValueError, KeyError, TypeError, OSError):
                raise ConfigError(
                    "Invalid topic manifest or changed namespace; use a new state_dir"
                ) from None
        current = {s.key for s in self.config.sensors}
        for key in sorted(prior - current):
            await self.send("readings/" + key, b"")
        temporary = Path(str(self.manifest) + ".tmp")
        temporary.write_text(
            json.dumps({"prefix": self.config.prefix, "keys": sorted(current)}), encoding="utf-8"
        )
        temporary.replace(self.manifest)
        await self.send(
            "metadata",
            json.dumps(
                {
                    "schema_version": 1,
                    "device_id": self.config.device_id,
                    "sensors": {
                        s.key: {"unit": s.unit, "type": s.type} for s in self.config.sensors
                    },
                },
                allow_nan=False,
            ),
        )

    async def cycle(self, values: dict):
        for key, reading in values.items():
            if self.stopping is not None and self.stopping.is_set():
                return
            await self.send("readings/" + key, json.dumps(reading, allow_nan=False))
