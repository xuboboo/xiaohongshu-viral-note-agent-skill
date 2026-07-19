from __future__ import annotations

from xhs_skill.ranking.features import score_title, title_features
from xhs_skill.schemas.content import TitleCandidate


def rank_titles(
    candidates: list[TitleCandidate], keyword: str
) -> tuple[list[TitleCandidate], dict[str, float]]:
    relevance: dict[str, float] = {}
    for candidate in candidates:
        candidate.scores = title_features(candidate.title, keyword, candidate.mechanism)
        relevance[candidate.id] = round(score_title(candidate), 6)
    return sorted(candidates, key=lambda item: relevance[item.id], reverse=True), relevance
