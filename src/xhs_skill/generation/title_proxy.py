"""标题可解释代理分：机制覆盖 + 长度 + 搜索意图，非平台 CTR。"""

from __future__ import annotations

from typing import Any

from xhs_skill.core.title_mechanisms import normalize_mechanism, tag_title_mechanisms
from xhs_skill.schemas.content import TitleCandidate


def score_title_proxy(
    title: str,
    *,
    topic: str = "",
    preferred_mechanisms: list[str] | None = None,
) -> dict[str, Any]:
    """0–100 代理分 + 分项解释。"""
    text = (title or "").strip()
    length = len(text)
    # 长度：8–22 最佳
    if 8 <= length <= 22:
        length_score = 100.0
    elif 6 <= length <= 28:
        length_score = 75.0
    else:
        length_score = 45.0

    mechs = [normalize_mechanism(m) for m in tag_title_mechanisms(text)]
    preferred = [normalize_mechanism(m) for m in (preferred_mechanisms or []) if m]
    if preferred:
        hit = sum(1 for m in preferred if m in mechs)
        mech_score = 100.0 * hit / max(len(preferred), 1)
        mech_score = min(100.0, mech_score + (20 if mechs else 0))
    else:
        mech_score = min(100.0, 40.0 + 20.0 * len(mechs))

    topic_hit = 0.0
    if topic and topic[:4] in text:
        topic_hit = 100.0
    elif topic:
        # 部分字符重叠
        overlap = sum(1 for ch in topic[:6] if ch in text)
        topic_hit = min(100.0, overlap * 18)

    question_bonus = 12.0 if ("？" in text or "?" in text) else 0.0
    hype_penalty = 0.0
    for bad in ("根治", "100%", "闭眼冲", "必入", "永久"):
        if bad in text:
            hype_penalty += 15.0

    raw = (
        0.35 * mech_score
        + 0.25 * length_score
        + 0.30 * topic_hit
        + question_bonus
        - hype_penalty
    )
    score = round(max(0.0, min(100.0, raw)), 1)
    reasons: list[str] = []
    if mechs:
        reasons.append("机制：" + "、".join(mechs[:3]))
    if 8 <= length <= 22:
        reasons.append("标题长度适中")
    elif length:
        reasons.append(f"标题长度 {length}，建议 8–22 字")
    if topic_hit >= 60:
        reasons.append("覆盖主题词")
    if question_bonus:
        reasons.append("问句利于搜索点击")
    if hype_penalty:
        reasons.append("含绝对化/夸张表述，已降分")

    return {
        "score": score,
        "components": {
            "mechanism": round(mech_score, 1),
            "length": round(length_score, 1),
            "topic_relevance": round(topic_hit, 1),
            "question_bonus": question_bonus,
            "hype_penalty": hype_penalty,
        },
        "mechanisms": mechs,
        "reasons": reasons[:5],
        "score_type": "TITLE_PROXY_SCORE",
        "disclaimer": "标题代理分仅供排序参考，不是平台真实 CTR。",
    }


def annotate_title_candidates(
    candidates: list[TitleCandidate],
    *,
    topic: str = "",
    preferred_mechanisms: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in candidates:
        proxy = score_title_proxy(
            item.title, topic=topic, preferred_mechanisms=preferred_mechanisms
        )
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "mechanism": item.mechanism,
                "proxy": proxy,
            }
        )
    rows.sort(key=lambda r: float(r["proxy"]["score"]), reverse=True)
    return rows