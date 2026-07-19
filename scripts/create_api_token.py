from __future__ import annotations

import argparse

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.core.auth import issue_token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="创建短期 Bearer 服务令牌")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--scope", action="append", required=True)
    parser.add_argument("--auth-level", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--amr", action="append", default=[])
    parser.add_argument("--region")
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    args = parser.parse_args()
    print(
        issue_token(
            subject=args.subject,
            tenant_id=args.tenant,
            scopes=set(args.scope),
            auth_level=args.auth_level,
            roles=set(args.role),
            amr=set(args.amr),
            region=args.region,
            ttl_seconds=args.ttl_seconds,
        )
    )


if __name__ == "__main__":
    main()
