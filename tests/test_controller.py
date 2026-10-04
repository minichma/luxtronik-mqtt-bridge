import logging
from dataclasses import replace

import pytest

from luxtronik_mqtt.controller import Controller
from luxtronik_mqtt.model import normalize
from luxtronik_mqtt.protocol import (
    AuthenticationError,
    ProtocolError,
    content,
    decode,
    navigation,
    refresh,
)

from .fake_controller import FakeController


@pytest.mark.parametrize(
    "frame",
    [
        '{"type":',
        "<broken>",
        '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>',
        "<x>" * 35 + "</x>" * 35,
    ],
)
def test_rejects_unsafe_or_unknown_frames(frame):
    with pytest.raises(ProtocolError):
        decode(frame)


def test_first_duplicate_wins(fixture_dir):
    snapshot = content(decode((fixture_dir / "page0.xml").read_bytes()), ("Informationen",))
    reading = snapshot.values[("Informationen", "Eingänge", "HD")]
    assert reading.values == ("Aus",)
    updated = refresh(decode((fixture_dir / "refresh0.xml").read_bytes()), snapshot)
    assert updated.values[reading.path].values == ("Aus",)


def test_json_navigation_content_and_refresh():
    nav = decode(
        '{"type":"Navigation","items":[{"id":"0x1","name":"Informationen",'
        '"items":[{"id":"0x2","name":"Temperaturen","items":[]}]}]}'
    )
    paths = navigation(nav)
    assert paths[("Informationen", "Temperaturen")] == "0x2"
    page = decode(
        '{"type":"Content","name":"Temperaturen","items":['
        '{"id":"0x10","name":"Vorlauf","value":"35.0°C",'
        '"type":"slider","min":0,"max":100,"step":1,"div":10,"raw":350},'
        '{"id":"0x11","name":"Modus","value":"Auto", "type":"combo",'
        '"options":{"0":"Aus","1":"Auto"}}]}'
    )
    snapshot = content(page, ("Informationen", "Temperaturen"))
    assert snapshot.values[("Informationen", "Temperaturen", "Vorlauf")].write is not None
    changed = refresh(
        decode('{"type":"values","items":[{"id":"0x10","value":"36.0°C"}]}'),
        snapshot,
    )
    assert changed.values[("Informationen", "Temperaturen", "Vorlauf")].values == ("36.0°C",)


def test_omitted_refresh_preserves_original_observation(fixture_dir):
    snapshot = content(decode((fixture_dir / "page0.xml").read_bytes()), ("Informationen",))
    updated = refresh(decode("<values/>"), snapshot)
    assert updated.values == snapshot.values
    assert all(updated.values[p].observed_at == r.observed_at for p, r in snapshot.values.items())


@pytest.mark.parametrize(
    "frame",
    ["<Content/>", '<values><item id="0x999999"/></values>', '<values><item id="bad"/></values>'],
)
def test_unknown_refresh_fails(fixture_dir, frame):
    snapshot = content(decode((fixture_dir / "page0.xml").read_bytes()), ("Informationen",))
    with pytest.raises(ProtocolError):
        refresh(decode(frame), snapshot)


def test_authentication_and_size_limits():
    with pytest.raises(AuthenticationError):
        navigation(decode("<Error/>"))
    with pytest.raises(ProtocolError):
        decode("<x/>", max_bytes=1)


async def test_session_scoped_ids_refresh_and_redaction(config, fixture_dir, caplog):
    async with FakeController(fixture_dir) as fake:
        c = replace(config, url=f"ws://127.0.0.1:{fake.port}")
        with caplog.at_level(logging.DEBUG):
            for _ in range(2):
                async with Controller(c, "TEST_SECRET") as controller:
                    first = await controller.sample()
                    second = await controller.sample()
                    assert first.keys() == second.keys()
        assert fake.connections == 4
        for connection in range(1, 5):
            commands = [m for n, m in fake.commands if n == connection]
            assert commands[0].startswith("GET;")
            assert commands[-1] == "REFRESH"
        assert "TEST_SECRET" not in caplog.text


async def test_validated_write_and_readback(config, fixture_dir):
    async with FakeController(fixture_dir) as fake:
        c = replace(config, url=f"ws://127.0.0.1:{fake.port}")
        spec = next(s for s in c.sensors if s.key.endswith("loweringto"))
        async with Controller(c, "test") as controller:
            raw = await controller.sample()
            assert normalize(spec, raw[spec.key])["value"] == -20
            assert await controller.write(spec, b"-19.5") == "applied"
            assert normalize(spec, controller.values()[spec.key])["value"] == -19.5
            assert fake.saved == 1
            assert await controller.write(spec, b"-19.5") == "unchanged"
            assert fake.saved == 1
            before = len(fake.commands)
            from luxtronik_mqtt.protocol import CommandError

            with pytest.raises(CommandError):
                await controller.write(spec, b"1000")
            assert all(not command.startswith("SET;") for _, command in fake.commands[before:])


async def test_timer_write_and_scoped_reused_ids(full_config, fixture_dir):
    timer = next(s for s in full_config.sensors if s.type == "timer")
    async with FakeController(fixture_dir) as fake:
        c = replace(full_config, url=f"ws://127.0.0.1:{fake.port}", sensors=(timer,))
        async with Controller(c, "test") as controller:
            await controller.sample()
            assert await controller.write(timer, b"23:00 - 02:00") == "applied"
            assert normalize(timer, controller.values()[timer.key])["value"] == "23:00 - 02:00"


@pytest.mark.parametrize("language", ["de", "en"])
async def test_all_pages_in_both_languages(config_files, fixture_dir, language):
    from luxtronik_mqtt.config import load_config

    path = config_files / "device.toml"
    path.write_text(
        path.read_text("utf-8").replace('language = "de"', f'language = "{language}"'),
        encoding="utf-8",
    )
    c = load_config(path)
    async with FakeController(fixture_dir.parent / language) as fake:
        c = replace(c, url=f"ws://127.0.0.1:{fake.port}")
        async with Controller(c, "test") as controller:
            raw = await controller.sample()
            assert len(raw) == 271
            assert all(normalize(s, raw[s.key])["quality"] != "invalid" for s in c.sensors)
            flow = next(s for s in c.sensors if s.key == "information/temperatures/flow")
            assert normalize(flow, raw[flow.key])["value"] == 10
            assert len(await controller.sample()) == 271
            assert fake.connections == 2
