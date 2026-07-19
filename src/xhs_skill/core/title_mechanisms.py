"""标题机制 taxonomy：研究洞察与生成钩子共用，避免标签漂移。"""

from __future__ import annotations

import re
from typing import Final

# (pattern, label) — 只做结构标签，不鼓励编造亲测/功效
MECHANISM_PATTERNS: Final[list[tuple[str, str]]] = [
    (r"怎么选|如何选|值得买吗|值不值得", "决策搜索"),
    (r"避坑|别买|踩雷|翻车|别只看", "避坑警示"),
    (r"对比|VS|vs|还是|区别", "对比决策"),
    (r"清单|checklist|自检|核对表", "清单收藏"),
    (r"教程|步骤|手把手|怎么做", "教程转化"),
    (r"真实|亲测|实测|一周|个月", "实证种草"),
    (r"适合谁|不适合|哪类人", "人群边界"),
    (r"通勤|上班|差旅|学生|居家", "场景切片"),
    (r"\d+\s*[个件条招步点天周月年%％]|Top\s*\d+", "数字结果"),
    (r"今天|马上|最后|限时|赶紧|错过", "时间紧迫"),
    (r"预算|性价比|贵不贵|便宜|¥|￥|\d+\s*元", "价格锚点"),
    (r"反常识|没想到|原来|其实不|都说错", "反常识"),
    (r"新手|小白|第一次|入门", "新手友好"),
    (r"敏感肌|油皮|干皮|混干|混油", "人群边界"),
    (r"平价|学生党|性价比", "价格锚点"),
    (r"合集|攻略|指南", "清单收藏"),
    (r"开箱|横评", "实证种草"),
]

# 生成侧 hook 机制 → 与研究标签对齐的别名
HOOK_MECHANISM_ALIASES: Final[dict[str, str]] = {
    "搜索精准": "决策搜索",
    "长尾场景": "场景切片",
    "清单": "清单收藏",
    "对比决策": "对比决策",
    "避坑警示": "避坑警示",
    "失败边界": "人群边界",
    "经验教训": "避坑警示",
    "决策支持": "决策搜索",
    "人群定位": "人群边界",
    "克制专业": "决策搜索",
    "反差": "反常识",
    "场景切片": "场景切片",
    "关键词前置": "决策搜索",
    "问答体": "问答体",
    "决策对比": "对比决策",
    "数字清单": "数字结果",
    "真实体验": "实证种草",
    "问题解决": "决策搜索",
}


def normalize_mechanism(label: str) -> str:
    raw = (label or "").strip()
    if not raw:
        return "决策搜索"
    return HOOK_MECHANISM_ALIASES.get(raw, raw)


def tag_title_mechanisms(title: str, *, limit: int = 4) -> list[str]:
    """从标题抽取机制标签（去重保序）。"""
    text = title or ""
    tags: list[str] = []
    seen: set[str] = set()
    for pattern, label in MECHANISM_PATTERNS:
        if re.search(pattern, text, re.I):
            key = label.casefold()
            if key not in seen:
                seen.add(key)
                tags.append(label)
            if len(tags) >= limit:
                break
    return tags


def primary_title_mechanism(title: str) -> str:
    tags = tag_title_mechanisms(title, limit=1)
    return tags[0] if tags else "决策搜索"


def mechanism_coverage(titles: list[str], required: list[str]) -> dict[str, object]:
    """检查标题列表是否覆盖目标机制。"""
    present: set[str] = set()
    for title in titles:
        for tag in tag_title_mechanisms(title):
            present.add(normalize_mechanism(tag))
    need = [normalize_mechanism(item) for item in required if item]
    missing = [item for item in need if item not in present]
    return {
        "required": need,
        "present": sorted(present),
        "missing": missing,
        "covered": not missing,
    }