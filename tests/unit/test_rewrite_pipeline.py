"""generation/rewrite.py 单测：确定性规则清理 + 结构化变更日志。"""
import pytest

from xhs_skill.generation.rewrite import (
    CleanupChange,
    CleanupResult,
    apply_cleanup_rules,
    assemble_rewrite_response,
)


class TestApplyCleanupRules:
    def test_removes_hype_phrases(self):
        text = "宝子们谁懂啊，这个防晒真的绝绝子，闭眼冲！"
        result = apply_cleanup_rules(text)
        assert "宝子们谁懂啊" not in result.revised
        assert "绝绝子" not in result.revised
        assert "闭眼冲" not in result.revised
        assert len(result.changes) >= 3

    def test_structure_simplification(self):
        text = "首先看价格，其次看成分，最后看口碑。"
        result = apply_cleanup_rules(text)
        assert "第一" in result.revised
        assert "第二" in result.revised
        assert "第三" in result.revised
        assert len(result.changes) >= 3

    def test_removes_ai_filler(self):
        text = "家人们，这款真的不错。"
        result = apply_cleanup_rules(text)
        assert "家人们" not in result.revised

    def test_limits_decorative_emoji(self):
        text = "效果超好✨✨✨✨✨"
        result = apply_cleanup_rules(text)
        assert result.revised.count("✨") <= 1

    def test_no_changes_on_clean_text(self):
        text = "这是一款适合通勤使用的防晒霜，SPF50+，适合油皮。"
        result = apply_cleanup_rules(text)
        assert result.revised == text
        assert len(result.changes) == 0

    def test_preserves_original_in_result(self):
        text = "宝子们谁懂啊"
        result = apply_cleanup_rules(text)
        assert result.original == text

    def test_changes_are_structured(self):
        text = "闭眼冲！绝绝子！"
        result = apply_cleanup_rules(text)
        for change in result.changes:
            assert isinstance(change, CleanupChange)
            assert change.rule_id
            assert change.reason

    def test_collapses_triple_newlines(self):
        text = "段落一\n\n\n\n\n段落二"
        result = apply_cleanup_rules(text)
        assert "\n\n\n" not in result.revised

    def test_result_type(self):
        result = apply_cleanup_rules("测试")
        assert isinstance(result, CleanupResult)


class TestAssembleRewriteResponse:
    def test_basic_structure(self):
        changes = [CleanupChange("r1", "a", "b", "reason")]
        compliance = {"passed": True, "findings": []}
        ai_style = {"ai_style_score": 0, "detected_patterns": []}
        resp = assemble_rewrite_response("原文", "改文", changes, compliance, ai_style)
        assert resp["original"] == "原文"
        assert resp["revised"] == "改文"
        assert len(resp["changes"]) == 1
        assert resp["quality_report"]["compliance"]["passed"] is True
        assert resp["publication_status"] == "REVIEW"

    def test_blocked_when_compliance_fails(self):
        compliance = {"passed": False, "findings": [{"code": "MEDICAL_CLAIM"}]}
        ai_style = {"ai_style_score": 0}
        resp = assemble_rewrite_response("原文", "改文", [], compliance, ai_style)
        assert resp["publication_status"] == "BLOCKED"

    def test_human_review_when_high_ai_score(self):
        compliance = {"passed": True}
        ai_style = {"ai_style_score": 80, "detected_patterns": ["宝子们"]}
        resp = assemble_rewrite_response("原文", "改文", [], compliance, ai_style)
        assert resp["publication_status"] == "HUMAN_REVIEW_REQUIRED"

    def test_changes_preserved(self):
        changes = [
            CleanupChange("hype", "宝子们", "", "删套话"),
            CleanupChange("structure", "首先", "第一", "简化"),
        ]
        resp = assemble_rewrite_response("原文", "改文", changes, {"passed": True}, {"ai_style_score": 0})
        assert len(resp["changes"]) == 2
        assert resp["changes"][0]["rule_id"] == "hype"
        assert resp["quality_report"]["change_count"] == 2

    def test_blocked_when_originality_fails(self):
        compliance = {"passed": True, "findings": []}
        ai_style = {"ai_style_score": 0}
        originality = {"publication_allowed": False, "literal_similarity": 0.99}
        resp = assemble_rewrite_response(
            "原文", "改文", [], compliance, ai_style, originality=originality
        )
        assert resp["publication_status"] == "BLOCKED"
        assert resp["quality_report"]["originality"]["publication_allowed"] is False

    def test_originality_optional(self):
        resp = assemble_rewrite_response(
            "原文", "改文", [], {"passed": True}, {"ai_style_score": 0}
        )
        assert "originality" not in resp["quality_report"]
        assert resp["publication_status"] == "REVIEW"