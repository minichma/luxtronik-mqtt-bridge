# Deployment

Runtime: Python 3.9+, MQTT 5 broker, Lux_WS controller. The live openHABian host is
Raspberry Pi OS 11 (armhf), Python 3.9.2, systemd 247. Its broker accepts MQTT 5;
no broker or system-Python upgrade is required.

## Configuration layout

Copy `config/base.example.toml` to an external `base.toml`, copy `config/mappings`,
and copy each device example to `devices/<id>.toml`. Set the shared broker/state
root and each device's URL/language. A device's ID determines its MQTT namespace,
client ID, and state subdirectory. Both supplied language catalogs use identical
English topic IDs. Changing the controller language requires updating its device
file and restarting that instance.

## Windows

Use `%LOCALAPPDATA%\LuxtronikMqtt\config\` for the base, mappings, and devices.
Set `runtime.state_dir` to an absolute Windows path (forward slashes in TOML work).
Keep credentials under the protected external `secrets` directory. The helper
`tools/run-windows.ps1` defaults to the `heatpump_old` device file:

```powershell
uv sync --locked
.\tools\run-windows.ps1 check
.\tools\run-windows.ps1 discover
.\tools\run-windows.ps1 run -Config C:/absolute/config/devices/windows_test.toml
```

Give a publishing Windows test instance its own device ID. Discovery is read-only
and does not connect to MQTT. Never run two publishers for the same device ID.

## openHABian

Use `/etc/luxtronik-mqtt-bridge/{base.toml,mappings/,devices/}` and the state root
`/var/lib/luxtronik-mqtt-bridge`. Provision root-owned 0600 credentials under
`/etc/luxtronik-mqtt-bridge/secrets/<id>-controller-password` (directory 0700).
The template maps each into its private systemd credential directory as
`controller-password`; credentials never enter command lines or the repository.

Stage the built 0.2.0 wheel, `requirements.lock`, `deploy/install.sh`,
`deploy/luxtronik-mqtt-bridge@.service`, and an external `config/` directory.
Run:

```sh
sudo sh /absolute/staging/install.sh /absolute/staging heatpump_new heatpump_old
```

The installer builds a versioned virtualenv without replacing system Python,
validates staged and installed config, preserves existing base/device config,
updates language mappings, then activates each template instance. The original
single-instance service is stopped/disabled. Previous virtualenv releases and the
original `.venv` are retained for rollback. Review MQTT state after activation.

```sh
systemctl status luxtronik-mqtt-bridge@heatpump_new
systemctl status luxtronik-mqtt-bridge@heatpump_old
sudo tail -n 20 /var/lib/luxtronik-mqtt-bridge/heatpump_old/bridge.log
```

A healthy instance may have no log file. Runtime warning/error logs rotate at
1 MiB, retaining two backups per instance, and repeated errors are rate-limited.
Only early startup errors reach stderr/journald; the unit rate-limits those too.
No per-reading or per-poll messages are emitted, even at debug level.

For broker authentication add systemd `LoadCredential` entries named `mqtt-username`
and `mqtt-password` via a template drop-in. Configure TLS in the shared base;
certificate/hostname verification cannot be disabled. `secret-paths.env`, if used,
contains only absolute paths, never credential values.

## Upgrade, rollback, and migration

A service instance uses `/opt/luxtronik-mqtt-bridge/current/bin/python`. To roll
back, stop both instances, point `current` to the prior release, restore its matching
base/mappings/device files, then restart and check MQTT availability. Keep copies
of configuration when making schema changes. The installer preserves releases,
but does not automatically roll back after a failed hardware connection.

Version 0.2 replaces the monolithic config and `/v1/readings/<key>` topics. The old
namespace should remain offline until its consumers migrate. Clear only its owned
retained topics using the old manifest; never bulk-clear unrelated broker topics.
Each current namespace has a separate manifest that removes obsolete JSON and scalar
topics when its mappings change. Preserve manifests across restarts.

Only initial/changed observations are published, so retained `observed_at` is not
a heartbeat. Consumers must check availability and quality. Setting commands go
to `/value` without retention; `/result` reports readback or rejection. A broker
account needs publish/subscribe rights only within its assigned device namespace.
