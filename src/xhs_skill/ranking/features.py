from __future__ import annotations

import re

from xhs_skill.schemas.content import TitleCandidate

# 特征顺序与 LambdaMART metadata 绑定；扩展时需同步 retrain
FEATURE_ORDER = [
    "length",
    "keyword",
    "number",
    "specificity",
    "mechanism_diversity",
    "risk_penalty",
    "hook_strength",
    "search_intent",
    "readability",
    "emoji_penalty",
]


def title_features(title: str, keyword: str, mechanism: str) -> dict[str, float]:
    """可审计的标题特征（规则可解释 + LTR 输入）。"""
    length_score = max(0.0, 1 - abs(len(title) - 18) / 28)
    keyword_score = 1.0 if keyword and keyword.lower() in title.lower() else 0.5
    number_score = 1.0 if re.search(r"\d+", title) else 0.4
    specificity = min(
        1.0, (sum(ch.isdigit() for ch in title) + len(set(title))) / max(len(title), 1)
    )
    risk = 0.0
    if any(word in title for word in ("100%", "最好", "唯一", "闭眼冲", "必买", "第一名")):
        risk = 1.0

    # 钩子：问号/反差/清单感
    hook = 0.4
    if "？" in title or "?" in title:
        hook += 0.25
    if any(token in title for token in ("别", "不要", "真相", "踩坑", "避坑", "真正")):
        hook += 0.2
    if re.search(r"\d+\s*[个条点件岁天]", title) or re.search(r"[一二三四五六七八九十]+个", title):
        hook += 0.15
    hook = min(1.0, hook)

    # 搜索意图：怎么/适合/对比/清单
    intent = 0.3
    if any(token in title for token in ("怎么", "如何", "哪款", "哪个", "值得", "推荐")):
        intent += 0.35
    if any(token in title for token in ("适合", "不适合", "对比", "区别", "清单", "攻略")):
        intent += 0.25
    if keyword and keyword[:2] in title:
        intent += 0.1
    intent = min(1.0, intent)

    # 可读性：过长/过短惩罚已在 length；再看标点密度
    punct = sum(title.count(ch) for ch in "，。！？、…·|｜/")
    readability = max(0.0, 1.0 - punct * 0.12)
    if 10 <= len(title) <= 28:
        readability = min(1.0, readability + 0.15)

    emoji_hits = len(re.findall(r"[\U0001F300-\U0001FAFF✨⭐🔥💯✅❌]", title))
    emoji_penalty = min(1.0, emoji_hits * 0.35)

    return {
        "length": round(length_score, 4),
        "keyword": keyword_score,
        "number": number_score,
        "specificity": round(specificity, 4),
        "mechanism_diversity": 1.0 if mechanism else 0.5,
        "risk_penalty": risk,
        "hook_strength": round(hook, 4),
        "search_intent": round(intent, 4),
        "readability": round(readability, 4),
        "emoji_penalty": round(emoji_penalty, 4),
    }


def score_title(candidate: TitleCandidate) -> float:
    scores = candidate.scores
    return (
        0.18 * scores.get("length", 0)
        + 0.18 * scores.get("keyword", 0)
        + 0.10 * scores.get("number", 0)
        + 0.12 * scores.get("specificity", 0)
        + 0.10 * scores.get("mechanism_diversity", 0)
        + 0.12 * scores.get("hook_strength", 0)
        + 0.12 * scores.get("search_intent", 0)
        + 0.08 * scores.get("readability", 0)
        - 0.45 * scores.get("risk_penalty", 0)
        - 0.25 * scores.get("emoji_penalty", 0)
    )