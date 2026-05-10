from __future__ import annotations

from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from collections import defaultdict
from pathlib import Path
import json

from models import Transaction
from merchant_normalizer import normalize
from category_classifier import classify


@dataclass
class Provider:
    provider_id: str
    canonical_name: str
    category: str
    aliases: list[str]
    transaction_count: int = 0


@dataclass
class ResolutionEvent:
    transaction_id: str
    normalized_merchant: str
    provider_id: str
    provider_name: str
    confidence: float
    decision: str  # match | possible_match | new_provider


def build_canonical_registry(
    transactions: list[Transaction],
    auto_threshold: float = 0.92,
    review_threshold: float = 0.78,
) -> tuple[list[Provider], list[ResolutionEvent]]:
    providers: list[Provider] = []
    events: list[ResolutionEvent] = []

    for txn in transactions:
        normalized = normalize(txn.merchant_raw)
        category = classify(txn.merchant_raw, mcc=txn.category_mcc)

        best, score = _best_provider_match(normalized, providers)
        if best and score >= auto_threshold:
            decision = "match"
            provider = best
        elif best and score >= review_threshold:
            decision = "possible_match"
            provider = best
        else:
            decision = "new_provider"
            provider = Provider(
                provider_id=f"prov_{len(providers)+1:05d}",
                canonical_name=normalized,
                category=category,
                aliases=[normalized],
                transaction_count=0,
            )
            providers.append(provider)
            score = 1.0

        if normalized not in provider.aliases:
            provider.aliases.append(normalized)
        provider.transaction_count += 1

        events.append(
            ResolutionEvent(
                transaction_id=txn.transaction_id,
                normalized_merchant=normalized,
                provider_id=provider.provider_id,
                provider_name=provider.canonical_name,
                confidence=round(score, 3),
                decision=decision,
            )
        )

    return providers, events


def save_registry_snapshot(
    providers: list[Provider],
    events: list[ResolutionEvent],
    output_path: str,
) -> None:
    payload = {
        "providers": [asdict(p) for p in providers],
        "resolution_events": [asdict(e) for e in events],
    }
    Path(output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _best_provider_match(name: str, providers: list[Provider]) -> tuple[Provider | None, float]:
    best = None
    best_score = 0.0
    for p in providers:
        score = max((_sim(name, a) for a in p.aliases), default=0.0)
        if score > best_score:
            best = p
            best_score = score
    return best, best_score


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()
