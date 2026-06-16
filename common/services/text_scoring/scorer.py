from .embeddings import semantic_similarity
from .lexical import bm25_similarity


def score_text(
    answer: str,
    reference: str,
    *,
    language: str = "en",
    bm25_weight: float = 0.5,
    semantic_weight: float = 0.5,
) -> float:
    """0.0-1.0 correctness fraction for a free-text answer vs a reference answer.

    Combines normalized BM25 lexical similarity and embedding cosine
    similarity. Weights need not sum to 1; they are normalized by their sum.
    """
    if not answer or not answer.strip() or not reference or not reference.strip():
        return 0.0

    total_weight = bm25_weight + semantic_weight
    if total_weight <= 0:
        return 0.0

    lexical = bm25_similarity(answer, reference, language=language)
    semantic = semantic_similarity(answer, reference, language=language)
    combined = (bm25_weight * lexical + semantic_weight * semantic) / total_weight
    return min(1.0, max(0.0, combined))
