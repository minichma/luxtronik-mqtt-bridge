# Running the bridge

Python 3.9+ is supported. The inspected openHABian host runs Raspberry Pi OS 11
(32-bit armhf), Python 3.9.2, and systemd 247. No system-Python upgrade is required.

## Windows testing

```powershell
uv sync --locked
.\tools\run-windows.ps1 check
.\tools\run-windows.ps1 discover
.\tools\run-windows.ps1 once
.\tools\run-windows.ps1 run
```

The helper uses `%LOCALAPPDATA%\LuxtronikMqtt\config\bridge.toml` and the external
controller secret. `discover` lists sensor paths, flagging ambiguous ones without
printing values. `once` publishes one cycle then marks the bridge offline. `run`
polls until Ctrl+C. Do not run two instances against the same topic namespace.

## openHABian system service

Use a dedicated `luxtronik-mqtt` account, application under
`/opt/luxtronik-mqtt-bridge`, configuration under `/etc/luxtronik-mqtt-bridge`, and
state under `/var/lib/luxtronik-mqtt-bridge`. The supplied
[systemd unit](../deploy/luxtronik-mqtt-bridge.service) creates the state directory
and loads the controller password through systemd credentials. The application
reads `CREDENTIALS_DIRECTORY` directly, including on systemd 247 where `%d` is not
available in the unit's environment settings.

The [installer](../deploy/install.sh) takes a staging directory containing the
built wheel, `requirements.lock`, and `luxtronik-mqtt-bridge.service`. Its parent
must contain the external `bridge.toml` and `secrets/controller-password`:

```sh
sudo sh deploy/install.sh /absolute/path/to/staging
```

It creates the account/virtualenv, installs locked dependencies, preserves existing
configuration and secrets, and enables the service. The installer requires system
`python3`, `venv`, and `pip`, which are present on the inspected host. It does not
need `ensurepip` or an OS upgrade.

Install the built wheel into a virtualenv using `requirements.lock` with
`pip install --require-hashes -r requirements.lock`, then install the wheel with
`--no-deps`. A host missing `ensurepip` can create the environment with
`python3 -m venv --without-pip` and use system pip's `--target` option to populate
that environment's `lib/python3.9/site-packages`. The service invokes the virtualenv
Python directly, so pip-generated console-script interpreter paths are irrelevant.

Copy the example configuration outside the checkout; set the controller URL,
broker address, and mapped sensor paths. For an intentionally anonymous LAN broker,
set `authentication = "none"`, `tls = false`, and `port = 1883`. TLS/authentication
remain the example defaults. `state_dir` must match the service's state directory.
Store the controller password in `/etc/luxtronik-mqtt-bridge/secrets/controller-password`
with root-only permissions; systemd passes a read-only copy to the service.

For an authenticated broker, add `LoadCredential` entries named `mqtt-username`
and `mqtt-password` through a systemd drop-in. The application reads these from
the credential directory too. Explicit `MQTT_USERNAME_FILE` / `MQTT_PASSWORD_FILE`
paths override this; the optional `secret-paths.env` contains paths only.
Validate the unit before enabling it:

```sh
sudo systemd-analyze verify /etc/systemd/system/luxtronik-mqtt-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now luxtronik-mqtt-bridge
sudo journalctl -u luxtronik-mqtt-bridge -n 30 --no-pager
```

The older test controller's verified XML protocol is implemented. FW 3.92 still
needs authenticated fixtures and a 24-hour hardware soak. Unknown formats fail
explicitly; no legacy API fallback or controller-write commands exist.

## Operations

- Stop: `sudo systemctl stop luxtronik-mqtt-bridge`; retained availability becomes
  offline. An unexpected process death uses MQTT's Last Will.
- Updates: stop the service, preserve its current wheel and dependency lock, install
  the new locked dependencies/wheel, then restart and verify fresh readings. Roll
  back using the saved wheel and matching lock. Keep config/secrets/state external.
- Rotation: replace the protected credential file, restart, and revoke the old
  credential. Never put credential values in command lines or environment files.
- Mapping changes: remove a sensor from config and restart; its old retained topic
  is cleared using `published-topics.json`. Keep this manifest across upgrades.
  A changed namespace needs a separate state directory; the bridge won't erase
  topics in another namespace. Retire old namespaces explicitly in the broker.
- Diagnostics: logs include failure categories, never raw frames or login values.
  `check` validates config/secret files without network access. For protocol work,
  `tools/inspect_controller.py` stores captures only outside the checkout.
- Freshness: consumers must require availability `online`, reading quality `good`,
  and a recent `observed_at`. Retained readings can outlive a controller or broker.

The broker account needs publish access only to `luxtronik/<device_id>/v1/#`;
the service has no subscriptions. Subscribers such as openHAB need read access.
