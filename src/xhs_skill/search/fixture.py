from __future__ import annotations

from datetime import UTC, datetime, timedelta

from xhs_skill.schemas.research import SearchQuery, SearchResult


class FixtureSearchProvider:
    name = "fixture"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        now = datetime.now(UTC)
        return [
            SearchResult(
                url=f"https://www.xiaohongshu.com/explore/fixture-{i}",
                title=title.format(q=query.query),
                snippet=snippet.format(q=query.query),
                published_at=now - timedelta(hours=hours),
                source_provider=self.name,
                source_rank=i,
                metadata=metrics,
            )
            for i, (title, snippet, hours, metrics) in enumerate(
                [
                    (
                        "{q}实测：上班族真正需要看的5个细节",
                        "场景、优缺点和适用边界都讲清楚。",
                        8,
                        {
                            "likes": 1600,
                            "saves": 2900,
                            "comments": 210,
                            "shares": 430,
                            "followers": 32000,
                        },
                    ),
                    (
                        "第一次选{q}，别只看宣传页",
                        "新手最容易忽略的参数和真实使用场景。",
                        20,
                        {
                            "likes": 2100,
                            "saves": 1800,
                            "comments": 340,
                            "shares": 180,
                            "followers": 85000,
                        },
                    ),
                    (
                        "{q}避坑清单｜哪些人不适合",
                        "不是无脑推荐，明确不适合的人群。",
                        36,
                        {
                            "likes": 900,
                            "saves": 2400,
                            "comments": 190,
                            "shares": 390,
                            "followers": 12000,
                        },
                    ),
                    (
                        "通勤场景下的{q}怎么选",
                        "按预算和使用频率给出决策建议。",
                        52,
                        {
                            "likes": 700,
                            "saves": 1250,
                            "comments": 90,
                            "shares": 150,
                            "followers": 9000,
                        },
                    ),
                    (
                        "{q}使用一周后，我保留的三个结论",
                        "包含限制条件和失败体验。",
                        72,
                        {
                            "likes": 1200,
                            "saves": 1000,
                            "comments": 260,
                            "shares": 120,
                            "followers": 20000,
                        },
                    ),
                ],
                start=1,
            )
        ][: query.limit]
