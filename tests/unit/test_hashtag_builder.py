"""generation/tags.py 单测：验证 topics/hashtags 从研究信号生成，不再写死三件套。"""
import pytest

from xhs_skill.generation.tags import build_topics_and_hashtags
from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.schemas.research import (
    ContentMechanism,
    HotNoteCandidate,
    HotNotesReport,
    ScoreType,
    TrendClass,
    TrendTopic,
)


def _make_request(topic: str = "防晒", **kwargs) -> GenerateRequest:
    return GenerateRequest(topic=topic, **kwargs)


def _make_report(
    *,
    mechanisms: list[ContentMechanism] | None = None,
    trends: list[TrendTopic] | None = None,
    notes: list[HotNoteCandidate] | None = None,
) -> HotNotesReport:
    return HotNotesReport(
        query="test",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=notes or [],
        trends=trends or [],
        mechanisms=mechanisms or [],
        coverage_warning="test fixture",
    )


class TestBuildTopicsAndHashtags:
    def test_no_report_uses_topic_and_fallback(self):
        req = _make_request("通勤防晒")
        topics, hashtags = build_topics_and_hashtags(req, report=None)
        assert topics[0] == "通勤防晒"
        assert all(t for t in topics), "topics 不应为空"
        assert all(h.startswith("#") for h in hashtags)
        assert len(topics) <= 6
        assert len(hashtags) <= 8

    def test_with_mechanisms_extracts_audience_and_problem(self):
        report = _make_report(
            mechanisms=[
                ContentMechanism(
                    audience="上班族",
                    user_problem="不知道怎么选",
                    topic_angle="避坑指南",
                ),
            ]
        )
        req = _make_request("防晒")
        topics, hashtags = build_topics_and_hashtags(req, report)
        assert "上班族" in topics
        assert "避坑指南" in topics
        assert "#上班族" in hashtags

    def test_with_trends_extracts_topic_words(self):
        report = _make_report(
            trends=[
                TrendTopic(topic="通勤防晒", trend_class=TrendClass.RISING, score=0.9),
                TrendTopic(topic="敏感肌", trend_class=TrendClass.STABLE, score=0.7),
            ]
        )
        req = _make_request("防晒")
        topics, _ = build_topics_and_hashtags(req, report)
        assert "通勤防晒" in topics
        assert "敏感肌" in topics

    def test_deduplicates_similar_tags(self):
        report = _make_report(
            mechanisms=[ContentMechanism(audience="防晒")],
        )
        req = _make_request("防晒")
        topics, _ = build_topics_and_hashtags(req, report)
        assert topics.count("防晒") == 1

    def test_topic_always_first(self):
        req = _make_request("口红")
        report = _make_report(
            mechanisms=[ContentMechanism(audience="学生党")],
        )
        topics, _ = build_topics_and_hashtags(req, report)
        assert topics[0] == "口红"

    def test_with_product_name(self):
        req = _make_request("防晒霜", product={"name": "安耐晒小金瓶"})
        topics, _ = build_topics_and_hashtags(req, None)
        assert "安耐晒小金瓶" in topics

    def test_max_limits_respected(self):
        report = _make_report(
            mechanisms=[ContentMechanism(audience=f"受众{i}") for i in range(10)],
            trends=[TrendTopic(topic=f"趋势{i}", trend_class=TrendClass.RISING, score=0.5) for i in range(10)],
        )
        req = _make_request("测试")
        topics, hashtags = build_topics_and_hashtags(req, report)
        assert len(topics) <= 6
        assert len(hashtags) <= 8

    def test_hashtags_match_topics_prefix(self):
        req = _make_request("咖啡")
        topics, hashtags = build_topics_and_hashtags(req, None)
        for t, h in zip(topics, hashtags):
            assert h == f"#{t}"

    def test_fallback_tags_when_topic_is_stop_word_only(self):
        """极端情况：topic 为空白或停用词时兜底标签仍生效。"""
        req = GenerateRequest(topic="的")
        topics, hashtags = build_topics_and_hashtags(req, None)
        assert len(topics) >= 2
        assert all(h.startswith("#") for h in hashtags)

    def test_constraints_extracted(self):
        req = _make_request("面霜", constraints=["油皮", "平价"])
        topics, _ = build_topics_and_hashtags(req, None)
        assert "油皮" in topics
        assert "平价" in topics