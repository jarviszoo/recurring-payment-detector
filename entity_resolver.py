"""
Entity resolution orchestrator.

Takes a raw merchant string and produces a ResolutionResult by walking through
progressively more expensive matchers.  Each stage has a confidence threshold:

    Stage 0  Clean text (regex strip)               always
    Stage 1  Exact alias lookup in registry         confidence 1.00
    Stage 2  Fuzzy match (rapidfuzz)                confidence 0.80–0.95
    Stage 3  Embedding match (TF-IDF char n-grams)  confidence 0.60–0.85
    Stage 4  Auto-create new low-confidence service confidence 0.30
    Stage 5  (offline batch) cluster unresolved → propose merges

Stages 1–3 also write back: a successful match attaches the cleaned form as a
new alias on the matched service and bumps last_seen.  This is how the
registry learns variant spellings without manual labels.
"""

from datetime import date
from models import ResolutionResult, CanonicalService
from merchant_normalizer import clean
from category_classifier import classify
import service_registry
import fuzzy_matcher
import embedding_matcher

# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------
FUZZY_HIGH = 92      # accept fuzzy match without further check
FUZZY_MIN = 80       # accept fuzzy match if also corroborated by embedding
EMBED_HIGH = 0.75
EMBED_MIN = 0.55

# Below this, don't auto-attach an alias to an existing service — the match
# is too weak to learn from automatically.
AUTO_ALIAS_MIN_CONFIDENCE = 0.80

# Below this, mark the resolution as low-confidence so feedback is solicited.
LOW_CONFIDENCE_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve(
    raw_merchant: str,
    txn_date: date | None = None,
    mcc: str | None = None,
    auto_create: bool = True,
) -> ResolutionResult:
    """
    Resolve a single raw merchant string to a canonical service.

    If auto_create is True (default) and no high-confidence match is found,
    a new low-confidence service is registered so downstream code always has
    a stable canonical_name to group by.
    """
    cleaned = clean(raw_merchant)
    if not cleaned:
        return ResolutionResult(
            raw=raw_merchant, cleaned="", canonical_name=None,
            service_id=None, category=None,
            method="unresolved", confidence=0.0,
        )

    services = service_registry.all_services()

    # ---- Stage 1: exact alias lookup ----
    hit = service_registry.find_by_alias(cleaned)
    if hit is None:
        # also try the canonical_name field directly
        hit = service_registry.find_by_canonical(cleaned)
    if hit is not None:
        if txn_date:
            service_registry.bump_seen(hit.service_id, txn_date)
        return _result(raw_merchant, cleaned, hit, "exact_alias", 1.0)

    # ---- Stage 2: fuzzy ----
    fuzzy_top = fuzzy_matcher.top_n(cleaned, services, n=3)
    fuzzy_best = fuzzy_top[0] if fuzzy_top else None

    # ---- Stage 3: embedding ----
    idx = embedding_matcher.get_index()
    idx.build(services)
    embed_top = idx.top_n(cleaned, n=3)
    embed_best = embed_top[0] if embed_top else None

    chosen, method, confidence, candidates = _decide(fuzzy_best, fuzzy_top, embed_best, embed_top)

    if chosen is not None:
        # Auto-learn: attach this cleaned form as an alias if confident enough
        if confidence >= AUTO_ALIAS_MIN_CONFIDENCE:
            service_registry.add_alias(chosen.service_id, cleaned)
        if txn_date:
            service_registry.bump_seen(chosen.service_id, txn_date)
        return _result(
            raw_merchant, cleaned, chosen, method, confidence, candidates
        )

    # ---- Stage 4: auto-create new service ----
    if auto_create:
        category = classify(raw_merchant, mcc=mcc)
        canonical_name = _pretty(cleaned)
        new_service = service_registry.register(
            canonical_name=canonical_name,
            category=category,
            aliases=[cleaned],
            source="auto",
            confidence=0.30,
        )
        if txn_date:
            service_registry.bump_seen(new_service.service_id, txn_date)
        return _result(raw_merchant, cleaned, new_service, "new_service", 0.30, candidates)

    # Unresolved — leave for batch clustering
    return ResolutionResult(
        raw=raw_merchant, cleaned=cleaned, canonical_name=None,
        service_id=None, category=None,
        method="unresolved", confidence=0.0,
        candidates=[(s.canonical_name, score) for s, score in candidates],
    )


def resolve_batch(
    raw_merchants: list[tuple[str, date | None, str | None]],
    auto_create: bool = True,
) -> list[ResolutionResult]:
    """Resolve many merchants. Order matters: earlier matches teach the registry."""
    return [resolve(r, d, m, auto_create) for r, d, m in raw_merchants]


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def _decide(
    fuzzy_best: tuple[CanonicalService, float] | None,
    fuzzy_top: list[tuple[CanonicalService, float]],
    embed_best: tuple[CanonicalService, float] | None,
    embed_top: list[tuple[CanonicalService, float]],
) -> tuple[CanonicalService | None, str, float, list[tuple[CanonicalService, float]]]:
    """
    Combine fuzzy + embedding signals into a single decision.

    Returns (chosen_service, method_name, confidence_0_1, candidates_list)
    where candidates_list is a flattened set of (service, score) for traceability.
    """
    candidates: list[tuple[CanonicalService, float]] = []
    if fuzzy_top:
        candidates.extend([(s, score / 100.0) for s, score in fuzzy_top])
    if embed_top:
        candidates.extend(embed_top)

    # 1) High-confidence fuzzy alone
    if fuzzy_best and fuzzy_best[1] >= FUZZY_HIGH:
        return fuzzy_best[0], "fuzzy", fuzzy_best[1] / 100.0, candidates

    # 2) High-confidence embedding alone
    if embed_best and embed_best[1] >= EMBED_HIGH:
        return embed_best[0], "embedding", embed_best[1], candidates

    # 3) Both moderate AND agree on the same service → corroborated match
    if (fuzzy_best and embed_best
            and fuzzy_best[0].service_id == embed_best[0].service_id
            and fuzzy_best[1] >= FUZZY_MIN
            and embed_best[1] >= EMBED_MIN):
        # Combine scores
        combined = (fuzzy_best[1] / 100.0) * 0.5 + embed_best[1] * 0.5
        return fuzzy_best[0], "fuzzy+embedding", combined, candidates

    return None, "unresolved", 0.0, candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(
    raw: str, cleaned: str, service: CanonicalService,
    method: str, confidence: float,
    candidates: list[tuple[CanonicalService, float]] | None = None,
) -> ResolutionResult:
    return ResolutionResult(
        raw=raw,
        cleaned=cleaned,
        canonical_name=service.canonical_name,
        service_id=service.service_id,
        category=service.category,
        method=method,
        confidence=round(confidence, 3),
        candidates=[(s.canonical_name, round(score, 3)) for s, score in (candidates or [])],
    )


def _pretty(cleaned: str) -> str:
    """Render a cleaned string as a presentable canonical name."""
    if not cleaned:
        return cleaned
    # Preserve all-caps when the brand uses an ampersand (PG&E, AT&T, H&R)
    if "&" in cleaned:
        return cleaned.upper()
    return cleaned.title()
