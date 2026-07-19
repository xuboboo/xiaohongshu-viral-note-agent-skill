from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from xhs_skill.verifiers import ai_style_report, check_text, originality_report  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="诊断小红书笔记")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path, action="append", default=[])
    args = parser.parse_args()
    text = args.input.read_text(encoding="utf-8")
    refs = [item.read_text(encoding="utf-8") for item in args.reference]
    print(json.dumps({
        "compliance": check_text(text),
        "originality": originality_report(text, refs),
        "ai_style": ai_style_report(text),
        "recommended_fixes": [
            "让标题承诺在首段得到兑现",
            "补充具体场景、限制条件和不适合人群",
            "删除无法验证的数据和效果承诺",
        ],
    }, ensure_ascii=False, indent=2))
