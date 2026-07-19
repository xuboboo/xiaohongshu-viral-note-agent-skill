"""内容 Brief：从请求与研究报告抽出可执行创作纲要。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import HotNotesReport


def build_content_brief(
    request: GenerateRequest,
    report: HotNotesReport | None = None,
) -> dict[str, Any]:
    """产出结构化 brief，供生成/诊断/宿主展示。"""
    product = ""
    if isinstance(request.product, dict):
        product = str(request.product.get("name") or request.product.get("title") or "")
    audience = (request.target_audience or "").strip() or "正在做决策的用户"
    pain_points: list[str] = []
    angles: list[str] = []
    if report:
        for m in (report.mechanisms or [])[:4]:
            if m.user_problem:
                pain_points.append(m.user_problem[:48])
            if m.topic_angle:
                angles.append(m.topic_angle[:32])
        for gap in (report.content_gaps or [])[:4]:
            if isinstance(gap, dict) and gap.get("gap"):
                pain_points.append(str(gap["gap"])[:32])
    for c in request.constraints[:4]:
        text = str(c).strip()
        if text:
            pain_points.append(text[:40])

    # 去重保序
    def _uniq(items: list[str], n: int = 6) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = item.casefold()
            if key and key not in seen:
                seen.add(key)
                out.append(item)
            if len(out) >= n:
                break
        return out

    intent = "hybrid"
    if request.distribution_mode:
        intent = str(request.distribution_mode)
    objective = request.objective or "search_growth"

    promise = (
        request.topic_reason
        or (angles[0] if angles else "")
        or f"帮助{audience}用场景标准判断{request.topic}"
    )

    return {
        "topic": request.topic,
        "seed_topic": request.suggested_topic or request.topic,
        "product": product or request.topic,
        "audience": audience,
        "objective": objective,
        "distribution_intent": intent,
        "commercial_status": str(request.commercial_status),
        "angle": (request.topic_angle or (angles[0] if angles else "场景决策"))[:40],
        "content_promise": promise[:120],
        "pain_points": _uniq(pain_points, 5),
        "must_cover": _uniq(
            [
                "使用场景与频率",
                "最不能接受的问题",
                "证据是否具体",
                "不适合的人群",
                *([f"产品核对：{product}"] if product and product != request.topic else []),
            ],
            6,
        ),
        "forbidden": [
            "编造亲测经历",
            "伪造互动数据或销量排名",
            "未披露的商业合作口吻",
            "无法验证的功效承诺",
        ],
        "cta_goal": "引导补充具体场景或预算，而非空泛求赞",
        "evidence_count": len(request.evidence or []),
        "research_note_count": len(report.notes) if report else 0,
    }