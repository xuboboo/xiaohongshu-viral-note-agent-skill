"""generation/covers.py 单测：从 mechanism/title 派生 2–3 个封面方案。"""
from xhs_skill.generation.covers import build_cover_options
from xhs_skill.schemas.content import GenerateRequest, TitleCandidate
from xhs_skill.schemas.research import ContentMechanism, HotNotesReport, ScoreType


def _request(topic: str = "空气炸锅") -> GenerateRequest:
    return GenerateRequest(topic=topic, target_audience="上班族")


def _report(*mechanisms: ContentMechanism) -> HotNotesReport:
    return HotNotesReport(
        query="test",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=[],
        mechanisms=list(mechanisms),
        coverage_warning="test fixture",
    )


class TestBuildCoverOptions:
    def test_returns_two_to_three_options(self):
        options = build_cover_options(_request())
        assert 2 <= len(options) <= 3

    def test_uses_title_mechanisms(self):
        titles = [
            TitleCandidate(id="t1", title="空气炸锅怎么选不踩坑", mechanism="避坑清单"),
            TitleCandidate(id="t2", title="上班族空气炸锅真实场景", mechanism="场景决策"),
        ]
        options = build_cover_options(_request(), titles=titles)
        headlines = {o.headline for o in options}
        assert "空气炸锅怎么选不踩坑" in headlines
        assert len(options) >= 2

    def test_uses_report_mechanisms(self):
        report = _report(
            ContentMechanism(
                topic_angle="控油省时",
                audience="上班族",
                user_problem="不会挑参数",
            )
        )
        options = build_cover_options(_request(), report=report)
        assert any("控油省时" in o.headline or "上班族" in o.subheadline for o in options)
        assert 2 <= len(options) <= 3

    def test_dedupes_and_caps_at_three(self):
        titles = [
            TitleCandidate(id=f"t{i}", title="同一标题", mechanism=f"m{i}")
            for i in range(5)
        ]
        options = build_cover_options(_request(), titles=titles, selected_title="同一标题")
        assert len(options) <= 3
        assert len({o.headline for o in options}) == len(options)