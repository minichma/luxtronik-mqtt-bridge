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
    page: tuple[str, ...] = ()
    options: dict[str, str] = field(default_factory=dict)
    translations: dict[str, str] = field(default_factory=dict)
    position: int | None = None


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
    language: str = "de"
    schedules_interval: float = 300
    writes: bool = True


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


def _read(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, ValueError):
        raise ConfigError("Cannot read configuration or invalid TOML") from None


def load_config(path: Path) -> Settings:
    path = path.resolve()
    individual = _read(path)
    _fields(individual, "base device luxtronik runtime")
    base_path = (path.parent / _text(individual, "base")).resolve()
    raw = _read(base_path)
    _fields(raw, "mappings_dir luxtronik mqtt runtime")
    device = individual.get("device", {})
    _fields(device, "id url language")
    device_id = _text(device, "id")
    if not KEY.fullmatch(device_id):
        raise ConfigError("Invalid device ID")
    language = _text(device, "language", "de")
    if language not in ("de", "en"):
        raise ConfigError("Supported languages: de, en")
    mapping_path = base_path.parent / _text(raw, "mappings_dir", "mappings") / (language + ".toml")
    mapping = _read(mapping_path)
    _fields(mapping, "language information_label readings")
    if mapping.get("language") != language:
        raise ConfigError("Mapping language mismatch")
    lux = dict(raw.get("luxtronik", {}))
    lux.update(individual.get("luxtronik", {}))
    mqtt = raw.get("mqtt", {})
    runtime = dict(raw.get("runtime", {}))
    runtime.update(individual.get("runtime", {}))
    _fields(
        lux,
        "password_file_env poll_interval_seconds operation_timeout_seconds "
        "stale_after_seconds max_frame_bytes schedules_interval_seconds writes",
    )
    _fields(
        mqtt,
        "host port tls verify_certificate authentication username_file_env "
        "password_file_env topic_root ca_file",
    )
    _fields(runtime, "state_dir")
    url = _text(device, "url")
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
    poll = _number(lux, "poll_interval_seconds", 30, 1, 3600)
    timeout = _number(lux, "operation_timeout_seconds", 10, 0.1, 120)
    stale = _number(lux, "stale_after_seconds", 120, 1, 7200)
    if stale <= poll + timeout:
        raise ConfigError("stale_after_seconds must exceed polling interval plus timeout")
    max_frame = _number(lux, "max_frame_bytes", 1048576, 1024, 4194304)
    port = _number(mqtt, "port", 1883, 1, 65535)
    if type(port) is not int or type(max_frame) is not int:
        raise ConfigError("Ports and frame limits must be integers")
    tls = _boolean(mqtt, "tls", False)
    if not _boolean(mqtt, "verify_certificate", True):
        raise ConfigError("TLS certificate verification cannot be disabled")
    auth = _text(mqtt, "authentication", "none")
    if auth not in ("password", "none"):
        raise ConfigError("MQTT authentication must be password or none")
    host = _text(mqtt, "host")
    if any(c in host for c in "/@?# "):
        raise ConfigError("mqtt.host must be a hostname or IP address")
    topic_root = _text(mqtt, "topic_root", "luxtronik")
    if not re.fullmatch(r"[a-z0-9_]+(?:/[a-z0-9_]+)*", topic_root):
        raise ConfigError("Invalid MQTT topic root")
    state_root = Path(_text(runtime, "state_dir"))
    if not state_root.is_absolute():
        raise ConfigError("runtime.state_dir must be an absolute external path")
    specs = mapping.get("readings", [])
    if not isinstance(specs, list) or not 1 <= len(specs) <= 2048:
        raise ConfigError("Invalid mapping list")
    sensors = []
    for item in specs:
        _fields(item, "topic path page type unit options translations position")
        key, kind = _text(item, "topic"), _text(item, "type")
        sensor_path, page = item.get("path"), item.get("page")
        if (
            not re.fullmatch(r"[a-z][a-z0-9]*(?:/[a-z0-9]+)+", key)
            or kind not in ("number", "boolean", "text", "duration", "enum", "timer")
            or any(
                not isinstance(p, list)
                or not 1 <= len(p) <= 16
                or any(not isinstance(v, str) or not v.strip() for v in p)
                for p in (sensor_path, page)
            )
            or sensor_path[: len(page)] != page
        ):
            raise ConfigError("Invalid mapping topic, type, page, or path")
        position = item.get("position")
        if position is not None and (type(position) is not int or not 1 <= position <= 100):
            raise ConfigError("Invalid mapping position")
        if ("*" in sensor_path) != (position is not None) or (position and sensor_path[-1] != "*"):
            raise ConfigError("Only positional leaf wildcards are supported")
        unit = item.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit):
            raise ConfigError("Invalid sensor unit")
        if kind == "duration" and unit != "s":
            raise ConfigError("Duration sensors must use seconds")
        options, translations = item.get("options", {}), item.get("translations", {})
        for entries in (options, translations):
            if not isinstance(entries, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or not v
                for k, v in entries.items()
            ):
                raise ConfigError("Invalid value translation")
        sensors.append(
            Sensor(
                key, tuple(sensor_path), kind, unit, tuple(page), options, translations, position
            )
        )
    if len({s.key for s in sensors}) != len(sensors):
        raise ConfigError("Duplicate mapping topics")
    if len({(s.path, s.position) for s in sensors}) != len(sensors):
        raise ConfigError("Duplicate mapping paths")
    ca_file = mqtt.get("ca_file")
    if ca_file is not None and (not isinstance(ca_file, str) or not Path(ca_file).is_absolute()):
        raise ConfigError("ca_file must be an absolute path")
    return Settings(
        device_id,
        url,
        _text(lux, "password_file_env", "LUXTRONIK_PASSWORD_FILE"),
        _text(mapping, "information_label"),
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
        "luxtronik-" + device_id,
        topic_root + "/" + device_id,
        ca_file,
        state_root / device_id,
        tuple(sensors),
        language,
        _number(lux, "schedules_interval_seconds", 300, 30, 86400),
        _boolean(lux, "writes", True),
    )
