"""
Price-tier lookup against providers.db.

Given a resolved canonical service name, returns all known price tiers from
the price_tiers table, then evaluates whether a given charge matches an
expected tier, looks like a price hike, or is outside any known plan.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path(r"C:\Users\1\recurring-payment-detector\providers.db")

# Match a charge to a tier if the price is within this % of the tier price
TIER_MATCH_TOLERANCE = 0.10
# Flag if the charge is at least this much above the highest known tier
PRICE_HIKE_THRESHOLD = 0.15


@dataclass
class PriceTier:
    tier_name: str
    price_monthly: Optional[float]
    price_annual: Optional[float]
    price_quarterly: Optional[float]
    currency: str
    is_promo: bool


@dataclass
class PriceEvaluation:
    service_name: str
    charge_amount: float
    billing_cycle: Optional[str]            # "monthly" | "annual" | ...
    matched_tier: Optional[PriceTier] = None
    matched_cycle_field: Optional[str] = None   # "price_monthly" / "price_annual" / ...
    closest_tier: Optional[PriceTier] = None
    closest_tier_price: Optional[float] = None
    deviation_pct: Optional[float] = None       # % above closest known tier
    verdict: str = "unknown"                    # "match"|"price_hike"|"unknown_tier"|"no_data"|"below_known"
    all_tiers: list[PriceTier] = field(default_factory=list)
    explanation: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_tiers(canonical_name: str, db_path: Path = DEFAULT_DB) -> list[PriceTier]:
    """Return every PriceTier the DB knows for this canonical service."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT pt.tier_name, pt.price_monthly, pt.price_annual, pt.price_quarterly,
               pt.currency, pt.is_promo
        FROM price_tiers pt
        JOIN providers p ON p.id = pt.provider_id
        WHERE LOWER(p.name) = LOWER(?)
    """, (canonical_name,)).fetchall()
    conn.close()
    return [
        PriceTier(name, mo, an, qt, cur or "USD", bool(promo))
        for name, mo, an, qt, cur, promo in rows
    ]


def evaluate(
    canonical_name: str,
    charge_amount: float,
    billing_cycle: Optional[str] = "monthly",
    db_path: Path = DEFAULT_DB,
) -> PriceEvaluation:
    """Match a charge against the known price tiers and assign a verdict."""
    tiers = fetch_tiers(canonical_name, db_path)
    eval_ = PriceEvaluation(
        service_name=canonical_name,
        charge_amount=charge_amount,
        billing_cycle=billing_cycle,
        all_tiers=tiers,
    )

    if not tiers:
        eval_.verdict = "no_data"
        eval_.explanation = f"No price tiers known for {canonical_name}; cannot evaluate."
        return eval_

    cycle_field = _cycle_field(billing_cycle)

    # Find prices for the requested cycle, else fall back to monthly
    cycle_prices: list[tuple[PriceTier, float]] = []
    for t in tiers:
        price = _tier_price(t, cycle_field)
        if price is None or price <= 0:
            continue
        cycle_prices.append((t, price))

    if not cycle_prices:
        # Fallback: try monthly even if the email said annual (and vice versa)
        for fallback in ("price_monthly", "price_annual", "price_quarterly"):
            if fallback == cycle_field:
                continue
            for t in tiers:
                price = _tier_price(t, fallback)
                if price and price > 0:
                    cycle_prices.append((t, price))
            if cycle_prices:
                eval_.matched_cycle_field = fallback
                break
    else:
        eval_.matched_cycle_field = cycle_field

    if not cycle_prices:
        eval_.verdict = "no_data"
        eval_.explanation = f"{canonical_name} has tiers but no price for any billing cycle."
        return eval_

    # 1. Try to match the exact tier
    for t, price in cycle_prices:
        if _within_tolerance(charge_amount, price, TIER_MATCH_TOLERANCE):
            eval_.matched_tier = t
            eval_.closest_tier = t
            eval_.closest_tier_price = price
            eval_.deviation_pct = (charge_amount - price) / price
            eval_.verdict = "match"
            eval_.explanation = (
                f"Charge ${charge_amount:.2f} matches the '{t.tier_name}' tier "
                f"(${price:.2f}/{_cycle_label(eval_.matched_cycle_field)})."
            )
            return eval_

    # 2. No exact match — find the closest tier
    closest_t, closest_p = min(cycle_prices, key=lambda x: abs(x[1] - charge_amount))
    deviation = (charge_amount - closest_p) / closest_p
    eval_.closest_tier = closest_t
    eval_.closest_tier_price = closest_p
    eval_.deviation_pct = deviation

    max_known = max(p for _, p in cycle_prices)
    cycle_label = _cycle_label(eval_.matched_cycle_field)

    if charge_amount > max_known * (1 + PRICE_HIKE_THRESHOLD):
        eval_.verdict = "price_hike"
        eval_.explanation = (
            f"Charge ${charge_amount:.2f} is {deviation*100:+.1f}% vs the '{closest_t.tier_name}' "
            f"tier (${closest_p:.2f}/{cycle_label}); above any known plan for {canonical_name}."
        )
    elif charge_amount < min(p for _, p in cycle_prices) * (1 - PRICE_HIKE_THRESHOLD):
        eval_.verdict = "below_known"
        eval_.explanation = (
            f"Charge ${charge_amount:.2f} is below the cheapest known {canonical_name} tier "
            f"('{closest_t.tier_name}', ${closest_p:.2f}/{cycle_label}). "
            f"Likely a promo, partial-month charge, or unfamiliar tier."
        )
    else:
        eval_.verdict = "unknown_tier"
        eval_.explanation = (
            f"Charge ${charge_amount:.2f} doesn't match any known tier exactly; "
            f"closest is '{closest_t.tier_name}' at ${closest_p:.2f}/{cycle_label} "
            f"({deviation*100:+.1f}%)."
        )
    return eval_


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cycle_field(cycle: Optional[str]) -> str:
    if not cycle:
        return "price_monthly"
    return {
        "monthly":   "price_monthly",
        "annual":    "price_annual",
        "yearly":    "price_annual",
        "quarterly": "price_quarterly",
    }.get(cycle.lower(), "price_monthly")


def _tier_price(t: PriceTier, field: str) -> Optional[float]:
    return {
        "price_monthly":   t.price_monthly,
        "price_annual":    t.price_annual,
        "price_quarterly": t.price_quarterly,
    }.get(field)


def _within_tolerance(charge: float, tier_price: float, tol: float) -> bool:
    if tier_price <= 0:
        return False
    return abs(charge - tier_price) / tier_price <= tol


def _cycle_label(field: Optional[str]) -> str:
    return {
        "price_monthly":   "mo",
        "price_annual":    "yr",
        "price_quarterly": "qtr",
    }.get(field or "", "")
