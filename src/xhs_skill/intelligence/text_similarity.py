from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

_WORD_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+")


def _tokens(text: str) -> list[str]:
    raw = _WORD_RE.findall(text.casefold())
    compact: list[str] = []
    latin_buffer: list[str] = []
    for item in raw:
        if re.fullmatch(r"[A-Za-z0-9]+", item):
            latin_buffer.append(item)
        else:
            compact.append(item)
    compact.extend(latin_buffer)
    return compact


def _shingles(text: str, width: int = 4) -> list[str]:
    tokens = _tokens(text)
    if len(tokens) < width:
        return ["".join(tokens)] if tokens else []
    return ["".join(tokens[index : index + width]) for index in range(len(tokens) - width + 1)]


def simhash64(text: str) -> int:
    features = Counter(_shingles(text, 3))
    weights = [0] * 64
    for feature, count in features.items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += count if value & (1 << bit) else -count
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def simhash_hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def minhash_signature(text: str, permutations: int = 64) -> tuple[int, ...]:
    shingles = set(_shingles(text, 4))
    if not shingles:
        return tuple([0] * permutations)
    signature: list[int] = []
    for seed in range(permutations):
        minimum = math.inf
        prefix = seed.to_bytes(4, "big")
        for shingle in shingles:
            digest = hashlib.blake2b(prefix + shingle.encode("utf-8"), digest_size=8).digest()
            minimum = min(minimum, int.from_bytes(digest, "big"))
        signature.append(int(minimum))
    return tuple(signature)


def minhash_jaccard(a: Sequence[int], b: Sequence[int]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def rare_phrase_matches(
    candidate: str,
    references: Sequence[str],
    *,
    phrase_width: int = 6,
    max_document_frequency: float = 0.25,
) -> list[str]:
    if not references:
        return []
    reference_sets = [set(_shingles(reference, phrase_width)) for reference in references]
    document_frequency: Counter[str] = Counter()
    for phrases in reference_sets:
        document_frequency.update(phrases)
    candidate_phrases = set(_shingles(candidate, phrase_width))
    threshold = max(1, math.floor(len(references) * max_document_frequency))
    matches = [
        phrase
        for phrase in candidate_phrases
        if 0 < document_frequency.get(phrase, 0) <= threshold
        and any(phrase in phrases for phrases in reference_sets)
    ]
    return sorted(matches, key=lambda item: (-len(item), item))


def ngram_jaccard(a: str, b: str, width: int = 4) -> float:
    left, right = set(_shingles(a, width)), set(_shingles(b, width))
    if not left and not right:
        return 1.0
    return len(left & right) / max(1, len(left | right))


def aggregate_similarity(candidate: str, references: Iterable[str]) -> dict[str, float | int]:
    candidate_simhash = simhash64(candidate)
    candidate_minhash = minhash_signature(candidate)
    min_hamming = 64
    max_minhash = 0.0
    max_jaccard = 0.0
    for reference in references:
        min_hamming = min(min_hamming, simhash_hamming(candidate_simhash, simhash64(reference)))
        max_minhash = max(max_minhash, minhash_jaccard(candidate_minhash, minhash_signature(reference)))
        max_jaccard = max(max_jaccard, ngram_jaccard(candidate, reference))
    return {
        "simhash_min_hamming": min_hamming if min_hamming != 64 else 64,
        "minhash_max_similarity": round(max_minhash, 6),
        "ngram_max_jaccard": round(max_jaccard, 6),
    }
