from xhs_skill.accounts.weight_estimator import estimate_account_weight
from xhs_skill.schemas.account import AccountAnalytics


def test_insufficient_data_has_no_fake_score():
    report = estimate_account_weight(AccountAnalytics(account_id="a"))
    assert report.status == "INSUFFICIENT_DATA"
    assert report.overall_score is None
    assert "不是小红书官方" in report.disclaimer


def test_complete_account_has_explainable_score():
    report = estimate_account_weight(
        AccountAnalytics(
            account_id="a",
            followers=10000,
            published_note_count=50,
            recent_publish_count_30d=12,
            views_30d=100000,
            likes_30d=5000,
            saves_30d=3500,
            comments_30d=700,
            shares_30d=900,
            follows_gained_30d=400,
            profile_visits_30d=5000,
            search_views_30d=25000,
            recommendation_views_30d=75000,
            commercial_note_ratio=0.2,
            deleted_note_count_90d=0,
            violation_count_90d=0,
            category_distribution={"护肤": 0.8},
        )
    )
    assert report.overall_score is not None
    assert 0 <= report.overall_score <= 100
    assert report.dimensions
