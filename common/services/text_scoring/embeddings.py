import threading

from fastembed import TextEmbedding

_LANGUAGE_MODELS = {
    "en": "BAAI/bge-small-en-v1.5",
}

_model_cache: dict[str, TextEmbedding] = {}
_lock = threading.Lock()


def get_embedding_model(language: str = "en") -> TextEmbedding:
    if language not in _LANGUAGE_MODELS:
        raise ValueError(f"No embedding model configured for language '{language}'")

    model = _model_cache.get(language)
    if model is not None:
        return model

    with _lock:
        model = _model_cache.get(language)
        if model is None:
            model = TextEmbedding(model_name=_LANGUAGE_MODELS[language])
            _model_cache[language] = model
        return model


def semantic_similarity(answer: str, reference: str, *, language: str = "en") -> float:
    """0.0-1.0 cosine similarity (negative similarity clipped to 0) between embeddings."""
    if not answer.strip() or not reference.strip():
        return 0.0

    model = get_embedding_model(language)
    answer_vec, reference_vec = list(model.embed([answer, reference]))

    dot = float(answer_vec @ reference_vec)
    norm = float((answer_vec @ answer_vec) ** 0.5 * (reference_vec @ reference_vec) ** 0.5)
    if norm == 0:
        return 0.0

    return max(0.0, dot / norm)
