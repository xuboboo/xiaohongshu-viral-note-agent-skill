"""封面文案与笔记类型 / 叙事框架联动。"""

from __future__ import annotations

from typing import Any

from xhs_skill.generation.frameworks import (
    NarrativeFramework,
    NoteStyle,
    resolve_framework,
    resolve_note_style,
)
from xhs_skill.schemas.content import CoverOption, GenerateRequest, TitleCandidate
from xhs_skill.schemas.research import HotNotesReport

# style -> (supporting_tag, composition, visual_extra, subheadline_template)
_STYLE_COVER: dict[NoteStyle, dict[str, str]] = {
    NoteStyle.REVIEW: {
        "tag": "实测维度",
        "composition": "主体居中 + 底部评分条占位",
        "sub": "只写可验证维度 · 先看边界",
        "image": "产品特写，干净背景，可加维度小标签",
    },
    NoteStyle.SEEDING: {
        "tag": "场景种草",
        "composition": "生活场景主视觉，标题压上三分之一",
        "sub": "合不合你的场景，比口号重要",
        "image": "真实使用场景，自然光",
    },
    NoteStyle.AVOID_PITFALL: {
        "tag": "避坑",
        "composition": "警示色点缀 + 清单式副标题",
        "sub": "别只看宣传页 · 先排雷",
        "image": "对比/打叉示意，避免恐吓夸张",
    },
    NoteStyle.CHECKLIST: {
        "tag": "清单",
        "composition": "大字标题 + 勾选列表预览",
        "sub": "按优先级勾，不按情绪买",
        "image": "清单板/便签视觉，留白清晰",
    },
    NoteStyle.TUTORIAL: {
        "tag": "步骤",
        "composition": "步骤序号 1-2-3 视觉引导",
        "sub": "按顺序做，比一次记全参数更稳",
        "image": "过程分步截图风格",
    },
    NoteStyle.STORE_VISIT: {
        "tag": "探店",
        "composition": "环境广角 + 角标地点感（无假地址）",
        "sub": "动线与避雷 · 体验顺序",
        "image": "门店/空间氛围，不伪造地理位置",
    },
    NoteStyle.COMPARISON: {
        "tag": "对比",
        "composition": "左右分栏或 A/B 对照",
        "sub": "先定维度，再谈偏好",
        "image": "双主体并置，维度标签对齐",
    },
    NoteStyle.DECISION: {
        "tag": "怎么选",
        "composition": "主体居中，标题上方",
        "sub": "先看真实场景，不只看宣传页",
        "image": "清晰主体，决策感图标可弱化",
    },
}

_FRAMEWORK_SUB: dict[NarrativeFramework, str] = {
    NarrativeFramework.PAS: "痛点 → 方案",
    NarrativeFramework.AIDA: "抓住注意 → 推动行动",
    NarrativeFramework.BAB: "之前 → 之后 → 路径",
    NarrativeFramework.QUEST: "限定读者 → 可执行步骤",
    NarrativeFramework.FOUR_P: "画面 → 证明 → 推动",
    NarrativeFramework.SCQA: "情境 → 问题 → 回答",
    NarrativeFramework.AUTO: "场景决策",
}


def build_cover_options(
    request: GenerateRequest,
    *,
    titles: list[TitleCandidate] | None = None,
    report: HotNotesReport | None = None,
    selected_title: str = "",
    outline: dict[str, Any] | None = None,
) -> list[CoverOption]:
    """从类型/框架/标题/研究派生 2–3 个封面方案。"""
    topic = request.topic
    product = str(request.product.get("name", "") or topic) if isinstance(request.product, dict) else topic
    audience = request.target_audience or "正在做决策的用户"
    style = resolve_note_style(
        (outline or {}).get("note_style") or getattr(request, "note_style", None)
    )
    framework = resolve_framework(
        (outline or {}).get("narrative_framework") or getattr(request, "narrative_framework", None),
        style,
    )
    style_cfg = _STYLE_COVER.get(style, _STYLE_COVER[NoteStyle.DECISION])
    fw_label = _FRAMEWORK_SUB.get(framework, "场景决策")
    opening = str((outline or {}).get("opening_hook") or "")[:28]

    options: list[CoverOption] = []
    seen: set[str] = set()

    def _add(
        headline: str,
        subheadline: str,
        supporting_tag: str,
        composition: str,
        *,
        image_requirements: list[str] | None = None,
    ) -> None:
        key = headline.strip().lower()
        if not key or key in seen or len(options) >= 3:
            return
        seen.add(key)
        reqs = image_requirements or [
            "清晰主体",
            "避免过多文字",
            "保留真实质感",
            style_cfg["image"],
        ]
        options.append(
            CoverOption(
                headline=headline[:28],
                subheadline=subheadline[:40],
                supporting_tag=supporting_tag[:16],
                visual_subject=product,
                composition=composition,
                text_hierarchy="主标题 > 副标题 > 类型标签",
                image_requirements=reqs[:5],
            )
        )

    # 0) 大纲开场钩子 → 封面主标题（最贴框架）
    if opening:
        _add(
            opening,
            f"{style_cfg['sub']} · {fw_label}",
            style_cfg["tag"],
            style_cfg["composition"],
        )

    # 1) 标题候选（带类型副文案）
    for candidate in (titles or [])[:4]:
        title = (candidate.title or "").strip()
        if not title:
            continue
        mech = (candidate.mechanism or "").strip()
        _add(
            title,
            f"{mech or style_cfg['tag']} · {fw_label}",
            style_cfg["tag"] if not mech else mech[:16],
            style_cfg["composition"],
        )

    # 2) 研究机制
    if report:
        for mech in report.mechanisms[:2]:
            angle = (mech.topic_angle or mech.user_problem or "").strip()
            if not angle:
                continue
            _add(
                f"{topic}：{angle}"[:28],
                f"适合{mech.audience or audience} · {style_cfg['tag']}",
                style_cfg["tag"],
                "左文右图，场景优先",
            )

    # 3) 选中标题
    if selected_title:
        _add(
            selected_title,
            style_cfg["sub"],
            style_cfg["tag"],
            style_cfg["composition"],
        )

    # 4) 类型默认兜底
    defaults = [
        (f"{topic}｜{style_cfg['tag']}", style_cfg["sub"], style_cfg["tag"], style_cfg["composition"]),
        (f"{topic}给{audience[:6]}", fw_label, style_cfg["tag"], style_cfg["composition"]),
        (f"{product}适合谁", "说清楚不适合的人", "适合谁", "对比式左右分栏"),
    ]
    for headline, sub, tag, comp in defaults:
        _add(headline, sub, tag, comp)
        if len(options) >= 3:
            break

    return options[:3]