"""Warning/error logging with rate limits and a fixed per-device disk budget."""

import logging
import time
from logging.handlers import RotatingFileHandler


class RateLimit(logging.Filter):
    def __init__(self, interval=60):
        super().__init__()
        self.interval = interval
        self.last = {}

    def filter(self, record):
        # A fixed per-logger/level bucket bounds repeated or alternating errors.
        key = (record.name, record.levelno)
        current = time.monotonic()
        previous = self.last.get(key)
        if previous is not None and current - previous < self.interval:
            return False
        self.last[key] = current
        return True


def configure(directory=None):
    if directory is None:
        handler = logging.StreamHandler()
    else:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / "bridge.log",
            maxBytes=1024 * 1024,
            backupCount=2,
            encoding="utf-8",
            delay=True,
        )
    handler.setLevel(logging.WARNING)
    handler.addFilter(RateLimit())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
