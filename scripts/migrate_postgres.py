#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.core.config import get_settings  # noqa: E402
from xhs_skill.enterprise.postgres import EnterprisePostgresStore  # noqa: E402


async def migrate(path: Path | None) -> None:
    settings = get_settings()
    if not settings.postgres_state_enabled:
        raise SystemExit("POSTGRES_STATE_ENABLED=true is required")
    store = EnterprisePostgresStore(settings)
    try:
        await store.migrate(path)
        if not await store.ping():
            raise RuntimeError("PostgreSQL readiness check failed after migration")
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply bundled enterprise PostgreSQL migrations")
    parser.add_argument(
        "--migration",
        type=Path,
        help="Apply one explicit SQL migration instead of all bundled migrations",
    )
    args = parser.parse_args()
    asyncio.run(migrate(args.migration))
    print("PostgreSQL migrations applied successfully")


if __name__ == "__main__":
    main()
