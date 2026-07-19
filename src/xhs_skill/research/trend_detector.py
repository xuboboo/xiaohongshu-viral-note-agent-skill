from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime

from xhs_skill.schemas.research import HotNoteCandidate, TrendClass, TrendTopic

_STOPWORDS = {"小红书", "分享", "真的", "一个", "怎么", "使用", "推荐", "实测", "笔记"}


def _words(title: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9-]{2,}", title)
        if word not in _STOPWORDS
    ]


def _robust_z(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    if mad == 0:
        return 0.0
    return 0.6745 * (values[-1] - median) / mad


def _detect_change_point(series: list[tuple[datetime, float]]) -> tuple[bool, datetime | None, float]:
    if len(series) < 4:
        return False, None, 0.0
    values = [value for _, value in series]
    best_index, best_delta = 0, 0.0
    for index in range(2, len(values) - 1):
        before = statistics.fmean(values[:index])
        after = statistics.fmean(values[index:])
        scale = statistics.pstdev(values) or 1.0
        delta = abs(after - before) / scale
        if delta > best_delta:
            best_index, best_delta = index, delta
    detected = best_delta >= 1.25
    return detected, series[best_index][0] if detected else None, best_delta


def extract_topics(notes: list[HotNoteCandidate], limit: int = 12) -> list[TrendTopic]:
    counter: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    now = datetime.now(UTC)
    for note in notes:
        words = _words(note.title)
        day = (note.published_at or note.indexed_at or now).astimezone(UTC).date().isoformat()
        for word in words:
            counter[word] += 1
            daily[day][word] += 1
            evidence.setdefault(word, []).append(note.id)
            sources[word].add(note.source_provider)
    total = max(len(notes), 1)
    sorted_days = sorted(daily)
    trends = []
    for word, count in counter.most_common(limit):
        support = count / total
        series = [
            (datetime.fromisoformat(day).replace(tzinfo=UTC), float(daily[day].get(word, 0)))
            for day in sorted_days
        ]
        values = [value for _, value in series]
        recent = statistics.fmean(values[-2:]) if values else 0.0
        previous = statistics.fmean(values[:-2]) if len(values) > 2 else 0.0
        growth = (recent - previous) / max(previous, 1.0)
        acceleration = 0.0
        if len(values) >= 3:
            acceleration = (values[-1] - values[-2]) - (values[-2] - values[-3])
        change_detected, change_at, change_strength = _detect_change_point(series)
        z_score = _robust_z(values)
        cross_source = len(sources[word]) / max(1, len({note.source_provider for note in notes}))
        saturation = min(1.0, support * 1.5 + max(0.0, 1 - len(set(evidence[word])) / max(count, 1)) * 0.25)
        gap_score = max(0.0, min(1.0, (1 - saturation) * (0.5 + max(0.0, growth) * 0.3)))
        score = min(
            100.0,
            max(
                0.0,
                40
                + support * 25
                + max(-1.0, min(growth, 2.0)) * 15
                + min(abs(z_score), 4.0) * 4
                + cross_source * 10
                + min(change_strength, 3.0) * 3
                - saturation * 10,
            ),
        )
        if z_score >= 3.5 and support < 0.2:
            trend_class = TrendClass.ANOMALOUS
        elif growth > 0.5 and change_detected:
            trend_class = TrendClass.RISING
        elif growth > 0.2 or (count >= 2 and support < 0.35):
            trend_class = TrendClass.EMERGING
        elif growth < -0.35:
            trend_class = TrendClass.DECLINING
        elif saturation >= 0.75:
            trend_class = TrendClass.SATURATED
        else:
            trend_class = TrendClass.STABLE
        trends.append(
            TrendTopic(
                topic=word,
                trend_class=trend_class,
                score=round(score, 2),
                growth_rate=round(growth, 4),
                acceleration=round(acceleration, 4),
                cross_source_support=round(cross_source, 4),
                saturation=round(saturation, 4),
                change_point_detected=change_detected,
                change_point_at=change_at,
                momentum=round(math.tanh(growth + z_score / 4), 4),
                content_gap_score=round(gap_score, 4),
                evidence_note_ids=evidence[word],
            )
        )
    return trends


def detect_content_gaps(notes: list[HotNoteCandidate], trends: list[TrendTopic], limit: int = 10) -> list[dict]:
    pain_terms = ("避坑", "失败", "不适合", "为什么", "怎么选", "对比", "预算", "新手", "敏感", "通勤")
    coverage: Counter[str] = Counter()
    for note in notes:
        combined = f"{note.title} {note.snippet or ''}"
        for term in pain_terms:
            if term in combined:
                coverage[term] += 1
    trend_by_name = {item.topic: item for item in trends}
    candidates: list[dict] = []
    for term in pain_terms:
        ratio = coverage[term] / max(1, len(notes))
        score = round(1 - min(1.0, ratio * 2), 4)
        candidates.append(
            {
                "gap": term,
                "coverage_ratio": round(ratio, 4),
                "gap_score": score,
                "recommendation": f"围绕“{term}”补充具体场景、决策标准和失败边界。",
            }
        )
    for topic, trend in trend_by_name.items():
        if trend.content_gap_score >= 0.55:
            candidates.append(
                {
                    "gap": topic,
                    "coverage_ratio": round(1 - trend.content_gap_score, 4),
                    "gap_score": trend.content_gap_score,
                    "recommendation": f"主题“{topic}”仍有供给缺口，优先覆盖长尾人群和反例。",
                }
            )
    return sorted(candidates, key=lambda item: item["gap_score"], reverse=True)[:limit]
