from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.publishing import PublishingService  # noqa: E402
from xhs_skill.schemas.content import DeliveryPackage  # noqa: E402
from xhs_skill.schemas.publishing import PublishMode  # noqa: E402


def dump(value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="创建草稿、预览、审批并受控发布小红书笔记")
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft")
    draft.add_argument("--account", required=True)
    draft.add_argument("--package", type=Path, required=True)
    draft.add_argument("--mode", default="REQUIRE_CONFIRMATION")

    preview = sub.add_parser("preview")
    preview.add_argument("--draft", required=True)

    approve = sub.add_parser("approve")
    approve.add_argument("--draft", required=True)
    approve.add_argument("--confirm-ai-disclosure", action="store_true")
    approve.add_argument("--confirm-commercial-disclosure", action="store_true")
    approve.add_argument("--confirm-account", action="store_true")

    execute = sub.add_parser("execute")
    execute.add_argument("--draft", required=True)
    execute.add_argument("--approval-token", required=True)

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--draft", required=True)
    schedule.add_argument("--approval-token", required=True)
    schedule.add_argument("--at", required=True)

    args = parser.parse_args()
    service = PublishingService()

    if args.command == "draft":
        package = DeliveryPackage.model_validate_json(args.package.read_text(encoding="utf-8"))
        dump(service.create_draft(args.account, package, PublishMode(args.mode)))
        return
    if args.command == "approve":
        dump(service.approve(
            args.draft,
            ai_disclosure_confirmed=args.confirm_ai_disclosure,
            commercial_disclosure_confirmed=args.confirm_commercial_disclosure,
            account_identity_confirmed=args.confirm_account,
        ))
        return
    async def run() -> None:
        if args.command == "schedule":
            dump(await service.schedule(args.draft, args.approval_token, datetime.fromisoformat(args.at)))
            return
        if args.command == "preview":
            dump(await service.preview(args.draft))
        elif args.command == "execute":
            dump(await service.publish(args.draft, args.approval_token))

    asyncio.run(run())


if __name__ == "__main__":
    main()
