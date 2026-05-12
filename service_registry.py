"""
Canonical service registry — the structured, normalized database that the
entity-resolution pipeline builds and grows over time.

Backed by services.json on disk so the registry persists across runs.
Cold-start: registry can be empty; it grows as transactions are processed.
"""

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from models import CanonicalService

REGISTRY_FILE = Path(__file__).parent / "services.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def all_services() -> list[CanonicalService]:
    if not REGISTRY_FILE.exists():
        return []
    raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    return [_deserialize(r) for r in raw]


def get(service_id: str) -> CanonicalService | None:
    for s in all_services():
        if s.service_id == service_id:
            return s
    return None


def find_by_canonical(name: str) -> CanonicalService | None:
    """Exact (case-insensitive) match on canonical_name."""
    target = name.lower()
    for s in all_services():
        if s.canonical_name.lower() == target:
            return s
    return None


def find_by_alias(alias: str) -> CanonicalService | None:
    """Exact match on any stored alias (cleaned, case-insensitive)."""
    from merchant_normalizer import clean
    target = clean(alias)
    if not target:
        return None
    for s in all_services():
        for a in s.aliases:
            if clean(a) == target:
                return s
    return None


def register(
    canonical_name: str,
    category: str,
    aliases: list[str] | None = None,
    source: str = "auto",
    confidence: float = 0.5,
) -> CanonicalService:
    """Add a new canonical service to the registry."""
    services = all_services()
    service = CanonicalService(
        service_id=str(uuid.uuid4())[:8],
        canonical_name=canonical_name,
        category=category,
        aliases=list({a for a in (aliases or [canonical_name])}),
        first_seen=date.today(),
        last_seen=date.today(),
        transaction_count=0,
        confidence=confidence,
        source=source,
    )
    services.append(service)
    _save(services)
    return service


def add_alias(service_id: str, alias: str) -> bool:
    """Attach a new alias (raw cleaned form) to an existing service."""
    services = all_services()
    alias_clean = alias.strip()
    for s in services:
        if s.service_id == service_id:
            if alias_clean.lower() not in {a.lower() for a in s.aliases}:
                s.aliases.append(alias_clean)
                _save(services)
            return True
    return False


def bump_seen(service_id: str, txn_date: date) -> None:
    """Update last_seen and transaction_count after a successful match."""
    services = all_services()
    for s in services:
        if s.service_id == service_id:
            s.transaction_count += 1
            if s.first_seen is None or txn_date < s.first_seen:
                s.first_seen = txn_date
            if s.last_seen is None or txn_date > s.last_seen:
                s.last_seen = txn_date
            break
    _save(services)


def adjust_confidence(service_id: str, delta: float) -> None:
    """Shift confidence by delta (clamped to [0, 1])."""
    services = all_services()
    for s in services:
        if s.service_id == service_id:
            s.confidence = max(0.0, min(1.0, s.confidence + delta))
            break
    _save(services)


def merge(keep_id: str, drop_id: str) -> bool:
    """Merge two services (e.g., user confirms duplicates) into the keeper."""
    services = all_services()
    keep = next((s for s in services if s.service_id == keep_id), None)
    drop = next((s for s in services if s.service_id == drop_id), None)
    if keep is None or drop is None:
        return False
    for a in drop.aliases:
        if a.lower() not in {x.lower() for x in keep.aliases}:
            keep.aliases.append(a)
    keep.transaction_count += drop.transaction_count
    if drop.first_seen and (keep.first_seen is None or drop.first_seen < keep.first_seen):
        keep.first_seen = drop.first_seen
    if drop.last_seen and (keep.last_seen is None or drop.last_seen > keep.last_seen):
        keep.last_seen = drop.last_seen
    services = [s for s in services if s.service_id != drop_id]
    _save(services)
    return True


def clear() -> None:
    """Wipe the registry (useful for tests / cold-start demos)."""
    if REGISTRY_FILE.exists():
        REGISTRY_FILE.unlink()


def bootstrap_seed(seed: list[tuple[str, str, list[str]]]) -> None:
    """
    Seed the registry with a small set of well-known services.
    seed: list of (canonical_name, category, [aliases])
    Useful for warm-starting before processing the first batch of transactions.
    """
    for canonical, category, aliases in seed:
        if find_by_canonical(canonical) is None:
            register(canonical, category, aliases, source="manual", confidence=0.95)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save(services: list[CanonicalService]) -> None:
    payload = [_serialize(s) for s in services]
    REGISTRY_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _serialize(s: CanonicalService) -> dict:
    return {
        "service_id": s.service_id,
        "canonical_name": s.canonical_name,
        "category": s.category,
        "aliases": s.aliases,
        "first_seen": str(s.first_seen) if s.first_seen else None,
        "last_seen":  str(s.last_seen)  if s.last_seen  else None,
        "transaction_count": s.transaction_count,
        "confidence": s.confidence,
        "source": s.source,
    }


def _deserialize(d: dict) -> CanonicalService:
    return CanonicalService(
        service_id=d["service_id"],
        canonical_name=d["canonical_name"],
        category=d["category"],
        aliases=d.get("aliases", []),
        first_seen=date.fromisoformat(d["first_seen"]) if d.get("first_seen") else None,
        last_seen=date.fromisoformat(d["last_seen"])   if d.get("last_seen")  else None,
        transaction_count=d.get("transaction_count", 0),
        confidence=d.get("confidence", 0.5),
        source=d.get("source", "auto"),
    )
