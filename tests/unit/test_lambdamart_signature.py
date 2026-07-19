"""LambdaMART 签名校验。"""
from pathlib import Path

from xhs_skill.ranking.learning_ranker import LambdaMARTRanker


def test_verify_artifact_missing():
    result = LambdaMARTRanker().verify_artifact(Path("no-such-model.txt"))
    assert result["ok"] is False
    assert result["error"] == "model_missing"


def test_verify_artifact_with_sig(tmp_path):
    model = tmp_path / "m.txt"
    model.write_bytes(b"fake-model")
    import hashlib
    import json

    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    sig = {
        "alg": "sha256",
        "model_sha256": digest,
        "features": [
            "length",
            "keyword",
            "number",
            "specificity",
            "mechanism_diversity",
            "risk_penalty",
            "hook_strength",
            "search_intent",
            "readability",
            "emoji_penalty",
        ],
        "schema_version": "title_ltr_v2",
    }
    model.with_suffix(model.suffix + ".sig.json").write_text(
        json.dumps(sig), encoding="utf-8"
    )
    result = LambdaMARTRanker().verify_artifact(model)
    assert result["ok"] is True
    assert result["model_sha256"] == digest