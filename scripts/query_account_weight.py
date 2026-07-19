from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.accounts import AccountService  # noqa: E402
from xhs_skill.schemas.account import AccountAnalytics  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="基于授权数据估算账号健康与内容分发能力")
    parser.add_argument("--account", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    analytics = None
    if args.input:
        analytics = AccountAnalytics.model_validate_json(args.input.read_text(encoding="utf-8"))
    report = AccountService().query_weight(args.account, analytics)
    text = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
