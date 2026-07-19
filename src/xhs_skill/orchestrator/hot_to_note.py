"""热门 → 选题 → 一键生成：研究复用，避免二次搜索。"""

from __future__ import annotations

from typing import Any

from xhs_skill.generation.creation_bundle import build_creation_bundle
from xhs_skill.operations.publish_timing import generate_request_from_suggestion
from xhs_skill.research.topic_suggest import suggest_topics_from_report
from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import HotNotesReport, SearchQuery


def infer_note_style(suggestion: dict[str, Any]) -> str:
    """从选题来源/角度推断笔记类型。"""
    blob = " ".join(str(suggestion.get(k) or "") for k in ("topic", "angle", "reason", "source")).lower()
    if any(x in blob for x in ("避坑", "翻车", "踩雷", "失败", "avoid")):
        return "avoid_pitfall"
    if any(x in blob for x in ("清单", "checklist", "核对")):
        return "checklist"
    if any(x in blob for x in ("对比", "vs", "comparison", "还是")):
        return "comparison"
    if any(x in blob for x in ("教程", "步骤", "怎么做", "tutorial")):
        return "tutorial"
    if any(x in blob for x in ("探店", "到店", "store")):
        return "store_visit"
    if any(x in blob for x in ("测评", "实测", "review")):
        return "review"
    if any(x in blob for x in ("种草", "安利", "seed")):
        return "seeding"
    return "decision"


def infer_framework(note_style: str) -> str:
    return {
        "avoid_pitfall": "pas",
        "checklist": "scqa",
        "comparison": "scqa",
        "tutorial": "quest",
        "store_visit": "bab",
        "review": "four_p",
        "seeding": "aida",
        "decision": "pas",
    }.get(note_style, "pas")


