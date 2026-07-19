from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization|api[_-]?key|cookie|set-cookie)\s*[:=]\s*[^\s,;]+"),
]


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        output = super().format(record)
        for pattern in _SECRET_PATTERNS:
            output = pattern.sub(r"\1=[REDACTED]", output)
        return output


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
