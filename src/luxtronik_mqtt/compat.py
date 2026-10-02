"""Support the target openHABian Python 3.9 without replacing system Python."""

import asyncio
import sys

if sys.version_info >= (3, 11):
    from asyncio import timeout

    import tomllib
else:
    import tomli as tomllib
    from async_timeout import timeout

__all__ = ["run_async", "timeout", "tomllib"]


def run_async(coroutine):
    if sys.version_info >= (3, 11):
        with asyncio.Runner(
            loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
        ) as runner:
            return runner.run(coroutine)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coroutine)
