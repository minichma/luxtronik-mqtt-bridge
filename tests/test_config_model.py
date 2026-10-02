import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from luxtronik_mqtt.cli import main
from luxtronik_mqtt.config import ConfigError, Sensor, load_config, load_secrets, secret_file
from luxtronik_mqtt.model import normalize
from luxtronik_mqtt.protocol import RawReading


@pytest.mark.parametrize(
    "raw,kind,unit,expected,quality",
    [
        ("-3,5 °C", "number", "degC", -3.5, "good"),
        ("100h", "number", "h", 100, "good"),
        ("3.4 kWh", "number", "kWh", 3.4, "good"),
        ("--- °C", "number", "degC", None, "invalid"),
        ("3.5 °C trailing", "number", "degC", None, "invalid"),
        ("3.5 kW", "number", "kWh", None, "invalid"),
        ("NaN", "number", None, None, "invalid"),
        ("9" * 400, "number", None, None, "invalid"),
        ("Ein", "boolean", None, True, "good"),
        ("Aus", "boolean", None, False, "good"),
        ("unknown", "boolean", None, None, "invalid"),
        ("Standby", "text", None, "Standby", "good"),
        ("123:42:07", "duration", "s", 445327, "good"),
        ("12:99:00", "duration", "s", None, "invalid"),
    ],
)
def test_normalize(raw, kind, unit, expected, quality):
    spec = Sensor("test", ("test",), kind, unit)
    actual = normalize(spec, RawReading(spec.path, (raw,)), "now")
    assert actual == {"value": expected, "quality": quality, "unit": unit, "observed_at": "now"}
    json.dumps(actual, allow_nan=False)


def test_missing_and_multiple_values():
    spec = Sensor("test", ("test",), "number")
    assert normalize(spec, None, "now")["quality"] == "unavailable"
    assert normalize(spec, RawReading(spec.path, ("1", "2")), "now")["quality"] == "invalid"


def test_external_secrets(config, tmp_path, monkeypatch):
    file = tmp_path / "password"
    file.write_bytes(b" sensitive value \r\n")
    monkeypatch.setenv(config.password_env, str(file))
    secrets = load_secrets(config)
    assert secrets.controller == " sensitive value "
    assert "sensitive" not in repr(secrets)
    for value in (b"", b"x\ny", b"x" * 4097, b"\xff", b"a;b"):
        file.write_bytes(value)
        with pytest.raises(ConfigError):
            load_secrets(config)
    monkeypatch.setenv(config.password_env, "relative")
    with pytest.raises(ConfigError):
        secret_file(config.password_env)


def test_mqtt_secrets_required_unless_explicit_none(config, tmp_path, monkeypatch):
    file = tmp_path / "password"
    file.write_text("test-only")
    monkeypatch.setenv(config.password_env, str(file))
    monkeypatch.delenv(config.username_env, raising=False)
    with pytest.raises(ConfigError):
        load_secrets(replace(config, mqtt_auth="password"))
    assert load_secrets(config).username is None


def test_systemd_credentials_directory(config, tmp_path, monkeypatch):
    monkeypatch.delenv(config.password_env, raising=False)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    (tmp_path / "controller-password").write_text("test-systemd-credential")
    assert load_secrets(config).controller == "test-systemd-credential"


@pytest.mark.parametrize(
    "before,after",
    [
        ("verify_certificate = true", "verify_certificate = false"),
        ("qos = 1", "qos = 0"),
        ("poll_interval_seconds = 30", "poll_interval_seconds = nan"),
        ("port = 8883", "port = 1.5"),
        ('authentication = "password"', 'authentication = "guess"'),
        ("ws://192.0.2.10:8214/", "ws://private:secret@192.0.2.10:8214/"),
        ("ws://192.0.2.10:8214/", "ws://192.0.2.10:8889/"),
        ('key = "flow_temperature"', 'key = "outdoor_temperature"'),
        ('"Vorlauf"', '"Außentemperatur"'),
    ],
)
def test_bad_config_rejected(tmp_path, before, after):
    text = (Path(__file__).parents[1] / "config/bridge.example.toml").read_text("utf-8")
    text = text.replace(
        'state_dir = "/var/lib/luxtronik-mqtt-bridge"', f'state_dir = "{tmp_path.as_posix()}"'
    ).replace(before, after)
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_cli_never_logs_invalid_toml_contents(tmp_path, caplog):
    path = tmp_path / "bad.toml"
    path.write_text('password = "TOP_SECRET', encoding="utf-8")
    with caplog.at_level(logging.DEBUG):
        assert main(["--config", str(path), "check"]) == 2
    assert "TOP_SECRET" not in caplog.text
