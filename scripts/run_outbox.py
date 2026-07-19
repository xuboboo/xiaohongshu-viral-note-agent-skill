#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.enterprise.outbox import OutboxDispatcher  # noqa: E402

if __name__ == "__main__":
    asyncio.run(OutboxDispatcher().run())
