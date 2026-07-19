from __future__ import annotations

import argparse
import json
from pathlib import Path

from xhs_skill.ranking.features import FEATURE_ORDER
from xhs_skill.ranking.learning_ranker import LambdaMARTRanker


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the title LambdaMART ranking model")
    parser.add_argument("--input", required=True, help="JSONL rows with query_id, relevance, features")
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", type=int, default=80)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing model signature (requires --output path)",
    )
    args = parser.parse_args()
    ranker = LambdaMARTRanker()
    if args.verify_only:
        result = ranker.verify_artifact(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get("ok") else 2)
    rows = [
        json.loads(line)
        for line in Path(args.input).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 特征维度守卫：防止用旧 6 维样本训出不可加载模型
    for index, row in enumerate(rows[:5]):
        feats = row.get("features") or []
        if len(feats) != len(FEATURE_ORDER):
            raise SystemExit(
                f"row {index}: expected {len(FEATURE_ORDER)} features "
                f"({FEATURE_ORDER}), got {len(feats)}"
            )
    output = ranker.train(
        rows,
        output_path=args.output,
        num_boost_round=max(1, args.rounds),
    )
    verification = ranker.verify_artifact(output)
    print(
        json.dumps(
            {
                "model": str(output),
                "metadata": str(output) + ".metadata.json",
                "signature": str(output) + ".sig.json",
                "features": FEATURE_ORDER,
                "verify": verification,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
