"""Portable console entry point; no shell or daemon dependency in the core."""

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from pathlib import Path

from .compat import run_async
from .config import ConfigError, load_config, load_secrets
from .controller import Controller
from .service import run


async def execute(args, config, secrets):
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        if args.command == "discover":
            async with Controller(config, secrets.controller) as controller:
                raw = await controller.sample()
                # Paths only: device identifiers and other values stay out of output.
                print(
                    json.dumps(
                        {
                            "paths": sorted([list(p) for p in raw if not raw[p].ambiguous]),
                            "ambiguous_paths": sorted([list(p) for p in raw if raw[p].ambiguous]),
                        },
                        ensure_ascii=True,
                    )
                )
        else:
            await run(config, secrets, once=args.command == "once")
    finally:
        if sys.platform != "win32":
            loop.remove_signal_handler(signal.SIGTERM)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Lux_WS to MQTT bridge")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("command", choices=["check", "discover", "once", "run"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(args.config)
        secrets = load_secrets(config, controller_only=args.command == "discover")
        if args.command == "check":
            print("Configuration and secret files are valid; no connections attempted.")
            return 0
        # aiomqtt requires add_reader(), unsupported by Windows' default Proactor loop.
        with contextlib.suppress(asyncio.CancelledError):
            run_async(execute(args, config, secrets))
        return 0
    except KeyboardInterrupt:
        return 0
    except ConfigError as exc:
        logging.error("%s", exc)
        return 2
    except Exception as exc:
        logging.error(
            "Operation failed (%s); credentials and response contents omitted", type(exc).__name__
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
