"""三板块增强：热门洞察 / 创作包 / 内容健康度 / 诊断闭环 / Wave3。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from xhs_skill.accounts.anomaly import coldstart_prior, detect_analytics_anomalies, detect_weight_anomalies
from xhs_skill.accounts.content_health import estimate_content_health
from xhs_skill.accounts.service import AccountService
from xhs_skill.core.title_mechanisms import primary_title_mechanism, tag_title_mechanisms
from xhs_skill.generation.creation_bundle import (
    build_creation_bundle,
    polish_title_cluster,
    rewrite_title_and_hook,
)
from xhs_skill.generation.entity_guard import check_entity_preservation
from xhs_skill.generation.fallback import build_titles
from xhs_skill.generation.mechanism_force import ensure_mechanism_coverage
from xhs_skill.generation.rewrite import apply_cleanup_rules, assemble_rewrite_response
from xhs_skill.generation.seo_balance import balance_tags
from xhs_skill.generation.title_proxy import score_title_proxy
from xhs_skill.research.early_signal import early_viral_signals
from xhs_skill.research.hot_insights import build_hot_insights, label_note_heat
from xhs_skill.research.trend_memory import (
    TrendMemoryStore,
    apply_trend_memory,
    compare_snapshots,
    snapshot_from_notes_trends,
)
from xhs_skill.schemas.account import AccountAnalytics, AccountWeightSnapshot
from xhs_skill.schemas.content import (
    DeliveryPackage,
    GenerateRequest,
    TitleCandidate,
    VideoScene,
    VideoScript,
)
from xhs_skill.schemas.research import HotNoteCandidate, HotNotesReport, ScoreType, TrendClass, TrendTopic


def test_title_mechanism_taxonomy_shared():
    tags = tag_title_mechanisms("降噪耳机怎么选？通勤避坑 3 个点")
    assert "决策搜索" in tags or "避坑警示" in tags
    assert primary_title_mechanism("新手第一次选预算耳机") in {
        "新手友好",
        "价格锚点",
        "决策搜索",
    }


def test_hot_insights_labels_notes():
    notes = [
        HotNoteCandidate(
            id="1",
            url="https://example.com/1",
            title="降噪耳机怎么选？通勤避坑",
            source_provider="fixture",
            hot_score=80,
            score_components={"relevance": 0.8, "freshness": 0.7},
        ),
        HotNoteCandidate(
            id="2",
            url="https://example.com/2",
            title="普通笔记",
            source_provider="fixture",
            hot_score=20,
        ),
    ]
    trends = [
        TrendTopic(topic="通勤降噪", trend_class=TrendClass.RISING, score=70, content_gap_score=0.6)
    ]
    gaps = [{"gap": "预算", "gap_score": 0.7, "recommendation": "补预算分层"}]
    insights = build_hot_insights(
        notes,
        trends,
        query="降噪耳机",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        content_gaps=gaps,
    )
    assert insights["viral_candidates"]
    assert insights["topic_heat"]
    assert insights["content_gaps"]
    assert insights["topic_heat"][0].get("stage_confidence") is not None
    assert "不是" in insights["disclaimer"]
    labeled = label_note_heat(
        notes[0],
        rank=1,
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        all_scores=[80.0, 20.0],
    )
    assert labeled["heat_band"] in {"爆款候选", "高热", "中热", "长尾"}
    assert "percentile" in labeled
    assert "决策搜索" in labeled["title_mechanisms"] or "避坑警示" in labeled["title_mechanisms"]


def test_trend_memory_dual_axis(tmp_path: Path):
    store = TrendMemoryStore(tmp_path)
    notes = [
        HotNoteCandidate(
            id="n1",
            url="https://e.com/1",
            title="怎么选",
            source_provider="t",
            hot_score=50,
        )
    ]
    trends_v1 = [
        TrendTopic(topic="降噪", trend_class=TrendClass.EMERGING, score=40, saturation=0.3)
    ]
    apply_trend_memory(
        query="耳机",
        score_type="PUBLIC_INDEX_HOT_SCORE",
        notes=notes,
        trends=trends_v1,
        store=store,
    )
    trends_v2 = [
        TrendTopic(topic="降噪", trend_class=TrendClass.RISING, score=70, saturation=0.25)
    ]
    mem = apply_trend_memory(
        query="耳机",
        score_type="PUBLIC_INDEX_HOT_SCORE",
        notes=notes,
        trends=trends_v2,
        store=store,
    )
    assert mem["comparison"]["has_baseline"] is True
    assert mem["comparison"]["rising_words"] or mem["comparison"]["dual_axis"]
    snap = snapshot_from_notes_trends(
        query="耳机", score_type="x", notes=notes, trends=trends_v2
    )
    assert snap["topics"]
    assert compare_snapshots(snap, None)["has_baseline"] is False


def test_mechanism_force_and_title_proxy():
    req = GenerateRequest(topic="收纳", candidate_count=6)
    base = [
        TitleCandidate(id="1", title="收纳日记", mechanism="场景切片"),
    ]
    covered, report = ensure_mechanism_coverage(
        base, req, preferred=["清单收藏", "避坑警示"]
    )
    assert len(covered) >= 2
    assert report.get("supplemented")
    proxy = score_title_proxy(
        "收纳怎么选？避坑清单", topic="收纳", preferred_mechanisms=["清单收藏"]
    )
    assert proxy["score"] >= 50
    assert proxy["score_type"] == "TITLE_PROXY_SCORE"


def test_seo_balance_and_early_signal():
    trends = [
        TrendTopic(
            topic="通勤",
            trend_class=TrendClass.RISING,
            score=80,
            saturation=0.2,
            content_gap_score=0.7,
        ),
        TrendTopic(
            topic="热词堆砌",
            trend_class=TrendClass.SATURATED,
            score=90,
            saturation=0.9,
            content_gap_score=0.1,
        ),
    ]
    report = HotNotesReport(
        query="耳机",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=[],
        trends=trends,
        coverage_warning="test",
    )
    bal = balance_tags(["耳机", "通勤", "热词堆砌"], report)
    assert bal["topics"][0] in {"通勤", "耳机"}
    now = datetime.now(UTC)
    notes = [
        HotNoteCandidate(
            id="e1",
            url="https://e.com/e",
            title="实测",
            source_provider="t",
            likes=200,
            saves=80,
            comments=20,
            published_at=now - timedelta(hours=6),
        )
    ]
    sig = early_viral_signals(notes)
    assert sig and sig[0]["early_signal_score"] > 0


def test_content_health_scores():
    data = AccountAnalytics(
        account_id="a1",
        views_30d=10000,
        likes_30d=500,
        saves_30d=300,
        comments_30d=80,
        shares_30d=40,
        search_views_30d=2500,
        recent_publish_count_30d=8,
        category_distribution={"数码": 0.8, "生活": 0.2},
        note_performance=[
            {"normalized_score": 70, "views": 1000},
            {"normalized_score": 65, "views": 900},
        ],
        violation_count_90d=0,
        deleted_note_count_90d=0,
    )
    health = estimate_content_health(data)
    assert health["overall_score"] is not None
    assert health["level"]
    assert health["dimensions"]
    assert health["dimension_evidence"]
    assert health["rate_intervals"]
    assert health["score_type"] == "ESTIMATED_CONTENT_HEALTH"
    assert detect_analytics_anomalies(data)["status"] in {"ok", "clean"}


def test_anomaly_and_coldstart():
    cold = coldstart_prior(AccountAnalytics(account_id="new", followers=50, published_note_count=3))
    assert cold["is_coldstart"] is True
    hist = [
        AccountWeightSnapshot(
            account_id="a", score=70, confidence="M", data_completeness=0.8
        ),
        AccountWeightSnapshot(
            account_id="a", score=68, confidence="M", data_completeness=0.8
        ),
        AccountWeightSnapshot(
            account_id="a", score=40, confidence="M", data_completeness=0.8
        ),
    ]
    anom = detect_weight_anomalies(hist)
    assert anom["status"] == "ok"
    assert anom["alerts"]


def test_account_diagnosis_combines():
    svc = AccountService()
    data = AccountAnalytics(
        account_id="a2",
        followers=1000,
        published_note_count=50,
        recent_publish_count_30d=10,
        views_30d=20000,
        likes_30d=800,
        saves_30d=400,
        comments_30d=100,
        shares_30d=50,
        follows_gained_30d=30,
        profile_visits_30d=400,
        search_views_30d=4000,
        recommendation_views_30d=16000,
        commercial_note_ratio=0.1,
        deleted_note_count_90d=0,
        violation_count_90d=0,
        category_distribution={"数码": 0.7},
        note_performance=[{"normalized_score": 72, "age_days": 5}],
    )
    diag = svc.account_diagnosis("a2", data, base_topic="降噪耳机")
    assert "weight" in diag
    assert "content_health" in diag
    assert diag["combined_actions"]
    assert diag.get("generate_payload") or diag.get("generate_actions")
    assert "weight_anomalies" in diag
    assert "coldstart" in diag
    if diag.get("generate_payload"):
        assert diag["generate_payload"].get("topic")
    weight = diag["weight"]
    if weight.get("dimensions"):
        sample_dim = next(iter(weight["dimensions"].values()))
        assert sample_dim.get("evidence") is not None


def test_build_titles_with_report_mechanisms():
    report = HotNotesReport(
        query="收纳",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=[
            HotNoteCandidate(
                id="1",
                url="https://e.com/1",
                title="收纳避坑清单怎么选",
                source_provider="t",
                hot_score=80,
            )
        ],
        hot_insights={
            "title_mechanism_stats": [
                {"mechanism": "清单收藏", "count": 3},
                {"mechanism": "避坑警示", "count": 2},
            ]
        },
        coverage_warning="t",
    )
    titles = build_titles(GenerateRequest(topic="收纳", candidate_count=8), report)
    mechs = " ".join(t.mechanism or "" for t in titles) + " ".join(t.title for t in titles)
    assert "清单" in mechs or "避坑" in mechs or "收藏" in mechs


def test_creation_bundle_and_title_hook():
    pkg = DeliveryPackage(
        task_id="t",
        trace_id="r",
        selected_title="收纳怎么选",
        body="收纳怎么选\n\n先看场景。\n\n再看预算。",
        content_hash="h",
        title_candidates=[
            TitleCandidate(id="1", title="收纳避坑", mechanism="避坑"),
            TitleCandidate(id="2", title="收纳清单", mechanism="清单"),
        ],
        cta="欢迎留言",
        pinned_comment="你最在意什么",
        topics=["收纳"],
        hashtags=["#收纳"],
        video_script=VideoScript(
            duration_seconds=15,
            hook_0_3s="收纳先别买大柜",
            scenes=[
                VideoScene(start=0, end=3, visual="钩子", narration="收纳先别买大柜", subtitle="钩子"),
                VideoScene(start=3, end=15, visual="要点", narration="先量尺寸再选款", subtitle="要点"),
            ],
            ending="你最在意哪点",
            cover_copy="收纳怎么选",
            post_caption="收纳怎么选，先看场景。",
        ),
    )
    bundle = build_creation_bundle(pkg)
    assert bundle["schema"] == "creation_bundle.v1"
    assert bundle["title_cluster"]
    assert bundle["selected_title"] == "收纳怎么选"
    assert bundle["voiceover"]
    assert bundle["voiceover"]["subtitle_cards"]
    assert "readiness" in bundle
    assert bundle["cover_media"]["mode"] == "text_only_cover_spec"
    hook = rewrite_title_and_hook(pkg.body, "")
    assert hook["opening_hook"]
    assert hook.get("mechanism")
    assert polish_title_cluster("主标题", ["副1", "副2"])


def test_entity_preservation_on_rewrite():
    original = "这款耳机续航 30 小时，宝子们谁懂啊，闭眼冲。"
    cleanup = apply_cleanup_rules(original)
    assert "30" in cleanup.revised or "【数据核对" in cleanup.revised
    resp = assemble_rewrite_response(
        original=original,
        revised=cleanup.revised,
        changes=cleanup.changes,
        compliance={"passed": True},
        ai_style={"ai_style_score": 10},
    )
    assert "entity_preservation" in resp
    check = check_entity_preservation("售价 199 元，保证根治", "售价已说明")
    assert "missing_numbers" in check
    assert check["risk_flags"]