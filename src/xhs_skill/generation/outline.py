"""内容大纲：框架阶段 × 笔记类型 → 可执行 outline + 开场钩子 + 情绪曲线 + CTA。"""

from __future__ import annotations

from typing import Any

from xhs_skill.generation.frameworks import (
    NarrativeFramework,
    NoteStyle,
    build_framework_meta,
    framework_stages,
    resolve_framework,
    resolve_note_style,
    style_section_hints,
)
from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import HotNotesReport

# 开场钩子按类型
_OPENING_HOOKS: dict[NoteStyle, list[str]] = {
    NoteStyle.REVIEW: [
        "先说结论：{topic}适不适合你，取决于这 3 个核对点。",
        "别急着看卖点——{topic}测评我只保留可验证维度。",
        "{audience}如果在犹豫{topic}，先看边界再看优点。",
    ],
    NoteStyle.SEEDING: [
        "如果最近在找{topic}，这版只讲「场景合不合」不讲口号。",
        "{topic}值不值得关注：用你的真实使用频率判断。",
        "种草之前先划线：{topic}更适合谁、不适合谁。",
    ],
    NoteStyle.AVOID_PITFALL: [
        "第一次选{topic}，这几类翻车最常见。",
        "避坑优先：{topic}别只盯宣传页上的那一行字。",
        "关于{topic}，我更建议先确认你不能接受什么。",
    ],
    NoteStyle.CHECKLIST: [
        "{topic}清单版：按优先级勾，不按情绪买。",
        "把{topic}拆成可勾选的 {n} 条标准。",
        "收藏向：{topic}自检表（含不适合人群）。",
    ],
    NoteStyle.TUTORIAL: [
        "{topic}步骤拆解：从准备到收尾，按顺序做。",
        "新手向{topic}：每步只保留必要动作。",
        "按这个顺序做{topic}，比一次记完全部参数更稳。",
    ],
    NoteStyle.STORE_VISIT: [
        "探店记录边界：只写可核对的体验顺序与注意点。",
        "到店前先看：{topic}动线与避雷点。",
        "{topic}体验顺序建议：先看环境再决定是否深入。",
    ],
    NoteStyle.COMPARISON: [
        "{topic}对比不站队：先定维度，再谈偏好。",
        "两版{topic}怎么选：用矩阵代替「谁更好」。",
        "别问谁绝：问你的场景更吃哪一列指标。",
    ],
    NoteStyle.DECISION: [
        "选{topic}时，不要先被单一卖点带着走。",
        "{audience}判断{topic}：先答 3 个问题。",
        "结论先行：{topic}适不适合，看场景与证据密度。",
    ],
}

# 情绪曲线节点（用于分镜/分页提示，非心理操控）
_EMOTION_ARCS: dict[NarrativeFramework, list[dict[str, str]]] = {
    NarrativeFramework.PAS: [
        {"beat": "hook", "emotion": "紧张", "goal": "共鸣痛点"},
        {"beat": "deepen", "emotion": "焦虑缓解前的清醒", "goal": "暴露误区"},
        {"beat": "resolve", "emotion": "掌控感", "goal": "给标准"},
        {"beat": "close", "emotion": "平稳", "goal": "行动与边界"},
    ],
    NarrativeFramework.AIDA: [
        {"beat": "hook", "emotion": "好奇", "goal": "抓住注意"},
        {"beat": "deepen", "emotion": "兴趣", "goal": "场景展开"},
        {"beat": "resolve", "emotion": "向往但克制", "goal": "收益与边界"},
        {"beat": "close", "emotion": "行动意愿", "goal": "明确下一步"},
    ],
    NarrativeFramework.BAB: [
        {"beat": "hook", "emotion": "共鸣", "goal": "旧状态"},
        {"beat": "deepen", "emotion": "希望", "goal": "理想状态"},
        {"beat": "resolve", "emotion": "踏实", "goal": "路径"},
        {"beat": "close", "emotion": "清醒", "goal": "边界"},
    ],
    NarrativeFramework.QUEST: [
        {"beat": "hook", "emotion": "被看见", "goal": "限定读者"},
        {"beat": "deepen", "emotion": "理解", "goal": "教育"},
        {"beat": "resolve", "emotion": "动力", "goal": "关键取舍"},
        {"beat": "close", "emotion": "行动", "goal": "过渡"},
    ],
    NarrativeFramework.FOUR_P: [
        {"beat": "hook", "emotion": "画面感", "goal": "场景"},
        {"beat": "deepen", "emotion": "信任萌芽", "goal": "承诺范围"},
        {"beat": "resolve", "emotion": "可信", "goal": "证明"},
        {"beat": "close", "emotion": "决策", "goal": "推动"},
    ],
    NarrativeFramework.SCQA: [
        {"beat": "hook", "emotion": "熟悉", "goal": "情境"},
        {"beat": "deepen", "emotion": "张力", "goal": "冲突"},
        {"beat": "resolve", "emotion": "聚焦", "goal": "问题"},
        {"beat": "close", "emotion": "清晰", "goal": "回答"},
    ],
}