def enrich_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为选题补全 generate_payload / note_style，便于宿主一跳。"""
    out: list[dict[str, Any]] = []
    for item in suggestions:
        row = dict(item)
        style = str(row.get("note_style") or infer_note_style(row))
        framework = str(row.get("narrative_framework") or infer_framework(style))
        row["note_style"] = style
        row["narrative_framework"] = framework
        row["generate_payload"] = generate_request_from_suggestion(
            row,
            research_current_trends=False,
            note_style=style,
            narrative_framework=framework,
        )
        row["next_action"] = "generate_from_hot"
        out.append(row)
    return out


def pick_suggestion(
    suggestions: list[dict[str, Any]],
    *,
    index: int = 0,
    topic: str | None = None,
) -> tuple[int, dict[str, Any]]:
    if not suggestions:
        raise ValueError("no_topic_suggestions")
    if topic:
        key = topic.strip().casefold()
        for i, item in enumerate(suggestions):
            if str(item.get("topic") or "").strip().casefold() == key:
                return i, item
        for i, item in enumerate(suggestions):
            t = str(item.get("topic") or "").casefold()
            if key in t or t in key:
                return i, item
    idx = max(0, min(int(index), len(suggestions) - 1))
    return idx, suggestions[idx]


def build_generate_request_from_hot(
    suggestion: dict[str, Any],
    *,
    query: str,
    format: str = "graphic",
    video_duration_seconds: int | None = None,
    account_id: str | None = None,
    target_audience: str | None = None,
    commercial_status: str | None = None,
    brand_voice: dict | None = None,
    product: dict | None = None,
    constraints: list[str] | None = None,
    note_style: str | None = None,
    narrative_framework: str | None = None,
    provider: str | None = None,
) -> GenerateRequest:
    style = note_style or suggestion.get("note_style") or infer_note_style(suggestion)
    framework = (
        narrative_framework
        or suggestion.get("narrative_framework")
        or infer_framework(str(style))
    )
    topic = str(suggestion.get("topic") or query).strip()
    data: dict[str, Any] = {
        "topic": (query or topic).strip(),
        "suggested_topic": topic,
        "topic_angle": str(suggestion.get("angle") or "")[:120] or None,
        "topic_reason": str(suggestion.get("reason") or "")[:400] or None,
        "format": format if format in {"graphic", "video"} else "graphic",
        "research_current_trends": False,
        "note_style": style,
        "narrative_framework": framework,
        "account_id": account_id,
        "target_audience": target_audience,
        "provider": provider,
        "product": product or {},
        "brand_voice": brand_voice or {},
        "constraints": list(constraints or []),
    }
    if commercial_status:
        data["commercial_status"] = commercial_status
    if video_duration_seconds is not None:
        data["video_duration_seconds"] = int(video_duration_seconds)
    return GenerateRequest.model_validate({k: v for k, v in data.items() if v is not None})


async def run_hot_to_note(
    workflow: Any,
    *,
    query: str,
    suggestion_index: int = 0,
    suggestion_topic: str | None = None,
    dry_run: bool = False,
    providers: list[str] | None = None,
    web_results: list[dict[str, Any]] | None = None,
    tenant_id: str = "local",
    format: str = "graphic",
    video_duration_seconds: int | None = None,
    account_id: str | None = None,
    use_account_health: bool = False,
    target_audience: str | None = None,
    commercial_status: str | None = None,
    brand_voice: dict | None = None,
    product: dict | None = None,
    constraints: list[str] | None = None,
    note_style: str | None = None,
    narrative_framework: str | None = None,
    provider: str | None = None,
    accounts_service: Any | None = None,
) -> dict[str, Any]:
    """搜索热门 → 选题 →（可选）直接生成交付包。

    dry_run=True：只返回选题，不生成。
    dry_run=False：复用同一份 HotNotesReport 生成，避免二次联网。
    use_account_health=True 且提供 account_id：用内容健康度重排选题并推荐 note_style。
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query is required")

    report: HotNotesReport = await workflow.research.search_hot_notes(
        SearchQuery(query=query, time_range="7d", limit=30),
        providers=providers,
        web_results=web_results,
    )
    raw = list(report.topic_suggestions or suggest_topics_from_report(report))
    suggestions = enrich_suggestions(raw)
    health_meta: dict[str, Any] | None = None

    if use_account_health and account_id:
        from xhs_skill.accounts.service import AccountService

        svc = accounts_service or AccountService()
        merged = svc.suggest_topics_from_health(
            account_id,
            base_topic=query,
            research_suggestions=suggestions,
            tenant_id=tenant_id,
            limit=8,
        )
        suggestions = list(merged.get("topic_suggestions") or suggestions)
        for row in suggestions:
            row["next_action"] = "generate_from_hot"
        health_meta = {
            "strategy": merged.get("strategy"),
            "source_mix": merged.get("source_mix"),
            "content_health_level": (merged.get("content_health") or {}).get("level"),
            "content_health_score": (merged.get("content_health") or {}).get("overall_score"),
        }

    selected_index, selected = pick_suggestion(
        suggestions, index=suggestion_index, topic=suggestion_topic
    )
    # 健康度主类型可覆盖未显式传入的 note_style
    if (
        use_account_health
        and health_meta
        and not note_style
        and selected.get("note_style")
    ):
        note_style = str(selected.get("note_style"))
    if (
        use_account_health
        and not narrative_framework
        and selected.get("narrative_framework")
    ):
        narrative_framework = str(selected.get("narrative_framework"))

    result: dict[str, Any] = {
        "query": query,
        "coverage_warning": report.coverage_warning,
        "score_type": str(report.score_type),
        "hot_insights": report.hot_insights,
        "notes_count": len(report.notes),
        "topic_suggestions": suggestions,
        "selected_suggestion": selected,
        "selected_index": selected_index,
        "dry_run": dry_run,
        "use_account_health": bool(use_account_health and account_id),
        "health_strategy": health_meta,
    }

    if dry_run:
        result["status"] = "suggestions_ready"
        result["next_step"] = (
            "调用 generate_from_hot(dry_run=false) 生成，"
            "或 generate_xhs_note(**selected_suggestion.generate_payload)"
        )
        return result

    request = build_generate_request_from_hot(
        selected,
        query=query,
        format=format,
        video_duration_seconds=video_duration_seconds,
        account_id=account_id,
        target_audience=target_audience,
        commercial_status=commercial_status,
        brand_voice=brand_voice,
        product=product,
        constraints=constraints,
        note_style=note_style,
        narrative_framework=narrative_framework,
        provider=provider,
    )
    package = await workflow.generation.generate(request, report, tenant_id=tenant_id)
    package_data = package.model_dump(mode="json")
    package_data["creation_bundle"] = build_creation_bundle(package)
    result["status"] = "generated"
    result["package"] = package_data
    result["generate_request"] = request.model_dump(mode="json")
    return result