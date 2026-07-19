from __future__ import annotations

import argparse
import asyncio

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.jobs import JobService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Skill 自带的 Redis Streams 高并发任务 Worker")
    parser.add_argument("--consumer-name")
    args = parser.parse_args()

    async def run() -> None:
        service = JobService()
        try:
            await service.run_worker(args.consumer_name)
        finally:
            await service.shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    main()
