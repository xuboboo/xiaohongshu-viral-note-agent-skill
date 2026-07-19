from __future__ import annotations

from datetime import UTC, datetime, timedelta

from xhs_skill.operations.models import ContentCalendarItem, SeriesPlan
from xhs_skill.schemas.account import AccountProfile


def build_content_calendar(
    *,
    account_id: str,
    topics: list[str] | None = None,
    profile: AccountProfile | None = None,
    tenant_id: str = "local",
    days: int = 30,
    posts_per_week: int = 3,
    start_at: datetime | None = None,
    fallback_topics: list[str] | None = None,
) -> list[ContentCalendarItem]:
    resolved = [str(t).strip() for t in (topics or []) if str(t).strip()]
    if not resolved and fallback_topics:
        resolved = [str(t).strip() for t in fallback_topics if str(t).strip()]
    if not resolved and profile and profile.content_pillars:
        resolved = list(profile.content_pillars)
    if not resolved:
        raise ValueError(
            "At least one topic is required (pass topics or fallback_topics / profile pillars)"
        )
    topics = resolved
    start = start_at or datetime.now(UTC)
    preferred_days = profile.optimal_publish_days if profile and profile.optimal_publish_days else [1, 3, 6]
    preferred_hours = profile.optimal_publish_hours if profile and profile.optimal_publish_hours else [20]
    pillars = profile.content_pillars if profile and profile.content_pillars else topics
    items: list[ContentCalendarItem] = []
    day = start.date()
    end = day + timedelta(days=days)
    topic_index = 0
    while day < end:
        if day.weekday() in preferred_days[:posts_per_week]:
            scheduled = datetime.combine(day, datetime.min.time(), tzinfo=start.tzinfo or UTC).replace(
                hour=preferred_hours[len(items) % len(preferred_hours)]
            )
            items.append(
                ContentCalendarItem(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    scheduled_at=scheduled,
                    topic=topics[topic_index % len(topics)],
                    content_pillar=pillars[topic_index % len(pillars)],
                    objective=("search_growth" if topic_index % 2 == 0 else "engagement_growth"),
                    format=(profile.preferred_formats[0] if profile and profile.preferred_formats else "graphic"),
                )
            )
            topic_index += 1
        day += timedelta(days=1)
    return items


def build_series_plan(
    *,
    account_id: str,
    title: str,
    topic: str,
    audience: str,
    episode_count: int = 6,
    tenant_id: str = "local",
) -> SeriesPlan:
    if episode_count < 2 or episode_count > 30:
        raise ValueError("episode_count must be between 2 and 30")
    angles = [
        "问题定义",
        "新手误区",
        "选择标准",
        "真实场景",
        "失败反例",
        "进阶优化",
        "预算分层",
        "对比决策",
    ]
    episodes = [
        {
            "episode": index + 1,
            "title": f"{topic}｜{angles[index % len(angles)]}",
            "audience": audience,
            "promise": f"帮助{audience}解决{angles[index % len(angles)]}问题",
            "carry_over": "结尾预告下一集，不制造虚假悬念。",
        }
        for index in range(episode_count)
    ]
    return SeriesPlan(
        tenant_id=tenant_id,
        account_id=account_id,
        title=title,
        promise=f"围绕{topic}形成连续、可收藏的决策支持系列。",
        episodes=episodes,
    )
