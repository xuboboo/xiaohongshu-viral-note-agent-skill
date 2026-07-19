from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.accounts import AccountService  # noqa: E402
from xhs_skill.schemas.account import AccountAnalytics  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入用户授权的账号分析数据")
    parser.add_argument("--account", required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    payload["account_id"] = args.account
    result = AccountService().sync(AccountAnalytics.model_validate(payload))
    print(result.model_dump_json(indent=2))
