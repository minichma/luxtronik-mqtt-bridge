"""Verify fresh complete cycles from an already-running bridge; never publish."""

import argparse
import json
import ssl
from datetime import datetime, timezone
from pathlib import Path

import aiomqtt

from luxtronik_mqtt.compat import run_async, timeout
from luxtronik_mqtt.config import load_config, secret_file


async def observe(path, cycles):
    config = load_config(path)
    username = password = None
    if config.mqtt_auth == "password":
        username = secret_file(config.username_env, "mqtt-username")
        password = secret_file(config.mqtt_password_env, "mqtt-password")
    context = ssl.create_default_context(cafile=config.ca_file) if config.mqtt_tls else None
    expected = {s.key for s in config.sensors}
    observed = {}
    completed = set()
    online = False
    async with aiomqtt.Client(
        config.mqtt_host,
        config.mqtt_port,
        username=username,
        password=password,
        tls_context=context,
        identifier=config.client_id + "-observe",
    ) as client:
        await client.subscribe(config.prefix + "/#", qos=1)
        async with timeout(config.poll * (cycles + 1) + 10):
            async for message in client.messages:
                topic = str(message.topic)
                if topic == config.prefix + "/availability":
                    online = message.payload == b"online"
                elif topic.startswith(config.prefix + "/readings/") and not message.retain:
                    reading = json.loads(message.payload)
                    stamp = reading["observed_at"]
                    age = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    ).total_seconds()
                    if reading["quality"] != "good" or not -5 <= age <= config.stale:
                        raise ValueError("Invalid or stale reading")
                    # Discard incomplete older cycles; keep memory bounded.
                    if observed and stamp not in observed:
                        observed.clear()
                    observed.setdefault(stamp, set()).add(topic.rsplit("/", 1)[-1])
                for stamp, keys in observed.items():
                    if online and expected <= keys:
                        completed.add(stamp)
                if len(completed) >= cycles:
                    print(
                        json.dumps(
                            {
                                "fresh_cycles": len(completed),
                                "readings_per_cycle": len(expected),
                                "online": online,
                                "timestamps": sorted(completed),
                            }
                        )
                    )
                    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=2, choices=range(1, 11))
    args = parser.parse_args()
    try:
        run_async(observe(args.config, args.cycles))
    except Exception as exc:
        print("Delivery verification failed:", type(exc).__name__)
        raise SystemExit(1) from None
