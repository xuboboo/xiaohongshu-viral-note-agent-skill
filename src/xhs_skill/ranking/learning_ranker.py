from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from xhs_skill.ranking.features import FEATURE_ORDER, score_title, title_features
from xhs_skill.schemas.content import TitleCandidate

_FEATURE_ORDER = FEATURE_ORDER


def feature_vector(candidate: TitleCandidate, keyword: str) -> list[float]:
    features = title_features(candidate.title, keyword, candidate.mechanism)
    candidate.scores = features
    return [float(features[name]) for name in _FEATURE_ORDER]


class LambdaMARTRanker:
    """Optional LightGBM LambdaMART ranker with deterministic fallback.

    The model is only trusted when its feature schema matches the current code. Without
    the ML extra or a trained artifact, the class falls back to the audited rule score.
    """

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.model: Any | None = None
        self.metadata: dict[str, Any] = {}
        if self.model_path and self.model_path.exists():
            self.load(self.model_path)

    def load(self, path: str | Path) -> None:
        path = Path(path)
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("Install the ml optional dependency to load LambdaMART") from exc
        self.model = lgb.Booster(model_file=str(path))
        metadata_path = path.with_suffix(path.suffix + ".metadata.json")
        if metadata_path.exists():
            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected = self.metadata.get("features", _FEATURE_ORDER)
        if list(expected) != _FEATURE_ORDER:
            raise ValueError("LambdaMART feature schema mismatch")
        # 若存在签名文件，加载时校验模型哈希（防错装旧 artifact）
        sig_path = path.with_suffix(path.suffix + ".sig.json")
        if sig_path.exists():
            sig = json.loads(sig_path.read_text(encoding="utf-8"))
            expected_hash = sig.get("model_sha256")
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected_hash and expected_hash != actual_hash:
                raise ValueError("LambdaMART model signature mismatch")

    def train(
        self,
        rows: list[dict[str, Any]],
        *,
        output_path: str | Path,
        num_boost_round: int = 80,
    ) -> Path:
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("Install the ml optional dependency to train LambdaMART") from exc
        if not rows:
            raise ValueError("Training rows cannot be empty")
        # LambdaRank 的 group 必须连续；外部 JSONL 不可信，训练前强制稳定排序。
        ordered_rows = sorted(
            rows,
            key=lambda row: (
                str(row["query_id"]),
                str(row.get("title") or row.get("note_id") or ""),
            ),
        )
        features = [list(map(float, row["features"])) for row in ordered_rows]
        labels = [float(row["relevance"]) for row in ordered_rows]
        weights = [max(0.01, float(row.get("sample_weight", 1.0))) for row in ordered_rows]
        groups: list[int] = []
        current_query: str | None = None
        current_count = 0
        for row in ordered_rows:
            query_id = str(row["query_id"])
            if current_query is None:
                current_query = query_id
            if query_id != current_query:
                groups.append(current_count)
                current_query, current_count = query_id, 0
            current_count += 1
        groups.append(current_count)
        dataset = lgb.Dataset(
            features,
            label=labels,
            weight=weights,
            group=groups,
            feature_name=_FEATURE_ORDER,
        )
        model = lgb.train(
            {
                "objective": "lambdarank",
                "metric": "ndcg",
                "verbosity": -1,
                "learning_rate": 0.05,
                "num_leaves": 15,
                "min_data_in_leaf": 8,
                "feature_fraction": 0.9,
                "bagging_fraction": 0.9,
                "bagging_freq": 1,
                "seed": 42,
            },
            dataset,
            num_boost_round=num_boost_round,
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(str(output))
        model_sha = hashlib.sha256(output.read_bytes()).hexdigest()
        metadata = {
            "features": _FEATURE_ORDER,
            "feature_count": len(_FEATURE_ORDER),
            "objective": "lambdarank",
            "rows": len(ordered_rows),
            "groups": len(groups),
            "sample_weight": {
                "min": round(min(weights), 6),
                "max": round(max(weights), 6),
                "mean": round(sum(weights) / len(weights), 6),
            },
            "num_boost_round": num_boost_round,
            "model_sha256": model_sha,
            "model_file": output.name,
            "schema_version": "title_ltr_v2",
        }
        meta_path = output.with_suffix(output.suffix + ".metadata.json")
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        # 独立签名旁路：便于发布校验（model + metadata 双哈希）
        signature = {
            "alg": "sha256",
            "model_sha256": model_sha,
            "metadata_sha256": hashlib.sha256(meta_path.read_bytes()).hexdigest(),
            "features": _FEATURE_ORDER,
            "schema_version": "title_ltr_v2",
        }
        output.with_suffix(output.suffix + ".sig.json").write_text(
            json.dumps(signature, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.model, self.model_path, self.metadata = model, output, metadata
        return output

    def verify_artifact(self, path: str | Path | None = None) -> dict[str, Any]:
        """校验模型文件与 .sig.json / metadata 是否一致。"""
        model_path = Path(path or self.model_path or "")
        if not model_path.is_file():
            return {"ok": False, "error": "model_missing"}
        actual = hashlib.sha256(model_path.read_bytes()).hexdigest()
        sig_path = model_path.with_suffix(model_path.suffix + ".sig.json")
        meta_path = model_path.with_suffix(model_path.suffix + ".metadata.json")
        expected = None
        if sig_path.is_file():
            sig = json.loads(sig_path.read_text(encoding="utf-8"))
            expected = sig.get("model_sha256")
            features = sig.get("features")
            if features is not None and list(features) != _FEATURE_ORDER:
                return {"ok": False, "error": "feature_schema_mismatch", "expected_features": features}
        elif meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            expected = meta.get("model_sha256")
        if not expected:
            return {"ok": False, "error": "signature_missing", "model_sha256": actual}
        return {
            "ok": actual == expected,
            "model_sha256": actual,
            "expected_sha256": expected,
            "sig_path": str(sig_path) if sig_path.is_file() else None,
        }

    def predict_feature_rows(self, rows: list[dict[str, Any]]) -> list[float]:
        """对已构造特征行预测，供离线 NDCG 评估。"""
        if self.model is None:
            raise RuntimeError("LambdaMART model is not loaded")
        vectors = [list(map(float, row["features"])) for row in rows]
        return [float(item) for item in self.model.predict(vectors)]

    def score(self, candidates: list[TitleCandidate], keyword: str) -> dict[str, float]:
        vectors = [feature_vector(candidate, keyword) for candidate in candidates]
        if self.model is None:
            return {candidate.id: round(score_title(candidate), 6) for candidate in candidates}
        predictions = self.model.predict(vectors)
        return {
            candidate.id: round(float(prediction), 6)
            for candidate, prediction in zip(candidates, predictions, strict=True)
        }

    def rank(self, candidates: list[TitleCandidate], keyword: str) -> tuple[list[TitleCandidate], dict[str, float]]:
        scores = self.score(candidates, keyword)
        return sorted(candidates, key=lambda item: scores[item.id], reverse=True), scores
