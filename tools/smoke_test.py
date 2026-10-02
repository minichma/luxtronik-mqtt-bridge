"""Publish one live sample, verify delivery, then leave retained availability offline."""

import argparse
import asyncio
import json
import ssl
from pathlib import Path

import aiomqtt

from luxtronik_mqtt.compat import run_async
from luxtronik_mqtt.config import load_config, load_secrets
from luxtronik_mqtt.service import run


async def smoke(path):
    config = load_config(path)
    secrets = load_secrets(config)
    context = ssl.create_default_context(cafile=config.ca_file) if config.mqtt_tls else None
    async with aiomqtt.Client(
        config.mqtt_host,
        config.mqtt_port,
        username=secrets.username,
        password=secrets.password,
        tls_context=context,
        identifier=config.client_id + "-verify",
    ) as client:
        await client.subscribe(config.prefix + "/#", qos=1)
        received = {}
        statuses = []

        async def collect():
            async for message in client.messages:
                if message.retain:
                    continue  # Ignore values predating this run.
                topic = str(message.topic)
                if topic.startswith(config.prefix + "/readings/"):
                    received[topic.rsplit("/", 1)[-1]] = json.loads(message.payload)
                elif topic == config.prefix + "/availability":
                    statuses.append(bytes(message.payload).decode())
                    if statuses[-2:] == ["online", "offline"]:
                        return

        collector = asyncio.create_task(collect())
        try:
            await run(config, secrets, once=True)
            await asyncio.wait_for(collector, 10)
        finally:
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
        assert set(received) == {s.key for s in config.sensors}
        assert all(v["quality"] == "good" for v in received.values())
        print(json.dumps({"verified_readings": received, "availability": statuses}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_async(smoke(args.config))
    except Exception as exc:
        print("Smoke test failed:", type(exc).__name__)
        raise SystemExit(1) from None
