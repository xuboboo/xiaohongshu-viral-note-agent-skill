from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from pathlib import Path

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.intelligence.embeddings import (
    EmbeddingProvider,
    cosine_similarity,
    get_embedding_provider,
)
from xhs_skill.intelligence.text_similarity import (
    aggregate_similarity,
    rare_phrase_matches,
)
from xhs_skill.intelligence.vision import compare_images


def normalize(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def originality_report(text: str, references: list[str], settings: Settings | None = None) -> dict:
    """Fast deterministic originality gate used by synchronous callers."""
    settings = settings or get_settings()
    filtered = [reference for reference in references if reference]
    scores = [
        SequenceMatcher(None, normalize(text), normalize(reference)).ratio()
        for reference in filtered
    ]
    maximum = max(scores, default=0.0)
    fingerprints = aggregate_similarity(text, filtered)
    rare_matches = rare_phrase_matches(text, filtered)
    blocked = (
        maximum >= 0.85
        or int(fingerprints["simhash_min_hamming"]) <= settings.simhash_hamming_block
        or float(fingerprints["minhash_max_similarity"]) >= settings.minhash_similarity_block
        or len(rare_matches) >= settings.rare_phrase_match_block > 0
    )
    return {
        "literal_similarity": round(maximum, 4),
        "semantic_similarity": None,
        "semantic_provider": None,
        "structural_similarity": fingerprints["ngram_max_jaccard"],
        "simhash_min_hamming": fingerprints["simhash_min_hamming"],
        "minhash_similarity": fingerprints["minhash_max_similarity"],
        "rare_phrase_matches": rare_matches[:20],
        "image_matches": [],
        "publication_allowed": not blocked,
        "matched_reference_count": sum(score >= 0.7 for score in scores),
        "warnings": ["Semantic embeddings were not evaluated by the synchronous fast gate."],
    }


async def originality_report_async(
    text: str,
    references: Sequence[str],
    *,
    candidate_images: Sequence[str | Path] = (),
    reference_images: Sequence[str | Path] = (),
    candidate_image_labels: Sequence[str] | None = None,
    reference_image_labels: Sequence[str] | None = None,
    embedder: EmbeddingProvider | None = None,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    report = originality_report(text, list(references), settings)
    filtered = [reference for reference in references if reference]
    if filtered:
        provider = embedder or get_embedding_provider(settings)
        vectors = await provider.embed([text, *filtered])
        similarities = [cosine_similarity(vectors[0], vector) for vector in vectors[1:]]
        semantic_max = max(similarities, default=0.0)
        report["semantic_similarity"] = round(semantic_max, 6)
        report["semantic_provider"] = provider.name
        if semantic_max >= settings.semantic_similarity_block:
            report["publication_allowed"] = False
    if candidate_image_labels is not None and len(candidate_image_labels) != len(candidate_images):
        raise ValueError("candidate_image_labels must match candidate_images")
    if reference_image_labels is not None and len(reference_image_labels) != len(reference_images):
        raise ValueError("reference_image_labels must match reference_images")
    image_matches: list[dict] = []
    for candidate_index, candidate in enumerate(candidate_images):
        for reference_index, reference in enumerate(reference_images):
            match = compare_images(
                candidate,
                reference,
                phash_block_distance=settings.image_phash_distance_block,
                enable_ocr=settings.ocr_enabled,
            )
            payload = match.model_dump(mode="json")
            if candidate_image_labels is not None:
                payload["candidate"] = candidate_image_labels[candidate_index]
            if reference_image_labels is not None:
                payload["reference"] = reference_image_labels[reference_index]
            image_matches.append(payload)
            if match.blocked:
                report["publication_allowed"] = False
    report["image_matches"] = image_matches
    report["warnings"] = [
        warning
        for warning in report.get("warnings", [])
        if "Semantic embeddings" not in warning
    ]
    return report
