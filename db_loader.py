"""
Loads providers + aliases + price tiers from the real SQLite database
(C:\\Users\\1\\recurring-payment-detector\\providers.db) into formats
the pipeline understands.

The DB uses its own category vocabulary; we map it onto the pipeline's
category set (software / streaming / utilities / etc.) so existing
category_rules apply correctly.
"""

import sqlite3
import json
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass

DEFAULT_DB = Path(r"C:\Users\1\recurring-payment-detector\providers.db")


# Mapping from DB.category -> pipeline category
CATEGORY_MAP: dict[str, str] = {
    "saas": "software",
    "streaming": "streaming",
    "ai": "software",
    "devtools": "software",
    "cloud": "cloud_storage",
    "gaming": "gaming",
    "finance": "general",
    "vpn": "software",
    "hosting": "cloud_storage",
    "news": "news",
    "fitness": "fitness",
    "education": "software",
    "creative": "software",
    "ecommerce": "mixed_commerce",
    "delivery": "delivery",
    "communication": "software",
    "audio": "music",
    "marketing": "software",
    "health": "fitness",
    "crm": "software",
    "music": "music",
}


@dataclass
class DbProvider:
    provider_id: int
    name: str
    category: str          # mapped to pipeline category
    db_category: str       # original DB category
    aliases: list[str]
    billing_cycles: list[str]
    tiers: list[dict]      # [{tier_name, price_monthly, price_annual}, ...]


def load_providers(db_path: Path = DEFAULT_DB) -> list[DbProvider]:
    """Read every provider with its aliases + price tiers."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    aliases_by_pid: dict[int, list[str]] = defaultdict(list)
    for pid, alias in cur.execute("SELECT provider_id, alias FROM transaction_aliases"):
        aliases_by_pid[pid].append(alias)

    tiers_by_pid: dict[int, list[dict]] = defaultdict(list)
    for pid, name, monthly, annual, currency, is_promo in cur.execute(
        "SELECT provider_id, tier_name, price_monthly, price_annual, currency, is_promo FROM price_tiers"
    ):
        tiers_by_pid[pid].append({
            "tier_name": name,
            "price_monthly": monthly,
            "price_annual": annual,
            "currency": currency or "USD",
            "is_promo": bool(is_promo),
        })

    out: list[DbProvider] = []
    for pid, name, db_cat, billing_raw in cur.execute(
        "SELECT id, name, category, billing_cycles FROM providers"
    ):
        try:
            cycles = json.loads(billing_raw) if billing_raw else ["monthly"]
        except Exception:
            cycles = ["monthly"]
        out.append(DbProvider(
            provider_id=pid,
            name=name,
            category=CATEGORY_MAP.get(db_cat, "general"),
            db_category=db_cat or "general",
            aliases=aliases_by_pid.get(pid, []),
            billing_cycles=cycles,
            tiers=tiers_by_pid.get(pid, []),
        ))

    conn.close()
    return out


def to_seed_tuples(providers: list[DbProvider]) -> list[tuple[str, str, list[str]]]:
    """Convert to the (canonical_name, category, aliases) tuples that
    service_registry.bootstrap_seed() expects."""
    seed: list[tuple[str, str, list[str]]] = []
    for p in providers:
        # Include canonical name as one of the aliases so cleaned forms
        # can match it directly in the registry.
        all_aliases = list({p.name, *p.aliases})
        seed.append((p.name, p.category, all_aliases))
    return seed


# ---------------------------------------------------------------------------
# Quick CLI for inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    providers = load_providers()
    print(f"Loaded {len(providers)} providers from DB.")
    print(f"  total aliases: {sum(len(p.aliases) for p in providers)}")
    print(f"  total tiers:   {sum(len(p.tiers) for p in providers)}")

    by_cat: dict[str, int] = defaultdict(int)
    for p in providers:
        by_cat[p.category] += 1
    print("\n  by mapped category:")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"    {cat:<16s} {n}")
