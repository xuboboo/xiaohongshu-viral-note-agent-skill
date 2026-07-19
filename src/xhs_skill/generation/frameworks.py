"""笔记类型与叙事框架：驱动大纲与正文骨架（通用创作方法论，无外部品牌痕迹）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class NoteStyle(StrEnum):
    """小红书常见内容形态。"""

    REVIEW = "review"  # 测评
    SEEDING = "seeding"  # 种草
    AVOID_PITFALL = "avoid_pitfall"  # 避坑
    CHECKLIST = "checklist"  # 清单
    TUTORIAL = "tutorial"  # 教程
    STORE_VISIT = "store_visit"  # 探店
    COMPARISON = "comparison"  # 对比
    DECISION = "decision"  # 决策/怎么选（默认）


class NarrativeFramework(StrEnum):
    """正文叙事框架。"""

    PAS = "pas"  # Problem-Agitate-Solution
    AIDA = "aida"  # Attention-Interest-Desire-Action
    BAB = "bab"  # Before-After-Bridge
    QUEST = "quest"  # Qualify-Understand-Educate-Stimulate-Transition
    FOUR_P = "four_p"  # Picture-Promise-Prove-Push
    SCQA = "scqa"  # Situation-Complication-Question-Answer
    AUTO = "auto"  # 按笔记类型自动选


# style -> 默认框架
_STYLE_DEFAULT_FRAMEWORK: dict[NoteStyle, NarrativeFramework] = {
    NoteStyle.REVIEW: NarrativeFramework.FOUR_P,
    NoteStyle.SEEDING: NarrativeFramework.AIDA,
    NoteStyle.AVOID_PITFALL: NarrativeFramework.PAS,
    NoteStyle.CHECKLIST: NarrativeFramework.SCQA,
    NoteStyle.TUTORIAL: NarrativeFramework.QUEST,
    NoteStyle.STORE_VISIT: NarrativeFramework.BAB,
    NoteStyle.COMPARISON: NarrativeFramework.SCQA,
    NoteStyle.DECISION: NarrativeFramework.PAS,
}

# 框架阶段定义：id, label, purpose
_FRAMEWORK_STAGES: dict[NarrativeFramework, list[dict[str, str]]] = {
    NarrativeFramework.PAS: [
        {"id": "problem", "label": "痛点", "purpose": "点出读者真实困扰"},
        {"id": "agitate", "label": "加剧", "purpose": "说明不解决的代价与常见误区"},
        {"id": "solution", "label": "方案", "purpose": "给出可执行判断标准与边界"},
        {"id": "proof", "label": "证据", "purpose": "可核对信息，不编造亲测"},
        {"id": "cta", "label": "行动", "purpose": "邀请补充场景"},
    ],
    NarrativeFramework.AIDA: [
        {"id": "attention", "label": "注意", "purpose": "强钩子开场"},
        {"id": "interest", "label": "兴趣", "purpose": "场景化展开"},
        {"id": "desire", "label": "欲望", "purpose": "收益与适用人群"},
        {"id": "action", "label": "行动", "purpose": "下一步与互动"},
    ],
    NarrativeFramework.BAB: [
        {"id": "before", "label": "之前", "purpose": "旧状态/旧做法的问题"},
        {"id": "after", "label": "之后", "purpose": "理想状态（不保证效果）"},
        {"id": "bridge", "label": "桥梁", "purpose": "如何从之前到之后的标准路径"},
        {"id": "boundary", "label": "边界", "purpose": "不适合谁"},
    ],
    NarrativeFramework.QUEST: [
        {"id": "qualify", "label": "限定", "purpose": "这篇适合谁读"},
        {"id": "understand", "label": "理解", "purpose": "问题本质"},
        {"id": "educate", "label": "教育", "purpose": "步骤或标准"},
        {"id": "stimulate", "label": "刺激", "purpose": "关键取舍"},
        {"id": "transition", "label": "过渡", "purpose": "下一步行动"},
    ],
    NarrativeFramework.FOUR_P: [
        {"id": "picture", "label": "画面", "purpose": "场景画面"},
        {"id": "promise", "label": "承诺", "purpose": "可验证的内容承诺（非功效保证）"},
        {"id": "prove", "label": "证明", "purpose": "参数/结构/边界证据"},
        {"id": "push", "label": "推动", "purpose": "决策清单与 CTA"},
    ],
    NarrativeFramework.SCQA: [
        {"id": "situation", "label": "情境", "purpose": "读者所处现状"},
        {"id": "complication", "label": "冲突", "purpose": "难点与信息噪音"},
        {"id": "question", "label": "问题", "purpose": "核心问题句"},
        {"id": "answer", "label": "回答", "purpose": "结构化答案"},
    ],
}

# 笔记类型专属段落提示
_STYLE_SECTION_HINTS: dict[NoteStyle, list[str]] = {
    NoteStyle.REVIEW: ["测评维度表", "优点", "缺点", "适合/不适合", "购买前核对清单"],
    NoteStyle.SEEDING: ["为什么值得关注", "场景契合点", "使用边界", "和同类差异", "怎么开始"],
    NoteStyle.AVOID_PITFALL: ["常见翻车", "错误筛选方式", "正确核对顺序", "红线清单", "自救办法"],
    NoteStyle.CHECKLIST: ["清单总览", "逐项标准", "优先级", "可打印要点", "收尾自检"],
    NoteStyle.TUTORIAL: ["前置条件", "步骤拆解", "耗时与难度", "失败重试", "进阶"],
    NoteStyle.STORE_VISIT: ["到店信息边界", "环境与动线", "点单/体验顺序", "避雷", "更适合谁"],
    NoteStyle.COMPARISON: ["对比维度", "类型 A", "类型 B", "决策矩阵", "怎么选"],
    NoteStyle.DECISION: ["三问判断", "证据要求", "场景分层", "不适合人群", "行动建议"],
}


def resolve_note_style(raw: str | None) -> NoteStyle:
    if not raw:
        return NoteStyle.DECISION
    key = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "测评": NoteStyle.REVIEW,
        "种草": NoteStyle.SEEDING,
        "避坑": NoteStyle.AVOID_PITFALL,
        "清单": NoteStyle.CHECKLIST,
        "教程": NoteStyle.TUTORIAL,
        "探店": NoteStyle.STORE_VISIT,
        "对比": NoteStyle.COMPARISON,
        "怎么选": NoteStyle.DECISION,
        "决策": NoteStyle.DECISION,
        "review": NoteStyle.REVIEW,
        "seeding": NoteStyle.SEEDING,
        "avoid": NoteStyle.AVOID_PITFALL,
        "avoid_pitfall": NoteStyle.AVOID_PITFALL,
        "checklist": NoteStyle.CHECKLIST,
        "tutorial": NoteStyle.TUTORIAL,
        "store": NoteStyle.STORE_VISIT,
        "store_visit": NoteStyle.STORE_VISIT,
        "comparison": NoteStyle.COMPARISON,
        "vs": NoteStyle.COMPARISON,
        "decision": NoteStyle.DECISION,
    }
    if key in aliases:
        return aliases[key]
    try:
        return NoteStyle(key)
    except ValueError:
        return NoteStyle.DECISION


def resolve_framework(
    raw: str | None,
    style: NoteStyle,
) -> NarrativeFramework:
    if not raw or str(raw).strip().lower() in {"", "auto"}:
        return _STYLE_DEFAULT_FRAMEWORK.get(style, NarrativeFramework.PAS)
    key = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "pas": NarrativeFramework.PAS,
        "aida": NarrativeFramework.AIDA,
        "bab": NarrativeFramework.BAB,
        "quest": NarrativeFramework.QUEST,
        "4p": NarrativeFramework.FOUR_P,
        "four_p": NarrativeFramework.FOUR_P,
        "scqa": NarrativeFramework.SCQA,
    }
    if key in aliases:
        return aliases[key]
    try:
        return NarrativeFramework(key)
    except ValueError:
        return _STYLE_DEFAULT_FRAMEWORK.get(style, NarrativeFramework.PAS)


def framework_stages(framework: NarrativeFramework) -> list[dict[str, str]]:
    if framework == NarrativeFramework.AUTO:
        framework = NarrativeFramework.PAS
    return list(_FRAMEWORK_STAGES.get(framework, _FRAMEWORK_STAGES[NarrativeFramework.PAS]))


def style_section_hints(style: NoteStyle) -> list[str]:
    return list(_STYLE_SECTION_HINTS.get(style, _STYLE_SECTION_HINTS[NoteStyle.DECISION]))


def describe_framework(framework: NarrativeFramework) -> str:
    labels = {
        NarrativeFramework.PAS: "痛点-加剧-方案",
        NarrativeFramework.AIDA: "注意-兴趣-欲望-行动",
        NarrativeFramework.BAB: "之前-之后-桥梁",
        NarrativeFramework.QUEST: "限定-理解-教育-刺激-过渡",
        NarrativeFramework.FOUR_P: "画面-承诺-证明-推动",
        NarrativeFramework.SCQA: "情境-冲突-问题-回答",
        NarrativeFramework.AUTO: "自动",
    }
    return labels.get(framework, framework.value)


def build_framework_meta(
    *,
    note_style: str | None = None,
    narrative_framework: str | None = None,
) -> dict[str, Any]:
    style = resolve_note_style(note_style)
    framework = resolve_framework(narrative_framework, style)
    return {
        "note_style": style.value,
        "note_style_label": {
            NoteStyle.REVIEW: "测评",
            NoteStyle.SEEDING: "种草",
            NoteStyle.AVOID_PITFALL: "避坑",
            NoteStyle.CHECKLIST: "清单",
            NoteStyle.TUTORIAL: "教程",
            NoteStyle.STORE_VISIT: "探店",
            NoteStyle.COMPARISON: "对比",
            NoteStyle.DECISION: "决策",
        }.get(style, style.value),
        "narrative_framework": framework.value,
        "framework_label": describe_framework(framework),
        "stages": framework_stages(framework),
        "style_sections": style_section_hints(style),
    }