_CTA_BANK: dict[str, list[str]] = {
    "comment": [
        "你选{topic}最在意哪一点？预算 / 场景 / 耐用，留一个就行。",
        "如果已经踩过坑，最想提醒新手的是哪一步？",
        "需要我按通勤 / 居家 / 差旅拆一版吗？留言场景。",
    ],
    "save": [
        "需要对照时收藏这版判断标准，别只存情绪种草。",
        "把核对清单收起来，下次决策直接勾。",
    ],
    "share": [
        "如果朋友也在纠结{topic}，把判断标准转给他比安利口号有用。",
    ],
    "dm_safe": [
        "不私聊导流；公开评论区补充场景，我按条件帮你缩小范围。",
    ],
}


def _product(request: GenerateRequest) -> str:
    if isinstance(request.product, dict):
        name = str(request.product.get("name") or "").strip()
        if name:
            return name
    return request.topic


def _audience(request: GenerateRequest) -> str:
    return (request.target_audience or "正在做决策的人").strip()[:20]


def pick_opening_hook(
    request: GenerateRequest,
    style: NoteStyle,
    *,
    index: int = 0,
) -> str:
    pool = _OPENING_HOOKS.get(style) or _OPENING_HOOKS[NoteStyle.DECISION]
    template = pool[index % len(pool)]
    return template.format(
        topic=request.topic,
        audience=_audience(request),
        product=_product(request),
        n=5,
    )


def pick_cta(request: GenerateRequest, *, kind: str = "comment", index: int = 0) -> str:
    pool = _CTA_BANK.get(kind) or _CTA_BANK["comment"]
    template = pool[index % len(pool)]
    return template.format(topic=request.topic, audience=_audience(request))


def build_content_outline(
    request: GenerateRequest,
    report: HotNotesReport | None = None,
    *,
    note_style: str | None = None,
    narrative_framework: str | None = None,
    variant_index: int = 0,
) -> dict[str, Any]:
    """生成结构化大纲，供模型与离线模板共用。"""
    style = resolve_note_style(note_style or getattr(request, "note_style", None))
    framework = resolve_framework(
        narrative_framework or getattr(request, "narrative_framework", None),
        style,
    )
    meta = build_framework_meta(note_style=style.value, narrative_framework=framework.value)
    stages = framework_stages(framework)
    style_hints = style_section_hints(style)
    audience = _audience(request)
    product = _product(request)
    pain = ""
    if report and report.mechanisms:
        pain = (report.mechanisms[0].user_problem or "")[:48]
    if not pain and request.constraints:
        pain = str(request.constraints[0])[:48]
    if not pain:
        pain = f"信息很多，不知道如何判断{request.topic}"

    sections: list[dict[str, Any]] = []
    for i, stage in enumerate(stages):
        hint = style_hints[i] if i < len(style_hints) else stage["purpose"]
        sections.append(
            {
                "order": i + 1,
                "stage_id": stage["id"],
                "title": stage["label"],
                "purpose": stage["purpose"],
                "writing_hint": hint,
                "must_include": _section_must_include(
                    stage["id"], request, audience=audience, product=product, pain=pain
                ),
            }
        )

    # 类型专属附加节
    for j, hint in enumerate(style_hints[len(sections) : len(sections) + 2]):
        sections.append(
            {
                "order": len(sections) + 1,
                "stage_id": f"style_{j}",
                "title": hint,
                "purpose": "类型强化",
                "writing_hint": hint,
                "must_include": [hint, "保持可验证、不编造"],
            }
        )

    opening = pick_opening_hook(request, style, index=variant_index)
    cta = pick_cta(request, kind="comment", index=variant_index)
    emotion = list(
        _EMOTION_ARCS.get(framework, _EMOTION_ARCS[NarrativeFramework.PAS])
    )

    word_count = _suggest_word_count(style, request)
    return {
        **meta,
        "topic": request.topic,
        "audience": audience,
        "product": product,
        "opening_hook": opening,
        "closing_cta": cta,
        "cta_variants": {
            "comment": pick_cta(request, kind="comment", index=0),
            "save": pick_cta(request, kind="save", index=0),
            "share": pick_cta(request, kind="share", index=0),
        },
        "emotion_arc": emotion,
        "sections": sections[:8],
        "suggested_word_count": word_count,
        "suggested_page_count": 6 if request.format.value == "graphic" else 0,
        "suggested_duration_seconds": 45 if str(request.format) == "video" or getattr(request.format, "value", "") == "video" else None,
        "checklist_before_publish": [
            "标题承诺是否在首段兑现",
            "是否写明不适合人群",
            "客观说法是否有 evidence",
            "商业合作是否披露",
            "话题标签是否与正文一致",
        ],
    }


