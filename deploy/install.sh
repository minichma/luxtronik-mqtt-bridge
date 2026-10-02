#!/bin/sh
# Run as root with the staging directory containing the wheel, lockfile, and unit.
# Site config and secrets must be in the staging directory's parent, outside git.
set -eu
test "$(id -u)" -eq 0 || { printf '%s\n' 'Run this installer with sudo.' >&2; exit 1; }
staging=$(realpath "${1:?Usage: sudo sh install.sh /absolute/path/to/staging}")
site=$(dirname "$staging")
app=/opt/luxtronik-mqtt-bridge
config=/etc/luxtronik-mqtt-bridge
state=/var/lib/luxtronik-mqtt-bridge
wheel="$staging/luxtronik_mqtt_bridge-0.1.0-py3-none-any.whl"
for file in "$wheel" "$staging/requirements.lock" "$staging/luxtronik-mqtt-bridge.service" \
            "$site/bridge.toml" "$site/secrets/controller-password"; do
    test -f "$file" || { printf '%s\n' 'Missing required staging file.' >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9+ required"'
if ! getent passwd luxtronik-mqtt >/dev/null; then
    useradd --system --no-log-init --user-group --home-dir "$state" --shell /usr/sbin/nologin luxtronik-mqtt
fi
install -d -o root -g root -m 755 "$app"
install -d -o root -g luxtronik-mqtt -m 750 "$config"
install -d -o root -g root -m 700 "$config/secrets"
install -d -o luxtronik-mqtt -g luxtronik-mqtt -m 700 "$state"

# Stop an existing instance before updating; preserve its artifacts for rollback.
if systemctl is-active --quiet luxtronik-mqtt-bridge; then
    systemctl stop luxtronik-mqtt-bridge
fi
if test -f "$app/requirements.lock"; then
    backup="$app/previous-$(date -u +%Y%m%dT%H%M%SZ)"
    install -d -m 700 "$backup"
    cp "$app/requirements.lock" "$backup/requirements.lock"
    if test -f "$app/luxtronik_mqtt_bridge-0.1.0-py3-none-any.whl"; then
        cp "$app/luxtronik_mqtt_bridge-0.1.0-py3-none-any.whl" "$backup/"
    fi
fi
python3 -m venv --without-pip "$app/.venv"
packages=$("$app/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
case "$packages" in "$app"/.venv/*) ;; *) printf '%s\n' 'Unexpected virtualenv path.' >&2; exit 1;; esac
PIP_CONFIG_FILE=/dev/null python3 -m pip install --disable-pip-version-check \
    --index-url https://pypi.org/simple --only-binary=:all: --upgrade --require-hashes \
    --target "$packages" -r "$staging/requirements.lock"
PIP_CONFIG_FILE=/dev/null python3 -m pip install --disable-pip-version-check \
    --no-deps --upgrade --target "$packages" "$wheel"
install -m 644 "$staging/requirements.lock" "$app/requirements.lock"
install -m 644 "$wheel" "$app/"

# Preserve existing site configuration and credentials during upgrades.
if ! test -e "$config/bridge.toml"; then
    python3 - "$site/bridge.toml" "$config/bridge.toml" <<'PY'
import pathlib
import re
import sys
source, target = map(pathlib.Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
text, count = re.subn(r'(?m)^state_dir\s*=.*$',
                     'state_dir = "/var/lib/luxtronik-mqtt-bridge"', text)
if count != 1:
    raise SystemExit("Expected exactly one state_dir setting")
target.write_text(text, encoding="utf-8")
PY
    chown root:luxtronik-mqtt "$config/bridge.toml"
    chmod 640 "$config/bridge.toml"
fi
if ! test -e "$config/secrets/controller-password"; then
    install -o root -g root -m 600 "$site/secrets/controller-password" \
        "$config/secrets/controller-password"
fi
LUXTRONIK_PASSWORD_FILE="$config/secrets/controller-password" \
    "$app/.venv/bin/python" -m luxtronik_mqtt --config "$config/bridge.toml" check
install -o root -g root -m 644 "$staging/luxtronik-mqtt-bridge.service" \
    /etc/systemd/system/luxtronik-mqtt-bridge.service
systemd-analyze verify /etc/systemd/system/luxtronik-mqtt-bridge.service
systemctl daemon-reload
systemctl enable --now luxtronik-mqtt-bridge
sleep 2
systemctl is-active luxtronik-mqtt-bridge
