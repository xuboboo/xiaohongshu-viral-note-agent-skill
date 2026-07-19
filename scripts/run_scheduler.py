from __future__ import annotations

import asyncio

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.publishing import PublishingService  # noqa: E402

if __name__ == "__main__":
    asyncio.run(PublishingService().run_scheduler_worker())
