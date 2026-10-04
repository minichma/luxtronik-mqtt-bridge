import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from luxtronik_mqtt.cli import main
from luxtronik_mqtt.config import ConfigError, Sensor, load_config, load_secrets, secret_file
from luxtronik_mqtt.model import encode_command, normalize
from luxtronik_mqtt.protocol import CommandError, RawReading, content, decode


@pytest.mark.parametrize(
    "raw,kind,unit,expected,quality",
    [
        ("-3,5 °C", "number", "degC", -3.5, "good"),
        ("100h", "number", "h", 100, "good"),
        ("3.4 kWh", "number", "kWh", 3.4, "good"),
        ("--- °C", "number", "degC", None, "unavailable"),
        ("3.5 °C trailing", "number", "degC", None, "invalid"),
        ("NaN", "number", None, None, "invalid"),
        ("9" * 400, "number", None, None, "invalid"),
        ("Ein", "boolean", None, True, "good"),
        ("off", "boolean", None, False, "good"),
        ("unknown", "boolean", None, None, "invalid"),
        ("Standby", "text", None, "Standby", "good"),
        ("", "text", None, None, "unavailable"),
        ("123:42:07", "duration", "s", 445327, "good"),
        ("12:99:00", "duration", "s", None, "invalid"),
        ("23:00 - 02:00", "timer", None, "23:00 - 02:00", "good"),
    ],
)
def test_normalize(raw, kind, unit, expected, quality):
    spec = Sensor("test/value", ("test",), kind, unit)
    actual = normalize(spec, RawReading(spec.path, (raw,)), "now")
    assert actual["value"] == expected
    assert actual["quality"] == quality
    assert actual["path"] == ["test"]
    assert actual["observed_at"] == "now"
    json.dumps(actual, allow_nan=False)


def test_language_catalogs_cover_all_fixture_readings(config_files):
    topic_sets = []
    for language in ("de", "en"):
        device = config_files / "device.toml"
        device.write_text(
            device.read_text("utf-8").replace('language = "de"', f'language = "{language}"'),
            encoding="utf-8",
        )
        c = load_config(device)
        topic_sets.append({s.key for s in c.sensors})
        base = Path(__file__).parent / "fixtures" / "v3_89_3" / language
        for page in json.loads((base / "pages.json").read_text("utf-8")):
            snapshot = content(decode((base / page["file"]).read_bytes()), tuple(page["path"]))
            for path in snapshot.values:
                assert any(
                    s.path == path or (s.position and s.path[:-1] == path[:-1]) for s in c.sensors
                )
        assert c.prefix == "luxtronik/test" and c.client_id == "luxtronik-test"
        assert c.state_dir.name == "test"
    assert topic_sets[0] == topic_sets[1]
    assert len(topic_sets[0]) == 271


@pytest.mark.parametrize(
    "before,after",
    [
        ("verify_certificate = true", "verify_certificate = false"),
        ("poll_interval_seconds = 30", "poll_interval_seconds = nan"),
        ("port = 1883", "port = 1.5"),
        ('authentication = "none"', 'authentication = "guess"'),
        ('topic_root = "luxtronik"', 'topic_root = "bad/#"'),
    ],
)
def test_invalid_base_config(config_files, before, after):
    base = config_files / "base.toml"
    base.write_text(base.read_text("utf-8").replace(before, after), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config_files / "device.toml")


@pytest.mark.parametrize("url", ["ws://user:password@host:8214/", "ws://host:8889/", "file:///x"])
def test_invalid_controller_url(config_files, url):
    p = config_files / "device.toml"
    p.write_text(p.read_text("utf-8").replace("ws://192.0.2.10:8214/", url), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_external_secrets(config, tmp_path, monkeypatch):
    file = tmp_path / "password"
    file.write_bytes(b" sensitive value \r\n")
    monkeypatch.setenv(config.password_env, str(file))
    assert load_secrets(config).controller == " sensitive value "
    assert "sensitive" not in repr(load_secrets(config))
    for value in (b"", b"x\ny", b"x" * 4097, b"\xff", b"a;b"):
        file.write_bytes(value)
        with pytest.raises(ConfigError):
            load_secrets(config)
    monkeypatch.setenv(config.password_env, "relative")
    with pytest.raises(ConfigError):
        secret_file(config.password_env)


def test_systemd_credentials_and_optional_mqtt_auth(config, tmp_path, monkeypatch):
    monkeypatch.delenv(config.password_env, raising=False)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    (tmp_path / "controller-password").write_text("test-secret")
    assert load_secrets(config).controller == "test-secret"
    with pytest.raises(ConfigError):
        load_secrets(replace(config, mqtt_auth="password"))


@pytest.mark.parametrize("payload", [b"-20.1", b"11", b"NaN", b"1;SAVE;1", b"", b"1" * 300])
def test_write_rejects_invalid_ranges_and_injection(config, fixture_dir, payload):
    spec = next(s for s in config.sensors if s.key.endswith("loweringto"))
    raw = content(decode((fixture_dir / "page1.xml").read_bytes()), spec.page).values[spec.path]
    with pytest.raises(CommandError):
        encode_command(spec, raw, payload)


def test_enum_uses_english_choices_and_rejects_unknown(config, fixture_dir):
    spec = next(s for s in config.sensors if s.type == "enum")
    raw = content(decode((fixture_dir / "page1.xml").read_bytes()), spec.page).values[spec.path]
    assert normalize(spec, raw)["possible_values"]["choices"][0] == "automatic"
    assert encode_command(spec, raw, b"party") == ("2", "party")
    with pytest.raises(CommandError):
        encode_command(spec, raw, b"Automatik")
    with pytest.raises(CommandError):
        encode_command(spec, replace(raw, write=None), b"party")


def test_cli_redacts_invalid_config(tmp_path, capsys):
    path = tmp_path / "bad.toml"
    path.write_text('password = "TOP_SECRET', encoding="utf-8")
    assert main(["--config", str(path), "check"]) == 2
    assert "TOP_SECRET" not in capsys.readouterr().err
    # Restore pytest's logging capture after CLI configuration.
    logging.getLogger().handlers.clear()
