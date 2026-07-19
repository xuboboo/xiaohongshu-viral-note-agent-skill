"""定时/批量跑发布选择器 canary：版本钉扎 + 失败 webhook 告警。

用法:
  python scripts/run_selector_canary.py --account acc1 --tenant local
  python scripts/run_selector_canary.py --accounts-file accounts.json

accounts.json: [{"account_id":"a1","tenant_id":"local"}, ...]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 允许直接 python scripts/... 运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_skill.publishing.service import PublishingService  # noqa: E402


async def _run_one(account_id: str, tenant_id: str) -> dict:
    return await PublishingService().check_selector_health(account_id, tenant_id, alert=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Creator Studio selector canary")
    parser.add_argument("--account", default=None)
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--accounts-file", default=None, help="JSON list of {account_id, tenant_id}")
    args = parser.parse_args()

    targets: list[tuple[str, str]] = []
    if args.accounts_file:
        payload = json.loads(Path(args.accounts_file).read_text(encoding="utf-8"))
        for item in payload:
            targets.append((str(item["account_id"]), str(item.get("tenant_id") or "local")))
    elif args.account:
        targets.append((args.account, args.tenant))
    else:
        raise SystemExit("require --account or --accounts-file")

    async def run_all() -> list[dict]:
        results = []
        for account_id, tenant_id in targets:
            results.append(await _run_one(account_id, tenant_id))
        return results

    results = asyncio.run(run_all())
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if any(not item.get("ok") for item in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()