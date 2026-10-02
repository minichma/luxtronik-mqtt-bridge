"""Strict configuration and external secret loading; errors never echo input."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .compat import tomllib


class ConfigError(ValueError):
    """Safe-to-display configuration error."""


KEY = re.compile(r"[a-z][a-z0-9_]*\Z")


@dataclass(frozen=True)
class Sensor:
    key: str
    path: tuple[str, ...]
    type: str
    unit: str | None = None


@dataclass(frozen=True)
class Settings:
    device_id: str
    url: str
    password_env: str
    information_label: str
    poll: float
    timeout: float
    stale: float
    max_frame: int
    mqtt_host: str
    mqtt_port: int
    mqtt_tls: bool
    mqtt_auth: str
    username_env: str
    mqtt_password_env: str
    client_id: str
    prefix: str
    ca_file: str | None
    state_dir: Path
    sensors: tuple[Sensor, ...]


@dataclass(frozen=True)
class Secrets:
    controller: str = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)


def secret_file(variable: str, credential_name: str | None = None) -> str:
    path = os.environ.get(variable, "")
    credential_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if not path and credential_name and credential_dir:
        path = str(Path(credential_dir) / credential_name)
    if not path or not Path(path).is_absolute():
        raise ConfigError(f"Set {variable} to an absolute external secret-file path")
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise ValueError
        value = data.decode("utf-8").removesuffix("\n").removesuffix("\r")
        if not value or any(c in value for c in "\r\n\x00"):
            raise ValueError
        return value
    except (OSError, ValueError, UnicodeError):
        raise ConfigError(f"Secret file for {variable} is unreadable, empty, or invalid") from None


def load_secrets(config: Settings, *, controller_only: bool = False) -> Secrets:
    controller = secret_file(config.password_env, "controller-password")
    if ";" in controller:
        raise ConfigError("Controller password cannot contain protocol delimiters")
    if controller_only or config.mqtt_auth == "none":
        return Secrets(controller)
    return Secrets(
        controller,
        secret_file(config.username_env, "mqtt-username"),
        secret_file(config.mqtt_password_env, "mqtt-password"),
    )


def _fields(table: dict, allowed: str) -> None:
    if not isinstance(table, dict) or set(table) - set(allowed.split()):
        raise ConfigError("Unknown configuration field or invalid table")


def _text(table: dict, key: str, default=None) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ConfigError(f"Invalid or missing {key}")
    return value


def _number(table: dict, key: str, default, low, high):
    value = table.get(key, default)
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ConfigError(f"Invalid {key}")
    return value


def _boolean(table: dict, key: str, default: bool) -> bool:
    value = table.get(key, default)
    if type(value) is not bool:
        raise ConfigError(f"Invalid {key}")
    return value


def load_config(path: Path) -> Settings:
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, ValueError):
        raise ConfigError("Cannot read configuration or invalid TOML") from None
    _fields(raw, "device luxtronik mqtt runtime sensors")
    device, lux, mqtt, runtime = (
        raw.get(t, {}) for t in ("device", "luxtronik", "mqtt", "runtime")
    )
    _fields(device, "id")
    _fields(
        lux,
        "url subprotocol password_file_env information_label poll_interval_seconds "
        "operation_timeout_seconds stale_after_seconds max_frame_bytes",
    )
    _fields(
        mqtt,
        "host port tls verify_certificate authentication username_file_env "
        "password_file_env client_id topic_prefix qos retain ca_file",
    )
    _fields(runtime, "state_dir")
    device_id = _text(device, "id")
    if not KEY.fullmatch(device_id):
        raise ConfigError("device.id must contain lowercase letters, digits, or underscores")
    url = _text(lux, "url")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in ("ws", "wss")
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.port not in (8888, 8889)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("Invalid Lux_WS URL; credentials and legacy ports are forbidden")
    if _text(lux, "subprotocol", "Lux_WS") != "Lux_WS":
        raise ConfigError("Only Lux_WS is supported")
    poll = _number(lux, "poll_interval_seconds", 30, 1, 3600)
    timeout = _number(lux, "operation_timeout_seconds", 10, 0.1, 120)
    stale = _number(lux, "stale_after_seconds", 120, 1, 7200)
    if stale <= poll + timeout:
        raise ConfigError("stale_after_seconds must exceed polling interval plus timeout")
    max_frame = _number(lux, "max_frame_bytes", 1048576, 1024, 4194304)
    port = _number(mqtt, "port", 8883, 1, 65535)
    if type(port) is not int or type(max_frame) is not int:
        raise ConfigError("Ports and frame limits must be integers")
    tls = _boolean(mqtt, "tls", True)
    if not _boolean(mqtt, "verify_certificate", True):
        raise ConfigError("TLS certificate verification cannot be disabled")
    auth = _text(mqtt, "authentication", "password")
    if auth not in ("password", "none"):
        raise ConfigError("MQTT authentication must be password or none")
    host = _text(mqtt, "host")
    if any(c in host for c in "/@?# "):
        raise ConfigError("mqtt.host must be a hostname or IP address")
    prefix = _text(mqtt, "topic_prefix", f"luxtronik/{device_id}/v1")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", prefix):
        raise ConfigError("Invalid MQTT topic prefix")
    if mqtt.get("qos", 1) != 1 or not _boolean(mqtt, "retain", True):
        raise ConfigError("The v1 contract requires QoS 1 and retained messages")
    state_dir = Path(_text(runtime, "state_dir"))
    if not state_dir.is_absolute():
        raise ConfigError("runtime.state_dir must be an absolute external path")
    specs = raw.get("sensors", [])
    if not isinstance(specs, list) or len(specs) > 512:
        raise ConfigError("Invalid sensor list")
    sensors = []
    for item in specs:
        _fields(item, "key path type unit")
        key, kind = _text(item, "key"), _text(item, "type")
        sensor_path = item.get("path")
        if (
            not KEY.fullmatch(key)
            or kind not in ("number", "boolean", "text", "duration")
            or not isinstance(sensor_path, list)
            or not 1 <= len(sensor_path) <= 16
            or any(not isinstance(p, str) or not p.strip() for p in sensor_path)
        ):
            raise ConfigError("Invalid sensor key, type, or path")
        unit = item.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit):
            raise ConfigError("Invalid sensor unit")
        if kind == "duration" and unit != "s":
            raise ConfigError("Duration sensors must use seconds (unit = s)")
        sensors.append(Sensor(key, tuple(sensor_path), kind, unit))
    if len({s.key for s in sensors}) != len(sensors):
        raise ConfigError("Duplicate sensor keys")
    if len({s.path for s in sensors}) != len(sensors):
        raise ConfigError("Duplicate sensor paths")
    ca_file = mqtt.get("ca_file")
    if ca_file is not None and (not isinstance(ca_file, str) or not Path(ca_file).is_absolute()):
        raise ConfigError("ca_file must be an absolute path")
    return Settings(
        device_id,
        url,
        _text(lux, "password_file_env", "LUXTRONIK_PASSWORD_FILE"),
        _text(lux, "information_label", "Informationen"),
        poll,
        timeout,
        stale,
        max_frame,
        host,
        port,
        tls,
        auth,
        _text(mqtt, "username_file_env", "MQTT_USERNAME_FILE"),
        _text(mqtt, "password_file_env", "MQTT_PASSWORD_FILE"),
        _text(mqtt, "client_id"),
        prefix,
        ca_file,
        state_dir,
        tuple(sensors),
    )
