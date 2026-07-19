from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.storage.assets import AssetStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="将本地文件导入租户隔离素材库")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--content-type")
    args = parser.parse_args()
    item = AssetStore().save_bytes(
        tenant_id=args.tenant,
        filename=args.input.name,
        content_type=args.content_type,
        content=args.input.read_bytes(),
    )
    print(json.dumps({
        "asset_id": item.asset_id,
        "filename": item.filename,
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
