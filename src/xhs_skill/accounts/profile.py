from __future__ import annotations

from collections import defaultdict

from xhs_skill.schemas.account import AccountAnalytics, AccountProfile
from xhs_skill.schemas.content import GenerateRequest


def build_account_profile(
    analytics: AccountAnalytics,
    *,
    tenant_id: str = "local",
) -> AccountProfile:
    formats: dict[str, float] = defaultdict(float)
    hooks: dict[str, float] = defaultdict(float)
    publish_days: dict[int, float] = defaultdict(float)
    publish_hours: dict[int, float] = defaultdict(float)
    audiences: dict[str, float] = defaultdict(float)
    for note in analytics.note_performance:
        weight = max(0.1, float(note.get("normalized_score", 50)) / 100)
        if note.get("format"):
            formats[str(note["format"])] += weight
        if note.get("hook"):
            hooks[str(note["hook"])] += weight
        if note.get("audience"):
            audiences[str(note["audience"])] += weight
        if note.get("published_at"):
            try:
                from datetime import datetime

                moment = datetime.fromisoformat(str(note["published_at"]).replace("Z", "+00:00"))
                publish_days[moment.weekday()] += weight
                publish_hours[moment.hour] += weight
            except ValueError:
                pass
    pillars = [
        name
        for name, _ in sorted(
            analytics.category_distribution.items(), key=lambda item: item[1], reverse=True
        )[:5]
    ]
    sample_size = len(analytics.note_performance)
    return AccountProfile(
        account_id=analytics.account_id,
        tenant_id=tenant_id,
        primary_audiences=[item for item, _ in sorted(audiences.items(), key=lambda pair: pair[1], reverse=True)[:3]],
        content_pillars=pillars,
        preferred_formats=[item for item, _ in sorted(formats.items(), key=lambda pair: pair[1], reverse=True)[:3]],
        winning_hooks=[item for item, _ in sorted(hooks.items(), key=lambda pair: pair[1], reverse=True)[:5]],
        avoid_patterns=[
            str(note.get("hook"))
            for note in analytics.note_performance
            if float(note.get("normalized_score", 50)) < 30 and note.get("hook")
        ][:5],
        optimal_publish_days=[item for item, _ in sorted(publish_days.items(), key=lambda pair: pair[1], reverse=True)[:3]],
        optimal_publish_hours=[item for item, _ in sorted(publish_hours.items(), key=lambda pair: pair[1], reverse=True)[:3]],
        confidence=min(1.0, sample_size / 30),
    )


def adapt_request_to_profile(request: GenerateRequest, profile: AccountProfile) -> GenerateRequest:
    updates: dict = {}
    if not request.target_audience and profile.primary_audiences:
        updates["target_audience"] = profile.primary_audiences[0]
    voice = dict(request.brand_voice)
    voice.setdefault("tone", profile.tone)
    voice["content_pillars"] = profile.content_pillars
    voice["winning_hooks"] = profile.winning_hooks
    voice["avoid_patterns"] = profile.avoid_patterns
    updates["brand_voice"] = voice
    constraints = list(request.constraints)
    if profile.content_pillars:
        constraints.append("优先贴合账号内容支柱：" + "、".join(profile.content_pillars[:3]))
    if profile.avoid_patterns:
        constraints.append("避免复用低表现开头：" + "、".join(profile.avoid_patterns[:3]))
    updates["constraints"] = constraints
    return request.model_copy(update=updates)
