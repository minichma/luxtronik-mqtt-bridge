import asyncio
import shutil
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
def config_files(tmp_path):
    source = Path(__file__).parents[1] / "config"
    shutil.copytree(source / "mappings", tmp_path / "mappings")
    text = (
        (source / "base.example.toml")
        .read_text("utf-8")
        .replace("/var/lib/luxtronik-mqtt-bridge", (tmp_path / "state").as_posix())
    )
    (tmp_path / "base.toml").write_text(text, encoding="utf-8")
    (tmp_path / "device.toml").write_text(
        'base = "base.toml"\n[device]\nid = "test"\n'
        'url = "ws://192.0.2.10:8214/"\nlanguage = "de"\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def full_config(config_files):
    return load_config(config_files / "device.toml")


@pytest.fixture
def config(full_config):
    wanted = {
        "information/temperatures/flow",
        "information/temperatures/outdoortemperature",
        "settings/temperatures/loweringto",
        "settings/modeofoperation/heatingcircuit",
    }
    return replace(
        full_config,
        sensors=tuple(s for s in full_config.sensors if s.key in wanted),
        timeout=1,
        poll=0.1,
        stale=3,
    )


@pytest.fixture
def fixture_dir():
    return Path(__file__).parent / "fixtures" / "v3_89_3" / "de"
