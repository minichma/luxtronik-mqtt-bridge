# Luxtronik MQTT bridge

A standalone Luxtronik 2.1 bridge that exposes readings and supported settings
through MQTT using Lux_WS. It targets installations where the legacy TCP API on
port 8889 is unavailable, including the intended FW 3.92 deployment.

Runs as one systemd service per heat pump on openHABian/Linux, with Windows support
for local use and testing.

The current implementation reads information/settings/schedules and writes fields
that the controller declares writable. Tested protocol: **V3.89.3, German and
English captures**. FW 3.92 remains unverified; no legacy API fallback is used.

## Configuration

Copy the [configuration examples](config/base.example.toml) outside
source, using this layout:

```text
config/
  base.toml                 # shared MQTT, timing, state root
  devices/heatpump1.toml
  devices/heatpump2.toml
```

Each device file references `../base.toml`. MQTT prefixes, client IDs, and state
subdirectories derive from the device ID, so MQTT settings are shared. The catalogs
are bundled as package resources in `src/luxtronik_mqtt/mappings/` and
contain **271 mappings** from the captured hardware; each pump publishes only its
available fields. English abbreviations are expanded in topic IDs, and numbered
circuits use numeric subtopics. Actual credentials live in protected external files;
see [secrets](docs/secrets.md). Language selects the bundled catalog; no mappings
need copying into the config directory. The legacy `mappings_dir` key is accepted
but ignored; remove it from existing base files when convenient. Mapping updates
and rollbacks travel with the application release.

```sh
uv sync --locked
uv run --locked luxtronik-mqtt --config /absolute/config/devices/heatpump_old.toml check
uv run --locked luxtronik-mqtt --config /absolute/config/devices/heatpump_old.toml discover
uv run --locked luxtronik-mqtt --config /absolute/config/devices/heatpump_old.toml run
```

`check` makes no connections. `discover` lists mapped paths without their values.
`once` publishes an initial snapshot then exits offline. Do not run two publishers
with the same device ID. See [deployment](docs/deployment.md) for Windows and systemd.

## MQTT topics and writes

MQTT 5 is required. Example topics:

```text
luxtronik/heatpump1/information/temperatures/flow
luxtronik/heatpump1/information/temperatures/flow/value
luxtronik/heatpump1/information/temperatures/mixingcircuit/1/flow
luxtronik/heatpump1/settings/temperatures/loweringto/value
luxtronik/heatpump1/settings/temperatures/loweringto/result
luxtronik/heatpump1/availability
luxtronik/heatpump1/metadata
```

The reading topic carries retained JSON; `/value` carries the scalar. Example:

```json
{"value":35.5,"unit":"degC","observed_at":"2026-10-03T08:00:00Z","quality":"good","path":["Informationen","Temperaturen","Vorlauf"],"writable":false,"possible_values":null}
```

Writable JSON exposes `possible_values.choices`, numeric `minimum`/`maximum`/`step`,
or a timer format. To write, publish a **non-retained scalar** to that reading's
`/value` topic. Use the exact English choice listed in JSON, a number in the displayed
unit, or `HH:MM - HH:MM` for timers. `/result` reports `applied`, `unchanged`, or a
rejection/failure status. Readback, not the command payload, determines published
state. Fields without write metadata reject commands. `writes = false` disables writes.

The bridge rejects retained commands and ignores its own state publications using
MQTT 5 subscription options. An uncertain write is never automatically retried.
Keep broker access limited to clients trusted to control the heat pumps.

Values publish initially and only when value, quality, path, or constraints change.
No timestamp-only repeats occur. `observed_at` in retained JSON can therefore be old
for an unchanged value. Use `availability = online` and `quality = good` to decide
whether state is usable; do not expire a reading just because it has not changed.
QoS 1 allows transport duplicates. Readings missing on a model have no topic; a
reported unavailable value is null. Duplicate paths within a page use the first entry.

## Operation

Information/settings refresh every 30 seconds. A second connection navigates
settings and scans schedules every 300 seconds, also reloading histories and write
constraints. Page switches require GET, while
repeated reads of the selected page use REFRESH. Controller IDs are never MQTT IDs.
Availability goes offline on a lost/stale controller or broker connection.

There are no routine reading/poll logs. Warning/error logs are rate-limited and
rotate under `<state_root>/<device_id>/bridge.log`: 1 MiB plus two backups per pump.
The service does not stream routine logs into the host's `/var/log` filesystem.

Use separate per-device state directories and only one publisher per device ID.
See the [openHAB example](examples/openhab/README.md) and
[upgrade guidance](docs/deployment.md#upgrade-rollback-and-migration).

## Development and evidence

Python 3.9+ runs the service; Python 3.11+ runs development tools. Tests use real
Mosquitto 2: install its executable on PATH, or provide Docker for a disposable
broker. They never use the live installation's broker or write controller settings.

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check src tests tools
uv run --locked ruff format --check src tests tools
uv build
```

[AGENTS.md](AGENTS.md) records module responsibilities, architectural decisions and
maintenance rules; [validation](docs/validation.md) records remaining verification.
Keep AGENTS.md and this README current with every relevant implementation, configuration or deployment
change, and update affected detailed documentation and examples in the same change.
Describe the current state; use Git history rather than documentation change logs.
See [protocol evidence](docs/protocol-research.md) and [validation](docs/validation.md).
Raw captures and actual site configuration stay outside source. The mapping builder
accepts paired external captures; it never connects to a controller or reads secrets.

Developed using OpenAI Codex with GPT-6 Astra.
