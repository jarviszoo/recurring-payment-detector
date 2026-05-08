"""
Semantic similarity matcher using TF-IDF on character n-grams.

Why character n-grams instead of word vectors:
  - Robust to typos (NETFLX, NETFLIIX share most 3-grams with NETFLIX)
  - No model download required (sklearn only)
  - Cheap to rebuild as the registry grows

Index is rebuilt lazily when the registry has changed.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from models import CanonicalService

# Cosine-similarity threshold (0-1) for accepting a match
HIGH_CONFIDENCE = 0.75
MEDIUM_CONFIDENCE = 0.55


class EmbeddingIndex:
    def __init__(self):
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._row_to_service: list[CanonicalService] = []
        self._signature: tuple = ()

    # ------------------------------------------------------------------

    def build(self, services: list[CanonicalService]) -> None:
        """Build a TF-IDF index over canonical names + aliases."""
        sig = self._compute_signature(services)
        if sig == self._signature and self._vectorizer is not None:
            return  # nothing changed

        corpus: list[str] = []
        row_to_service: list[CanonicalService] = []
        for s in services:
            for text in [s.canonical_name, *s.aliases]:
                cleaned = text.lower().strip()
                if cleaned:
                    corpus.append(cleaned)
                    row_to_service.append(s)

        if not corpus:
            self._vectorizer = None
            self._matrix = None
            self._row_to_service = []
            self._signature = sig
            return

        self._vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            min_df=1,
        )
        self._matrix = self._vectorizer.fit_transform(corpus)
        self._row_to_service = row_to_service
        self._signature = sig

    # ------------------------------------------------------------------

    def best_match(self, query: str) -> tuple[CanonicalService, float] | None:
        """Return (service, similarity 0-1) for the best matching row."""
        if self._vectorizer is None or self._matrix is None:
            return None
        q = query.lower().strip()
        if not q:
            return None

        q_vec = self._vectorizer.transform([q])
        sims = cosine_similarity(q_vec, self._matrix).ravel()
        best_idx = int(np.argmax(sims))
        return self._row_to_service[best_idx], float(sims[best_idx])

    def top_n(self, query: str, n: int = 3) -> list[tuple[CanonicalService, float]]:
        if self._vectorizer is None or self._matrix is None:
            return []
        q = query.lower().strip()
        if not q:
            return []
        q_vec = self._vectorizer.transform([q])
        sims = cosine_similarity(q_vec, self._matrix).ravel()
        order = np.argsort(-sims)
        seen_ids: set[str] = set()
        out: list[tuple[CanonicalService, float]] = []
        for i in order:
            svc = self._row_to_service[int(i)]
            if svc.service_id in seen_ids:
                continue
            seen_ids.add(svc.service_id)
            out.append((svc, float(sims[int(i)])))
            if len(out) >= n:
                break
        return out

    # ------------------------------------------------------------------

    @staticmethod
    def _compute_signature(services: list[CanonicalService]) -> tuple:
        return tuple(sorted(
            (s.service_id, s.canonical_name, tuple(sorted(s.aliases)))
            for s in services
        ))


# Module-level singleton
_index = EmbeddingIndex()


def get_index() -> EmbeddingIndex:
    return _index
