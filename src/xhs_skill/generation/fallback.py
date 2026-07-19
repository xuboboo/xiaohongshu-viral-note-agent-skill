from __future__ import annotations

from uuid import uuid4

from xhs_skill.generation.checklist_pages import (
    checklist_pages,
    ensure_checkbox_body,
    is_checklist_style,
)
from xhs_skill.generation.hooks import expand_title_hooks
from xhs_skill.generation.outline import build_content_outline, render_body_from_outline
from xhs_skill.generation.video_storyboard import build_video_script
from xhs_skill.ranking import mmr_rerank, rank_titles
from xhs_skill.schemas.content import (
    GenerateRequest,
    GraphicPage,
    TitleCandidate,
    VideoScript,
)
from xhs_skill.schemas.research import ContentMechanism, HotNotesReport


def build_titles(
    request: GenerateRequest,
    report: HotNotesReport | None = None,
) -> list[TitleCandidate]:
    from xhs_skill.generation.mechanism_force import (
        ensure_mechanism_coverage,
        preferred_mechanisms_from_report,
    )

    candidates = expand_title_hooks(request)
    if not candidates:
        candidates = [
            TitleCandidate(
                id=str(uuid4()),
                title=f"{request.topic}怎么选？先看真实场景",
                mechanism="决策搜索",
                target_audience=request.target_audience or "正在做决策的用户",
                primary_keyword=request.topic,
            )
        ]
    preferred = preferred_mechanisms_from_report(report)
    if preferred:
        candidates, _cov = ensure_mechanism_coverage(
            candidates, request, preferred=preferred
        )
    ranked, relevance = rank_titles(candidates, request.topic)
    return mmr_rerank(ranked, relevance=relevance, limit=min(request.candidate_count, len(ranked)))


def _mechanism(report: HotNotesReport | None) -> ContentMechanism:
    if report and report.mechanisms:
        return report.mechanisms[0]
    return ContentMechanism(
        audience="正在研究该主题的用户",
        user_problem="信息很多，但不知道如何做适合自己的决定",
        topic_angle="决策支持",
        content_promise="用场景、标准和适用边界帮助做决定",
        title_mechanism="搜索精准",
        cover_mechanism="人群 + 关键问题",
        opening_mechanism="结论先行",
        body_structure=["结论", "判断标准", "场景", "不足", "适用人群"],
    )


def _product_name(request: GenerateRequest) -> str:
    name = request.product.get("name") if isinstance(request.product, dict) else None
    return str(name or request.topic)


def _evidence_hint(request: GenerateRequest) -> str:
    """把用户提供的证据来源写成一句可核对提示，不编造摘录内容。"""
    if not request.evidence:
        return "若你手头有参数表、说明书或实测截图，发布前逐条核对文中可验证说法。"
    sources: list[str] = []
    for item in request.evidence[:3]:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source") or item.get("url") or "").strip()
        if src:
            sources.append(src[:80])
    if not sources:
        return "你已提供证据条目，发布前请确认每条客观说法都有对应摘录绑定。"
    return "可优先核对这些来源：" + "；".join(sources) + "。"


def _scene_lines(request: GenerateRequest, report: HotNotesReport | None) -> list[str]:
    """短场景句：来自受众、产品、机制，避免长模板同质。"""
    lines: list[str] = []
    audience = (request.target_audience or "").strip()
    if audience:
        lines.append(f"目标读者更像：{audience[:40]}。")
    product = _product_name(request)
    if product and product != request.topic:
        lines.append(f"讨论对象侧重「{product}」，仍以你的使用边界为准。")
    mechanism = _mechanism(report)
    if mechanism.user_problem and mechanism.user_problem != "信息很多，但不知道如何做适合自己的决定":
        lines.append(f"常见卡点：{mechanism.user_problem[:48]}。")
    if mechanism.topic_angle and mechanism.topic_angle not in {"决策支持", ""}:
        lines.append(f"内容角度：{mechanism.topic_angle[:32]}。")
    for c in request.constraints[:2]:
        text = str(c).strip()
        if text:
            lines.append(f"约束：{text[:40]}。")
    return lines[:4]


def pages_from_body(
    request: GenerateRequest,
    body: str,
    report: HotNotesReport | None = None,
    *,
    outline: dict | None = None,
) -> list[GraphicPage]:
    """按最终正文切分页；清单类型走 checkbox 分页。"""
    if is_checklist_style(request, outline):
        return checklist_pages(request, body)

    mechanism = _mechanism(report)
    chunks = [part.strip() for part in body.split("\n\n") if part.strip()]
    if not chunks:
        chunks = [body.strip() or request.topic]

    # 封面 headline 优先大纲开场 / 类型标签
    cover_headline = (request.topic[:18] + "怎么选") if len(request.topic) < 20 else request.topic[:24]
    if outline and outline.get("opening_hook"):
        cover_headline = str(outline["opening_hook"])[:28]
    elif outline and outline.get("note_style_label"):
        cover_headline = f"{request.topic[:14]}｜{outline['note_style_label']}"

    pages: list[GraphicPage] = [
        GraphicPage(
            page=1,
            purpose="cover",
            headline=cover_headline,
            body_copy=chunks[0][:80],
            visual_direction="主题主体 + 清晰大字",
            layout="上图下字",
        )
    ]
    purposes = ["conclusion", "scenario", "pain", "trust", "boundary", "summary"]
    # 若有大纲 sections，purpose 跟 stage
    stage_ids = [s.get("stage_id") for s in (outline or {}).get("sections") or [] if isinstance(s, dict)]
    for index, chunk in enumerate(chunks[:6]):
        purpose = (
            str(stage_ids[index])
            if index < len(stage_ids) and stage_ids[index]
            else purposes[min(index, len(purposes) - 1)]
        )
        first_line = chunk.split("\n", 1)[0][:28]
        pages.append(
            GraphicPage(
                page=index + 2,
                purpose=purpose,
                headline=first_line or f"要点{index + 1}",
                body_copy=chunk[:160],
                visual_direction="与正文段落对应的图文卡片",
            )
        )
    if len(pages) < 3:
        pages.append(
            GraphicPage(
                page=len(pages) + 1,
                purpose="summary",
                headline="最后记住",
                body_copy=mechanism.content_promise or "用自己的场景做决定。",
                visual_direction="简洁总结页",
            )
        )
    return pages


def build_body(
    request: GenerateRequest, report: HotNotesReport | None
) -> tuple[str, list[GraphicPage]]:
    """按 note_style + narrative_framework 大纲渲染离线正文。"""
    outline = build_content_outline(
        request,
        report,
        note_style=getattr(request, "note_style", None),
        narrative_framework=getattr(request, "narrative_framework", None),
        variant_index=int(getattr(request, "variant_index", 0) or 0),
    )
    body = render_body_from_outline(request, outline, report)
    scenes = _scene_lines(request, report)
    evidence_line = _evidence_hint(request)
    extras: list[str] = []
    if scenes:
        extras.append("上下文补充：\n" + "\n".join(f"- {line}" for line in scenes))
    if evidence_line:
        extras.append(evidence_line)
    if extras:
        body = body.rstrip() + "\n\n" + "\n\n".join(extras) + "\n"
    if is_checklist_style(request, outline):
        body = ensure_checkbox_body(body)
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")
    pages = pages_from_body(request, body, report, outline=outline)
    return body, pages


def build_video(
    request: GenerateRequest,
    body: str,
    *,
    outline: dict | None = None,
    duration_seconds: int | None = None,
) -> VideoScript:
    return build_video_script(
        request,
        body,
        duration_seconds=duration_seconds,
        outline=outline,
    )