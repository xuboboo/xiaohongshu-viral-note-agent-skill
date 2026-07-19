from xhs_skill.intelligence.embeddings import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    cosine_similarity,
    get_embedding_provider,
)
from xhs_skill.intelligence.text_similarity import (
    minhash_jaccard,
    minhash_signature,
    rare_phrase_matches,
    simhash64,
    simhash_hamming,
)
from xhs_skill.intelligence.vision import ImageSimilarityReport, compare_images

__all__ = [
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "cosine_similarity",
    "get_embedding_provider",
    "simhash64",
    "simhash_hamming",
    "minhash_signature",
    "minhash_jaccard",
    "rare_phrase_matches",
    "ImageSimilarityReport",
    "compare_images",
]
