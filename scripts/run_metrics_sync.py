from __future__ import annotations

import argparse
import asyncio

from xhs_skill.operations.post_publish import PostPublishSyncWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run post-publication metrics sync worker")
    parser.add_argument(
        "--tenant",
        default="*",
        help="Tenant id; use * to enumerate all active PostgreSQL tenants",
    )
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()
    asyncio.run(PostPublishSyncWorker().run_forever(args.tenant, args.poll_seconds))


if __name__ == "__main__":
    main()
