#!/bin/sh
# Staging: wheel, requirements.lock, template unit, config/{base.toml,devices}.
# Secrets must already exist under /etc/luxtronik-mqtt-bridge/secrets/<id>-controller-password.
set -eu
test "$(id -u)" -eq 0 || { echo 'Run with sudo.' >&2; exit 1; }
staging=$(realpath "${1:?Usage: sudo sh install.sh STAGING DEVICE_ID ...}")
shift
test "$#" -gt 0 || { echo 'Specify at least one device ID.' >&2; exit 1; }
app=/opt/luxtronik-mqtt-bridge
config=/etc/luxtronik-mqtt-bridge
state=/var/lib/luxtronik-mqtt-bridge
wheel="$staging/luxtronik_mqtt_bridge-0.2.0-py3-none-any.whl"
for id in "$@"; do
    case "$id" in ''|*[!a-z0-9_]*|[0-9_]*) echo 'Invalid device ID.' >&2; exit 1;; esac
    test -f "$staging/config/devices/$id.toml"
    test -f "$config/secrets/$id-controller-password"
done
for file in "$wheel" "$staging/requirements.lock" "$staging/luxtronik-mqtt-bridge@.service"             "$staging/config/base.toml"; do
    test -f "$file" || { echo 'Missing staging file.' >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3, 9)'
if ! getent passwd luxtronik-mqtt >/dev/null; then
    useradd --system --no-log-init --user-group --home-dir "$state" --shell /usr/sbin/nologin luxtronik-mqtt
fi
install -d -o root -g root -m 755 "$app/releases"
install -d -o root -g luxtronik-mqtt -m 750 "$config" "$config/devices"
install -d -o luxtronik-mqtt -g luxtronik-mqtt -m 700 "$state"
release="$app/releases/$(date -u +%Y%m%dT%H%M%SZ)"
test ! -e "$release"
python3 -m venv --without-pip "$release"
packages=$("$release/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
case "$packages" in "$release"/*) ;; *) echo 'Unexpected virtualenv path.' >&2; exit 1;; esac
PIP_CONFIG_FILE=/dev/null python3 -m pip install --quiet --disable-pip-version-check     --index-url https://pypi.org/simple --only-binary=:all: --require-hashes     --target "$packages" -r "$staging/requirements.lock"
PIP_CONFIG_FILE=/dev/null python3 -m pip install --quiet --disable-pip-version-check     --no-deps --upgrade --target "$packages" "$wheel"
install -m 644 "$staging/requirements.lock" "$release/requirements.lock"
# Preflight the staged configuration before changing any running service.
for id in "$@"; do
    LUXTRONIK_PASSWORD_FILE="$config/secrets/$id-controller-password"         "$release/bin/python" -m luxtronik_mqtt --config "$staging/config/devices/$id.toml" check
done
# Preserve operator-maintained base/device files; mappings are bundled in the release.
if ! test -e "$config/base.toml"; then
    install -o root -g luxtronik-mqtt -m 640 "$staging/config/base.toml" "$config/base.toml"
fi
for id in "$@"; do
    if ! test -e "$config/devices/$id.toml"; then
        install -o root -g luxtronik-mqtt -m 640 "$staging/config/devices/$id.toml" "$config/devices/$id.toml"
    fi
    install -d -o luxtronik-mqtt -g luxtronik-mqtt -m 700 "$state/$id"
done
for id in "$@"; do
    LUXTRONIK_PASSWORD_FILE="$config/secrets/$id-controller-password"         "$release/bin/python" -m luxtronik_mqtt --config "$config/devices/$id.toml" check
done
install -o root -g root -m 644 "$staging/luxtronik-mqtt-bridge@.service" /etc/systemd/system/
if test -e "$app/current" && ! test -L "$app/current"; then
    echo 'Current release must be a symlink.' >&2; exit 1
fi
if ! test -L "$app/current"; then ln -s "$release" "$app/current"; fi
systemd-analyze verify /etc/systemd/system/luxtronik-mqtt-bridge@.service
# Old releases and the original .venv remain available for rollback.
ln -sfn "$release" "$app/current.next"
mv -Tf "$app/current.next" "$app/current"
systemctl daemon-reload
if systemctl is-active --quiet luxtronik-mqtt-bridge.service; then
    systemctl disable --now luxtronik-mqtt-bridge.service
fi
for id in "$@"; do
    systemctl enable "luxtronik-mqtt-bridge@$id.service"
    systemctl restart "luxtronik-mqtt-bridge@$id.service"
done
sleep 2
for id in "$@"; do systemctl is-active "luxtronik-mqtt-bridge@$id.service"; done
