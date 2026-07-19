"""关键词 / 可发现性 map：主词、长尾、场景词、避坑词。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import HotNotesReport


def build_keyword_map(
    request: GenerateRequest,
    report: HotNotesReport | None = None,
    *,
    topics: list[str] | None = None,
) -> dict[str, Any]:
    topic = request.topic.strip()
    audience = (request.target_audience or "").strip()
    product = ""
    if isinstance(request.product, dict):
        product = str(request.product.get("name") or "").strip()

    secondary = [
        f"{topic}怎么选",
        f"{topic}避坑",
        f"{topic}适合谁",
        f"{topic}推荐吗",
    ]
    if audience:
        secondary.insert(0, f"{audience}{topic}")
    if product and product != topic:
        secondary.append(f"{product}怎么样")

    long_tail = [
        f"上班族{topic}",
        f"新手{topic}攻略",
        f"{topic}预算怎么定",
        f"{topic}和同类怎么比",
    ]
    if audience:
        long_tail.append(f"{audience}选{topic}注意什么")

    scene_terms: list[str] = []
    if report:
        for t in (report.trends or [])[:6]:
            if t.topic and t.topic not in scene_terms:
                scene_terms.append(t.topic)
        for m in (report.mechanisms or [])[:3]:
            if m.topic_angle:
                scene_terms.append(m.topic_angle[:16])

    for item in topics or []:
        if item and item not in scene_terms:
            scene_terms.append(item)

    # 去重保序
    def _uniq(items: list[str], n: int) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in items:
            text = str(raw).strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= n:
                break
        return out

    return {
        "primary_keyword": topic,
        "secondary_keywords": _uniq(secondary, 8),
        "long_tail_queries": _uniq(long_tail, 8),
        "scene_keywords": _uniq(scene_terms, 10),
        "negative_keywords": ["闭眼入", "全网第一", "100%有效", "官方热榜"],
        "title_should_include": _uniq([topic, *(secondary[:2])], 4),
        "body_should_cover": ["使用场景", "判断标准", "不适合人群", "可核验证据"],
    }