from __future__ import annotations

import argparse
import asyncio
import json

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.browser import LoginFlow  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="通过用户扫码授权登录并加密保存会话")
    parser.add_argument("--account", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--logout", action="store_true")
    args = parser.parse_args()

    async def run() -> None:
        flow = LoginFlow()
        if args.logout:
            result = await flow.logout(args.account, delete_session=True)
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return
        if args.status_only:
            result = await flow.status(args.account)
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return

        result = await flow.start(args.account)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        print("请在打开的浏览器中扫码并确认。程序不会绕过验证码或风险验证。")
        elapsed = 0
        while elapsed < args.timeout:
            await asyncio.sleep(2)
            elapsed += 2
            result = await flow.status(args.account)
            if result.status in {
                "AUTHENTICATED",
                "RISK_VERIFICATION_REQUIRED",
                "ACCOUNT_MISMATCH",
            }:
                print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
                return
        raise SystemExit("登录等待超时；未保存未认证会话。")

    asyncio.run(run())


if __name__ == "__main__":
    main()
