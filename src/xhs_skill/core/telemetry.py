from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class TraceRecord:
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    spans: list[dict] = field(default_factory=list)

    @contextmanager
    def span(self, name: str, **attributes: object):
        started = time.perf_counter()
        error: str | None = None
        try:
            yield
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            self.spans.append(
                {
                    "name": name,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "attributes": attributes,
                    "error": error,
                }
            )
