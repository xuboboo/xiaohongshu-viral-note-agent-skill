"""从运营库导出 LTR JSONL，并可一键训练+签名。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_skill.core.config import get_settings  # noqa: E402
from xhs_skill.operations.repository import OperationsRepository  # noqa: E402
from xhs_skill.ranking.evaluation import (  # noqa: E402
    evaluate_candidate,
    split_rows_by_query,
)
from xhs_skill.ranking.features import FEATURE_ORDER  # noqa: E402
from xhs_skill.ranking.learning_ranker import LambdaMARTRanker  # noqa: E402
from xhs_skill.ranking.ltr_dataset import metrics_to_ltr_rows, write_ltr_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export LTR rows from published metrics")
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--account", required=True)
    parser.add_argument("--output", required=True, help="JSONL path")
    parser.add_argument("--train-output", default=None, help="If set, train LambdaMART to this path")
    parser.add_argument("--rounds", type=int, default=80)
    parser.add_argument("--min-group-size", type=int, default=2)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--minimum-ndcg-lift", type=float, default=0.0)
    parser.add_argument(
        "--promote-without-validation",
        action="store_true",
        help="Allow final model write when fewer than 3 query groups exist",
    )
    args = parser.parse_args()

    settings = get_settings()
    repo = OperationsRepository(settings)
    metrics = repo.list_metrics(args.tenant, args.account)
    rows = metrics_to_ltr_rows(metrics, min_group_size=max(1, args.min_group_size))
    count = write_ltr_jsonl(rows, args.output)
    result: dict = {
        "metrics": len(metrics),
        "rows": count,
        "features": FEATURE_ORDER,
        "jsonl": args.output,
    }
    if args.train_output and count:
        train_rows, validation_rows = split_rows_by_query(
            rows,
            validation_fraction=max(0.0, min(0.5, args.validation_fraction)),
        )
        target = Path(args.train_output)
        candidate = target.with_name(target.name + ".candidate")
        ranker = LambdaMARTRanker()
        model_path = ranker.train(
            train_rows or rows,
            output_path=candidate,
            num_boost_round=args.rounds,
        )
        result["candidate_model"] = str(model_path)
        result["candidate_verify"] = ranker.verify_artifact(model_path)

        promotion_recommended = False
        if validation_rows:
            predictions = ranker.predict_feature_rows(validation_rows)
            evaluation = evaluate_candidate(
                validation_rows,
                predictions,
                minimum_ndcg_lift=args.minimum_ndcg_lift,
            )
            result["evaluation"] = evaluation
            promotion_recommended = bool(evaluation["promotion_recommended"])
        else:
            result["evaluation"] = {
                "promotion_recommended": False,
                "reason": "insufficient_query_groups_for_validation",
            }
            promotion_recommended = bool(args.promote_without_validation)

        if promotion_recommended:
            target.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", ".metadata.json", ".sig.json"):
                source = Path(str(candidate) + suffix)
                destination = Path(str(target) + suffix)
                if source.exists():
                    source.replace(destination)
            result["model"] = str(target)
            result["verify"] = LambdaMARTRanker().verify_artifact(target)
            result["promoted"] = True
        else:
            result["promoted"] = False
            result["reason"] = "candidate_did_not_meet_promotion_gate"
    elif args.train_output and not count:
        result["train_skipped"] = "no rows"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if count == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()