from __future__ import annotations

from difflib import SequenceMatcher

from xhs_skill.intelligence.embeddings import cosine_similarity
from xhs_skill.schemas.content import TitleCandidate


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def mmr_rerank(
    candidates: list[TitleCandidate],
    *,
    relevance: dict[str, float],
    limit: int = 8,
    lambda_: float = 0.72,
    embeddings: dict[str, list[float]] | None = None,
) -> list[TitleCandidate]:
    if not 0 <= lambda_ <= 1:
        raise ValueError("lambda_ must be between 0 and 1")
    remaining = list(candidates)
    selected: list[TitleCandidate] = []
    while remaining and len(selected) < limit:
        best = None
        best_score = float("-inf")
        for candidate in remaining:
            if embeddings and candidate.id in embeddings:
                similarity = max(
                    (
                        cosine_similarity(embeddings[candidate.id], embeddings[item.id])
                        for item in selected
                        if item.id in embeddings
                    ),
                    default=0.0,
                )
            else:
                similarity = max(
                    (_similarity(candidate.title, item.title) for item in selected), default=0.0
                )
            score = lambda_ * relevance.get(candidate.id, 0.0) - (1 - lambda_) * similarity
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return selected
