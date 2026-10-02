# Credentials outside the source tree

The repository contains only example configuration. Actual configuration and the
supplied controller login are stored externally; the loader accepts file paths
through environment variables and never logs the values.

## Development on Windows

Keep actual configuration under `%LOCALAPPDATA%\LuxtronikMqtt\config\` and
credential files under `%LOCALAPPDATA%\LuxtronikMqtt\secrets\`, outside this
checkout. Restrict the secret directory's NTFS ACL to the account running the
bridge and required administrators/system accounts; remove broad inherited read
access and verify the effective ACL. Do not put it in a synchronized folder.

Use separate UTF-8 files for the controller password, MQTT username, and MQTT
password. The loader removes one terminal line ending only and preserves
other characters. It rejects empty required values. Do not supply credentials
as CLI arguments or put them in URLs. Environment variables carry only absolute
file paths, for example `LUXTRONIK_PASSWORD_FILE` and `MQTT_PASSWORD_FILE`.
Under systemd, the loader also accepts files named `controller-password`,
`mqtt-username`, and `mqtt-password` in `CREDENTIALS_DIRECTORY`. Explicit file-path
environment variables take precedence. The service unit uses this mechanism.

## Deployment on openHABian

Run under a dedicated unprivileged systemd service account. Keep configuration
under `/etc/luxtronik-mqtt-bridge` and state under `/var/lib/luxtronik-mqtt-bridge`.
Prefer service-manager credential injection where supported: load protected source
files from outside the checkout into the service's credential directory and set
the file-path environment variables accordingly. Otherwise use a dedicated
service account with a mode-0700 secret directory and mode-0600 files.

Protect TLS private keys in the same way. Keep CA trust files separate and always
verify broker certificates and hostname. Windows testing uses the same config
and secret-file contract with the paths and ACLs described above.

Actual site configuration, diagnostic captures, and runtime state also belong
outside the checkout. Tracked examples use reserved addresses. Broker access
should permit publishing only within this bridge's namespace, with no command
subscriptions. Authentication may be explicitly disabled only for a broker that
is intentionally configured to allow it; never silently downgrade on failure.

## Logging, rotation, and accidental exposure

Do not log secret contents, full configuration objects, authentication payloads,
or exceptions containing credentials. Redaction must apply to debug logs too.
Raw packet captures may contain login secrets and must never enter git.

Rotate by replacing external files with the same access restrictions and
restarting the service; verify recovery and revoke old credentials. Do not store
backup credentials in the checkout. If a secret is committed, revoke/rotate it
and coordinate repository-history cleanup; adding it to .gitignore is insufficient.

The ignore files are defense in depth, not a credential vault or access control.
