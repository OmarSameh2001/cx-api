import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_K1 = 1.5


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _bm25_raw_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """BM25 term-frequency-saturation score of query_tokens against a single
    doc_tokens document.

    Classic BM25 IDF (Robertson-Sparck-Jones) goes negative whenever a term
    appears in more than half the corpus, which is *always* true for a
    single-document corpus — the case here, since we only ever compare one
    answer against one reference, never a real multi-document index. With a
    1-document corpus, IDF and length-normalization both collapse to the
    same constant for every term, so they cancel out under the self-score
    normalization in `bm25_similarity` below; only the TF-saturation curve
    (controlled by k1) matters.
    """
    term_freq: dict[str, int] = {}
    for tok in doc_tokens:
        term_freq[tok] = term_freq.get(tok, 0) + 1

    score = 0.0
    for term in query_tokens:
        freq = term_freq.get(term)
        if not freq:
            continue
        score += freq * (_K1 + 1) / (freq + _K1)
    return score


def bm25_similarity(answer: str, reference: str, *, language: str = "en") -> float:
    """0.0-1.0 lexical similarity between `answer` and `reference`."""
    ref_tokens = _tokenize(reference)
    answer_tokens = _tokenize(answer)
    if not ref_tokens or not answer_tokens:
        return 0.0

    self_score = _bm25_raw_score(ref_tokens, ref_tokens)
    if self_score <= 0:
        return 0.0

    raw_score = _bm25_raw_score(answer_tokens, ref_tokens)
    return min(1.0, max(0.0, raw_score / self_score))
