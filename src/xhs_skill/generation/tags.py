"""从研究信号和请求上下文构建 topics / hashtags。

规则：
1. 优先从 report.mechanisms / keyword_map / trends 提取
2. 其次从 hot_notes 标题高频词提取
3. 最后用 request.topic 补齐（最多 1 个通用安全标签兜底）
4. 全程去重、规范化、限制条数
"""
from __future__ import annotations

import re
from collections import Counter

from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import HotNotesReport

# 通用安全兜底标签，仅在提取结果不足时使用
_FALLBACK_HASHTAGS = ["好物推荐", "生活记录", "真实测评"]

_MAX_TOPICS = 6
_MAX_HASHTAGS = 8

_CN_STOP = {"的", "了", "是", "在", "和", "有", "不", "人", "都", "一", "一个", "上", "也", "这", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己"}

_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")


def _extract_mechanism_tags(report: HotNotesReport) -> list[str]:
    """从 mechanisms 字段提取受众/问题/角度关键词。"""
    tags: list[str] = []
    for m in report.mechanisms[:3]:
        if m.audience and m.audience != "未明确":
            tags.append(m.audience)
        if m.user_problem:
            tags.append(m.user_problem[:12])
        if m.topic_angle:
            tags.append(m.topic_angle)
    return tags


def _extract_trend_tags(report: HotNotesReport) -> list[str]:
    """从 trends 提取主题词。"""
    return [t.topic for t in report.trends[:5] if t.topic]


def _extract_note_title_tags(report: HotNotesReport) -> list[str]:
    """从 hot_notes 标题中提取高频词。"""
    counter: Counter[str] = Counter()
    for note in report.notes[:20]:
        for word in _WORD_RE.findall(note.title):
            if word not in _CN_STOP:
                counter[word] += 1
    return [w for w, c in counter.most_common(10) if c >= 2]


def _extract_keyword_tags(request: GenerateRequest) -> list[str]:
    """从 request 自带关键词中提取。"""
    tags: list[str] = []
    if request.product.get("name"):
        tags.append(str(request.product["name"]))
    for kw in request.constraints[:3]:
        tags.append(kw)
    return tags


def _normalize_tag(raw: str) -> str:
    """去掉 # 前缀、首尾空白。"""
    return raw.strip().lstrip("#").strip()


def _dedupe_preserve_order(items: list[str], seen: set[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        key = _normalize_tag(item).lower()
        if key and key not in seen:
            seen.add(key)
            result.append(_normalize_tag(item))
    return result


def _extract_rising_trend_tags(report: HotNotesReport) -> list[str]:
    """优先 RISING/EMERGING 等上升类趋势词，再回落到普通 trends。"""
    rising: list[str] = []
    other: list[str] = []
    for t in report.trends[:8]:
        if not t.topic:
            continue
        stage = str(getattr(t, "trend_class", None) or "").upper()
        if any(key in stage for key in ("RISING", "EMERGING", "GROWING", "ACCEL", "SURGE")):
            rising.append(t.topic)
        else:
            other.append(t.topic)
    return rising + other


def append_hashtags_to_body(body: str, hashtags: list[str]) -> str:
    """正文末尾补全缺失的 #tag（已存在则不重复追加）。"""
    text = (body or "").rstrip()
    missing = [tag for tag in hashtags if tag and tag not in text]
    if not missing:
        return text + ("\n" if text else "")
    return text + "\n\n" + " ".join(missing[:_MAX_HASHTAGS]) + "\n"


def build_topics_and_hashtags(
    request: GenerateRequest,
    report: HotNotesReport | None = None,
) -> tuple[list[str], list[str]]:
    """返回 (topics, hashtags)。

    topics: 不带 # 前缀，用于创作者中心话题字段
    hashtags: 带 # 前缀，用于正文末尾
    """
    seen: set[str] = set()
    raw_topics: list[str] = []

    # 1. 研究信号（趋势优先于机制长句）
    if report:
        raw_topics.extend(_extract_rising_trend_tags(report))
        raw_topics.extend(_extract_note_title_tags(report))
        # 机制字段常过长，只取短 topic_angle
        for m in report.mechanisms[:3]:
            if m.topic_angle and len(m.topic_angle) <= 12:
                raw_topics.append(m.topic_angle)
        raw_topics.extend(_extract_mechanism_tags(report))

    # 2. 请求关键词
    raw_topics.extend(_extract_keyword_tags(request))

    # 3. 主题词
    raw_topics.insert(0, request.topic)

    topics = _dedupe_preserve_order(raw_topics, seen)
    # 过滤过长「伪标签」
    topics = [t for t in topics if 1 < len(t) <= 16][:_MAX_TOPICS]

    # 4. 兜底：至少 2 个话题，但只补弱通用标签（最多 2 个）
    if len(topics) < 2:
        for tag in _FALLBACK_HASHTAGS:
            if len(topics) >= 2:
                break
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                topics.append(tag)

    topics = topics[:_MAX_TOPICS]
    hashtags = [f"#{t}" for t in topics[:_MAX_HASHTAGS]]

    return topics, hashtags