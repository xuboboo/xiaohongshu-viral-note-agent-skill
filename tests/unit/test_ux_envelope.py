"""工具响应体验信封。"""

from __future__ import annotations

from xhs_skill.search.adaptive import ClientWebSearchRequired
from xhs_skill.ux.catalog import annotate_tool_definition, group_for, tools_list_meta
from xhs_skill.ux.envelope import (
    enrich_needs_web_search,
    enrich_tool_result,
    ux_for_delivery_package,
    ux_for_hot_to_note,
    ux_for_research,
    ux_for_rewrite,
)


def test_needs_web_search_payload_has_ux():
    raw = ClientWebSearchRequired(
        "通勤防晒",
        suggested_queries=["通勤防晒 小红书", "通勤防晒 测评"],
        time_range="7d",
        limit=10,
    ).to_payload()
    payload = enrich_needs_web_search(raw)
    assert payload["status"] == "needs_web_search"
    assert payload["ux"]["schema"] == "tool_ux.v1"
    assert payload["ux"]["status"] == "needs_web_search"
    assert payload["next_step"]
    assert "web_results" in payload["next_step"]
    assert payload["suggested_queries"]


def test_enrich_is_idempotent_enough():
    base = ClientWebSearchRequired("q", suggested_queries=["q 小红书"]).to_payload()
    again = enrich_needs_web_search(base)
    assert again["status"] == "needs_web_search"
    assert again["ux"]["status"] == "needs_web_search"
    # enrich_tool_result 对已有 ux 幂等
    twice = enrich_tool_result("search_hot_notes", again)
    assert twice["ux"]["schema"] == "tool_ux.v1"


def test_research_ux_points_to_generate():
    out = ux_for_research(
        {
            "notes": [{"id": "1"}],
            "topic_suggestions": [{"topic": "a", "generate_payload": {"topic": "a"}}],
            "coverage_warning": "PUBLIC_INDEX",
        },
        tool="search_hot_notes",
    )
    assert out["status"] == "ok"
    assert out["ux"]["summary"]
    assert "generate" in out["next_step"].lower() or "generate" in out["ux"]["next_step"]


def test_delivery_blocked_ux():
    out = ux_for_delivery_package(
        {
            "selected_title": "测试标题",
            "publication_status": "BLOCKED",
            "quality_report": {
                "readiness": {
                    "overall_score": 40,
                    "blockers": ["compliance_failed"],
                    "recommended_fixes": ["删极限词"],
                    "ready_for_human_review": False,
                }
            },
            "creation_bundle": {"readiness": {"ready_for_draft": False}},
        }
    )
    assert out["ux"]["status"] == "blocked"
    assert "Do not create_publish_draft" in out["ux"]["agent_hint"]
    assert out["ux"]["agent_hint"]


def test_hot_to_note_dry_run_ux():
    out = ux_for_hot_to_note(
        {
            "status": "suggestions_ready",
            "dry_run": True,
            "topic_suggestions": [{"topic": "t1"}],
            "selected_suggestion": {"topic": "t1"},
            "next_step": "调用 generate_from_hot(dry_run=false)",
            "coverage_warning": "PUBLIC",
        }
    )
    assert out["ux"]["status"] == "suggestions_ready"
    assert "t1" in out["ux"]["summary"]


def test_rewrite_ux_structure_fail():
    out = ux_for_rewrite(
        {
            "body": "x",
            "structure_checks": {"passed": False, "recommended_fixes": ["补 CTA"]},
            "title_hook": {"risk_flags": ["title_too_long"]},
        }
    )
    assert out["ux"]["status"] == "needs_human_review"
    assert out["ux"]["warnings"]


def test_enrich_tool_result_routes_publish_and_verify():
    draft = enrich_tool_result(
        "create_publish_draft", {"draft_id": "d1", "status": "draft"}
    )
    assert draft["ux"]["next_step"]
    assert "preview" in draft["ux"]["next_step"]

    blocked = enrich_tool_result(
        "check_compliance", {"passed": False, "findings": ["hype"]}
    )
    assert blocked["ux"]["status"] == "blocked"

    login = enrich_tool_result(
        "start_account_login", {"qr_url": "https://example", "status": "pending"}
    )
    assert "扫码" in login["ux"]["summary"] or "login" in login["ux"]["agent_hint"].lower()

    retro = enrich_tool_result(
        "generate_retrospective",
        {"next_note_suggestions": [{"topic": "a", "next_action": "generate_xhs_note"}]},
    )
    assert "generate_xhs_note" in retro["ux"]["next_step"]


def test_enrich_doctor_and_canary():
    ready = enrich_tool_result(
        "doctor",
        {
            "ready": True,
            "summary": {"errors": 0, "warnings": 0},
            "checks": [],
            "golden_path": ["1. doctor", "2. generate"],
        },
    )
    assert ready["ux"]["status"] == "ok"
    assert "generate" in ready["ux"]["next_step"] or ready["ux"]["next_step"]

    canary_fail = enrich_tool_result("publish_canary", {"ok": False, "missing": ["title"]})
    assert canary_fail["ux"]["status"] == "blocked"


def test_tool_catalog_groups_and_prefix():
    assert group_for("search_hot_notes") == "research"
    assert group_for("publish_note") == "publish"
    annotated = annotate_tool_definition(
        {"name": "search_hot_notes", "description": "搜热门"}
    )
    assert annotated["description"].startswith("[研究/选题]")
    assert annotated["_meta"]["category"] == "research"
    meta = tools_list_meta(["search_hot_notes", "publish_note", "generate_xhs_note"])
    assert meta["schema"] == "tool_groups.v1"
    ids = {g["id"] for g in meta["groups"]}
    assert {"research", "publish", "generate"}.issubset(ids)