def _section_must_include(
    stage_id: str,
    request: GenerateRequest,
    *,
    audience: str,
    product: str,
    pain: str,
) -> list[str]:
    topic = request.topic
    mapping: dict[str, list[str]] = {
        "problem": [pain, f"{audience}常见困扰"],
        "agitate": ["错误筛选方式", "只看宣传的风险"],
        "solution": [f"{topic}判断标准", "使用频率与场景"],
        "proof": ["可核对来源", "限制条件"],
        "cta": ["具体问题引导"],
        "attention": [f"{topic}钩子", "场景画面"],
        "interest": [f"适合{audience}的细节"],
        "desire": ["收益边界", "不保证功效"],
        "action": ["下一步"],
        "before": ["旧做法问题"],
        "after": ["理想状态描述（不承诺）"],
        "bridge": ["路径步骤"],
        "boundary": ["不适合谁"],
        "qualify": ["谁该读这篇"],
        "understand": ["问题本质"],
        "educate": ["步骤或标准"],
        "stimulate": ["关键取舍"],
        "transition": ["行动"],
        "picture": [f"{product}使用画面"],
        "promise": ["内容承诺范围"],
        "prove": ["证据点"],
        "push": ["决策清单"],
        "situation": ["现状"],
        "complication": ["信息噪音"],
        "question": [f"核心问题：如何选{topic}"],
        "answer": ["结构化答案"],
    }
    return mapping.get(stage_id, [stage_id, topic])


def _suggest_word_count(style: NoteStyle, request: GenerateRequest) -> dict[str, int]:
    base = {
        NoteStyle.CHECKLIST: (350, 700),
        NoteStyle.TUTORIAL: (450, 900),
        NoteStyle.REVIEW: (400, 800),
        NoteStyle.COMPARISON: (400, 850),
    }.get(style, (320, 650))
    return {"min": base[0], "max": base[1], "target": (base[0] + base[1]) // 2}


def render_body_from_outline(
    request: GenerateRequest,
    outline: dict[str, Any],
    report: HotNotesReport | None = None,
) -> str:
    """离线确定性正文：按大纲段落展开，避免单一模板。"""
    topic = request.topic
    audience = outline.get("audience") or _audience(request)
    product = outline.get("product") or _product(request)
    opening = outline.get("opening_hook") or f"关于{topic}，先对齐场景。"
    parts: list[str] = [
        opening,
        "",
        f"（结构：{outline.get('framework_label', '')} · {outline.get('note_style_label', '')}；"
        "离线骨架，请替换为你的真实事实后再发。）",
        "",
    ]
    for sec in outline.get("sections") or []:
        title = sec.get("title") or sec.get("stage_id")
        purpose = sec.get("purpose") or ""
        hints = sec.get("must_include") or []
        hint_line = "；".join(str(h) for h in hints[:3])
        parts.append(f"【{title}】{purpose}")
        parts.append(f"围绕：{hint_line}。结合{audience}与{product}写具体、可核对的信息，禁止编造亲测。")
        parts.append("")

    cta = outline.get("closing_cta") or pick_cta(request)
    parts.append(cta)
    body = "\n".join(parts)
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")
    return body.strip() + "\n"