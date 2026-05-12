"""
Fuzzy string matcher — handles typos and variant spellings.

Strategy:
  - For each candidate (canonical_name + every alias), score against the query
    using rapidfuzz (token_set_ratio is robust to word reordering and noise).
  - Keep the best score per service_id.
  - Boost the score slightly when matching against canonical_name vs alias.
"""

from rapidfuzz import fuzz
from models import CanonicalService

# Score thresholds (0-100 scale from rapidfuzz)
HIGH_CONFIDENCE = 92
MEDIUM_CONFIDENCE = 80


def best_match(
    cleaned_query: str,
    services: list[CanonicalService],
) -> tuple[CanonicalService, float] | None:
    """
    Return the (service, score) tuple with the highest fuzzy similarity,
    or None if no service is registered.
    Score is 0-100.
    """
    if not services or not cleaned_query.strip():
        return None

    best: tuple[CanonicalService, float] | None = None
    q = cleaned_query.lower().strip()

    for s in services:
        score = _score_service(q, s)
        if best is None or score > best[1]:
            best = (s, score)

    return best


def top_n(
    cleaned_query: str,
    services: list[CanonicalService],
    n: int = 3,
) -> list[tuple[CanonicalService, float]]:
    """Return top-N matches sorted by score descending."""
    if not services or not cleaned_query.strip():
        return []
    q = cleaned_query.lower().strip()
    scored = [(s, _score_service(q, s)) for s in services]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n]


# ---------------------------------------------------------------------------

def _score_service(query: str, service: CanonicalService) -> float:
    """Best score across canonical name + all aliases (all cleaned the same way as the query)."""
    from merchant_normalizer import clean as _clean
    targets: list[tuple[str, float]] = [(_clean(service.canonical_name), 1.05)]
    for a in service.aliases:
        cleaned_alias = _clean(a)
        if cleaned_alias:
            targets.append((cleaned_alias, 1.0))

    best = 0.0
    for target, boost in targets:
        if not target:
            continue
        # token_set_ratio handles word reordering and partial matches
        score_set = fuzz.token_set_ratio(query, target)
        # ratio is stricter — penalises edit-distance differences
        score_ratio = fuzz.ratio(query, target)
        score = max(score_set, score_ratio) * boost
        if score > best:
            best = score
    return min(best, 100.0)
