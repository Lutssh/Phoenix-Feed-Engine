"""
ml_core/bm25_filter.py
──────────────────────
BM25 pre-filter for text candidates.

Purpose
-------
Before paying the cost of a neural embedding call (~14ms each), BM25 quickly
scores candidate texts against a query using pure keyword statistics.
This narrows 1,000 candidates down to the top-50 most relevant ones in <1ms,
cutting neural embedding calls by up to 95%.

Usage
-----
    from smart_ingestion.ml_core.bm25_filter import BM25Filter

    # Build once per request from the candidate pool
    f = BM25Filter(corpus=["Post about cats", "Post about food", ...])

    # Fast narrow — returns top-K texts
    shortlist = f.top_k(query="cat videos", k=50)

    # Or score a single candidate (returns float in [0, ∞))
    score = f.score(query="cat videos", candidate="Post about cats")
"""
from __future__ import annotations

import re
from typing import List, Tuple

from rank_bm25 import BM25Okapi


# ── Tokenizer ─────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    """Lowercase + alphanumeric tokens only. Fast and dependency-free."""
    return _TOKEN_RE.findall(text.lower())


# ── BM25Filter ────────────────────────────────────────────────────────────────

class BM25Filter:
    """
    Wraps rank_bm25.BM25Okapi with a clean API suited for feed pre-filtering.

    Parameters
    ----------
    corpus : list[str]
        The pool of candidate texts for this request.
    """

    def __init__(self, corpus: List[str]) -> None:
        self._corpus = corpus
        self._tokenized = [_tokenize(doc) for doc in corpus]
        self._bm25 = BM25Okapi(self._tokenized)

    # ── Public API ────────────────────────────────────────────────────────────

    def scores(self, query: str) -> List[float]:
        """Return a BM25 score for every document in the corpus."""
        return self._bm25.get_scores(_tokenize(query)).tolist()

    def top_k(self, query: str, k: int = 50) -> List[str]:
        """
        Return the top-k most relevant texts for *query*.
        Runs in O(N) where N = len(corpus). Typical: <1ms for N=10,000.
        """
        raw_scores = self._bm25.get_scores(_tokenize(query))
        # argpartition is O(N) — much faster than full sort for large N
        import numpy as np
        k = min(k, len(self._corpus))
        top_idx = np.argpartition(raw_scores, -k)[-k:]
        top_idx = top_idx[np.argsort(raw_scores[top_idx])[::-1]]
        return [self._corpus[i] for i in top_idx]

    def top_k_with_scores(self, query: str, k: int = 50) -> List[Tuple[str, float]]:
        """Same as top_k but also returns the BM25 scores."""
        import numpy as np
        raw_scores = self._bm25.get_scores(_tokenize(query))
        k = min(k, len(self._corpus))
        top_idx = np.argpartition(raw_scores, -k)[-k:]
        top_idx = top_idx[np.argsort(raw_scores[top_idx])[::-1]]
        return [(self._corpus[i], float(raw_scores[i])) for i in top_idx]

    def score(self, query: str, candidate: str) -> float:
        """Score a single candidate against the query. O(vocab)."""
        try:
            idx = self._corpus.index(candidate)
            return float(self._bm25.get_scores(_tokenize(query))[idx])
        except ValueError:
            # Candidate not in corpus — score it stand-alone
            tmp = BM25Okapi([_tokenize(candidate)])
            return float(tmp.get_scores(_tokenize(query))[0])

    def is_relevant(self, query: str, candidate: str, threshold: float = 0.3) -> bool:
        """Return True if the candidate clears the BM25 threshold."""
        return self.score(query, candidate) >= threshold

    def __len__(self) -> int:
        return len(self._corpus)
