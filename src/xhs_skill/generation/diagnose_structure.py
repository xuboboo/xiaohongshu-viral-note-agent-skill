"""交付包结构诊断：可解释的检查项，替代死模板 fixes。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.content import DeliveryPackage


def structure_checks(
    *,
    title: str = "",
    body: str = "",
    package: DeliveryPackage | None = None,
    topics: list[str] | None = None,
    hashtags: list[str] | None = None,
    cta: str = "",
    pinned_comment: str = "",
    graphic_page_count: int | None = None,
    unverified_claim_count: int | None = None,
) -> dict[str, Any]:
    """返回 checks + recommended_fixes（仅基于真实检查）。"""
    if package is not None:
        title = package.selected_title or title
        body = package.body or body
        topics = package.topics or topics
        hashtags = package.hashtags or hashtags
        cta = package.cta or cta
        pinned_comment = package.pinned_comment or pinned_comment
        graphic_page_count = len(package.graphic_pages)
        unverified_claim_count = sum(1 for c in package.claims if not c.verified)

    topics = topics or []
    hashtags = hashtags or []
    first_para = (body or "").strip().split("\n\n", 1)[0]
    title_tokens = [t for t in (title or "").replace("？", " ").replace("?", " ").split() if len(t) >= 2]
    # 中文：标题前 6 字是否出现在首段
    title_core = (title or "").strip()[:8]
    title_in_opening = bool(title_core and title_core[:4] in first_para) or any(
        tok in first_para for tok in title_tokens[:3]
    )

    checks = {
        "title_present": bool((title or "").strip()),
        "body_present": len((body or "").strip()) >= 40,
        "title_reflected_in_opening": title_in_opening,
        "topics_present": len(topics) + len(hashtags) >= 1,
        "hashtag_in_body": any(h in (body or "") for h in hashtags[:5]) if hashtags else True,
        "cta_present": bool((cta or "").strip()),
        "pinned_comment_present": bool((pinned_comment or "").strip()),
        "graphic_pages_ok": (
            graphic_page_count is None or graphic_page_count == 0 or graphic_page_count >= 2
        ),
        "unverified_claims_ok": (unverified_claim_count or 0) == 0,
    }

    fixes: list[str] = []
    if not checks["title_present"]:
        fixes.append("补全标题，并保证首段回应标题承诺")
    if not checks["body_present"]:
        fixes.append("正文过短：补充场景、判断标准与适用边界")
    if checks["title_present"] and not checks["title_reflected_in_opening"]:
        fixes.append("标题未在首段兑现：开头点明主题与结论")
    if not checks["topics_present"]:
        fixes.append("补充 topics/hashtags 以提升可发现性")
    if hashtags and not checks["hashtag_in_body"]:
        fixes.append("正文末尾补充话题标签，与 topics 字段一致")
    if not checks["cta_present"]:
        fixes.append("补充 CTA（行动号召）")
    if not checks["pinned_comment_present"]:
        fixes.append("补充置顶评论引导")
    if graphic_page_count is not None and graphic_page_count > 0 and not checks["graphic_pages_ok"]:
        fixes.append("图文分页过少：至少 2 页并与正文对齐")
    if not checks["unverified_claims_ok"]:
        fixes.append(f"存在 {unverified_claim_count} 条未验证客观说法：删改或补 evidence")

    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "recommended_fixes": fixes[:10],
    }