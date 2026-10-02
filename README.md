# Luxtronik MQTT bridge

A new, standalone project to expose readings from a Luxtronik 2.1 controller
through MQTT. It is particularly intended to work with FW 3.92+ where the
legacy TCP API on port 8889 has been removed.

Deploy as a systemd service on openHABian; run the same application in a Windows
console for testing.

Implemented and live-tested on **Luxtronik 2.1 V3.89.3 (German UI)**.
**FW 3.92 remains the target, not a verified compatibility claim.** The bridge
supports the observed XML protocol; unexpected formats fail explicitly.
Repository: [minichma/luxtronik-mqtt-bridge](https://github.com/minichma/luxtronik-mqtt-bridge).

The controller's legacy TCP API on port 8889 is unavailable, per the project
requirement. Use the WebSocket subprotocol `Lux_WS`; there will be no legacy
fallback. The verified endpoint is `ws://<controller>:8214/` on the test controller.

## Run

Python 3.9+. Copy [example configuration](config/bridge.example.toml) outside the
checkout. Set endpoints, secret-file environment variables, and an absolute state
directory. Initial mappings cover outdoor/flow/return temperatures, compressor
hours/starts/running status, and total heat/input energy on the test controller.

```sh
uv sync --locked --no-dev
uv run --locked --no-dev luxtronik-mqtt --config /absolute/path/bridge.toml check
uv run --locked --no-dev luxtronik-mqtt --config /absolute/path/bridge.toml discover
uv run --locked --no-dev luxtronik-mqtt --config /absolute/path/bridge.toml once
uv run --locked --no-dev luxtronik-mqtt --config /absolute/path/bridge.toml run
```

`check` makes no connections. `discover` lists paths without values. `once`
publishes one sample and exits offline. `run` polls every 30 seconds until stopped.
See [deployment](docs/deployment.md) for Windows helpers and the openHABian service.

MQTT topics: `luxtronik/<device_id>/v1/readings/<sensor_key>`, `/availability`, and
`/metadata`. Readings contain `value`, `unit`, `observed_at`, and `quality`, with
QoS 1 and retention. Consumers must check freshness as well as availability.
An [openHAB example](examples/openhab/README.md) includes this check.

## Project documents

- [AGENTS.md](AGENTS.md): architectural decisions and contributor rules.
- [PLAN.md](PLAN.md): milestones, acceptance criteria, and outstanding inputs.
- [Protocol research](docs/protocol-research.md): evidence and uncertainties.
- [Secrets](docs/secrets.md): credential storage and deployment policy.
- [Example configuration](config/bridge.example.toml): validated configuration
  contract, with reserved example addresses and no credentials.

## Data flow

```text
Luxtronik 2.1
    -> Lux_WS login + information GET -> mapped values -> normalization
    -> MQTT broker -> openHAB / other subscribers
```

Initial scope: temperatures, operating status, runtime counters, and energy
readings where the controller exposes them. Missing sensors remain missing;
the bridge must not invent values. Controller writes, MQTT command topics,
cloud services, and automatic home-automation discovery are outside v1.

## Development

Python 3.11+ is required for test tools (runtime supports 3.9+).

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check src tests tools
uv build
```

Tests use sanitized XML and a disposable local MQTT broker. Live tests are explicit:
`tools/smoke_test.py --config PATH` publishes real readings and verifies delivery.
Keep secrets, raw captures, and actual site configuration outside source control.
`uv.lock` pins dependencies; `requirements.lock` is the hashed production export.
