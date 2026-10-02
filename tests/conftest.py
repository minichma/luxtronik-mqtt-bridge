import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from luxtronik_mqtt.config import load_config


def pytest_asyncio_loop_factories():
    return {
        "portable": asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    }


@pytest.fixture
def config(tmp_path):
    example = Path(__file__).parents[1] / "config" / "bridge.example.toml"
    text = example.read_text(encoding="utf-8").replace(
        'state_dir = "/var/lib/luxtronik-mqtt-bridge"',
        'state_dir = "' + (tmp_path / "state").as_posix() + '"',
    )
    path = tmp_path / "bridge.toml"
    path.write_text(text, encoding="utf-8")
    settings = load_config(path)
    return replace(settings, mqtt_auth="none", mqtt_tls=False, timeout=0.3, poll=0.05, stale=0.5)


@pytest.fixture
def fixture_dir():
    return Path(__file__).parent / "fixtures" / "v3_89_3_de"
