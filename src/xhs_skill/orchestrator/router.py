from __future__ import annotations

from xhs_skill.schemas.common import RiskLevel, TaskMode

KEYWORDS: list[tuple[TaskMode, tuple[str, ...]]] = [
    (TaskMode.SEARCH_HOT_NOTES, ("热门笔记", "当前爆款", "热榜", "热门内容")),
    (TaskMode.SEARCH_TRENDING_TOPICS, ("趋势", "热门话题", "上升话题")),
    (TaskMode.QUERY_ACCOUNT_WEIGHT, ("账号权重", "账号健康", "流量权重")),
    (TaskMode.AUTHENTICATE_ACCOUNT, ("扫码登录", "自动登录", "登录账号")),
    (TaskMode.PUBLISH_NOTE, ("自动发布", "发布笔记", "定时发布")),
    (TaskMode.REWRITE_NOTE, ("改写", "去AI味", "润色")),
    (TaskMode.DIAGNOSE_NOTE, ("诊断", "为什么数据不好", "分析这篇笔记")),
    (TaskMode.CREATE_NOTE, ("写一篇", "生成笔记", "小红书文案", "图文笔记", "口播稿")),
]


def route_task(text: str) -> dict:
    matched = []
    for mode, keywords in KEYWORDS:
        if any(keyword.lower() in text.lower() for keyword in keywords):
            matched.append(mode)
    primary = matched[0] if matched else TaskMode.CREATE_NOTE
    high_risk = primary in {TaskMode.PUBLISH_NOTE, TaskMode.AUTHENTICATE_ACCOUNT}
    return {
        "primary_mode": primary,
        "secondary_modes": matched[1:],
        "commercial_status": "REVIEW",
        "research_required": primary
        in {TaskMode.SEARCH_HOT_NOTES, TaskMode.SEARCH_TRENDING_TOPICS, TaskMode.CREATE_NOTE},
        "risk_level": RiskLevel.HIGH if high_risk else RiskLevel.LOW,
        "confidence": 0.92 if matched else 0.6,
    }
