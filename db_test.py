"""
End-to-end integration test against the real providers.db.

Procedure:
  1. Load 424 providers + 1100 aliases + 2356 price tiers from the SQLite DB.
  2. Bootstrap the entity_resolver registry from this data.
  3. Generate a realistic synthetic transaction stream:
       - Sample N providers
       - Pick a price tier for each
       - Emit 3-6 monthly charges using random aliases (with noise injected
         to simulate bank statement formatting)
       - Inject anomalies in ~25% of providers (price hike, plan upgrade,
         duplicate charge)
  4. Run the full Phase 0-4 pipeline on the generated stream.
  5. Report:
       a) Resolution accuracy (raw -> correct canonical name)
       b) Anomaly precision/recall against the ground-truth injected list
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import random
from datetime import date, timedelta
from collections import defaultdict
from dataclasses import dataclass

import service_registry
import feedback_store
from models import Transaction
from pipeline import run, resolve_all
from db_loader import load_providers, to_seed_tuples, DbProvider


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
SAMPLE_PROVIDERS = 80          # how many providers to draw from the DB
MIN_HISTORY_PER_PROVIDER = 3
MAX_HISTORY_PER_PROVIDER = 6
ANOMALY_RATE = 0.25            # fraction of providers that get an anomaly
NOISE_RATE = 0.30              # fraction of charges with formatting noise
RANDOM_SEED = 42

# Standard noise patterns banks add to merchant strings
NOISE_SUFFIXES = [
    " 866-579-7172", " 8004310023", " #REF99821", " *AUTH001",
    " LOS GATOS CA", " SAN FRANCISCO CA", " WA US", " /BILL",
    "*RECURRING", "  ", " INC", " LLC",
]

# Anomaly types we'll inject
ANOMALY_TYPES = ["price_hike", "plan_upgrade", "duplicate"]


# ---------------------------------------------------------------------------
# Synthetic transaction generator
# ---------------------------------------------------------------------------

@dataclass
class GroundTruth:
    txn_id: str
    expected_canonical: str
    is_anomaly: bool
    anomaly_type: str | None = None


def generate_stream(
    providers: list[DbProvider],
    rng: random.Random,
) -> tuple[list[Transaction], list[GroundTruth]]:
    txns: list[Transaction] = []
    truth: list[GroundTruth] = []

    sample = rng.sample(providers, min(SAMPLE_PROVIDERS, len(providers)))
    counter = 0

    for p in sample:
        if not p.tiers:
            continue
        tier = _pick_tier(p, rng)
        base_price = _tier_price(tier, "monthly")
        if base_price is None or base_price <= 0:
            continue

        # Pick how many months of history this provider gets
        n_months = rng.randint(MIN_HISTORY_PER_PROVIDER, MAX_HISTORY_PER_PROVIDER)
        start_date = date(2025, 8, 1)

        # Decide if this provider gets an anomaly (only if we have ≥ 3 months)
        anomaly_enabled = (n_months >= 3) and (rng.random() < ANOMALY_RATE)
        anomaly_type = rng.choice(ANOMALY_TYPES) if anomaly_enabled else None
        anomaly_month = n_months - 1  # the last charge

        for m in range(n_months):
            charge_date = start_date + timedelta(days=30 * m + rng.randint(-2, 2))
            amount = base_price

            # Apply tiny realistic noise (tax, rounding) every month
            amount = round(amount * (1 + rng.uniform(-0.015, 0.015)), 2)

            is_anomalous_charge = False
            if anomaly_enabled and m == anomaly_month:
                amount, is_anomalous_charge = _apply_anomaly(amount, base_price, p, anomaly_type, rng)

            raw = _make_raw_alias(p, rng)
            txn = Transaction(
                transaction_id=f"t{counter:04d}",
                merchant_raw=raw,
                amount=amount,
                date=charge_date,
            )
            txns.append(txn)
            # For duplicate-type anomalies the alert fires on the SECOND charge,
            # so we mark the original as non-anomalous and tag the duplicate (added below).
            is_price_anomaly = is_anomalous_charge and anomaly_type != "duplicate"
            truth.append(GroundTruth(
                txn_id=txn.transaction_id,
                expected_canonical=p.name,
                is_anomaly=is_price_anomaly,
                anomaly_type=anomaly_type if is_price_anomaly else None,
            ))
            counter += 1

            if is_anomalous_charge and anomaly_type == "duplicate":
                dup = Transaction(
                    transaction_id=f"t{counter:04d}",
                    merchant_raw=_make_raw_alias(p, rng),
                    amount=amount,
                    date=charge_date + timedelta(days=1),
                )
                txns.append(dup)
                truth.append(GroundTruth(
                    txn_id=dup.transaction_id,
                    expected_canonical=p.name,
                    is_anomaly=True,          # the duplicate is the anomaly
                    anomaly_type="duplicate",
                ))
                counter += 1

    rng.shuffle(txns)
    truth_by_id = {g.txn_id: g for g in truth}
    truth_sorted = [truth_by_id[t.transaction_id] for t in txns]
    return txns, truth_sorted


def _pick_tier(p: DbProvider, rng: random.Random) -> dict:
    """Prefer a non-promo non-free tier."""
    real = [t for t in p.tiers if not t["is_promo"] and (t["price_monthly"] or 0) > 0.5]
    pool = real if real else p.tiers
    return rng.choice(pool)


def _tier_price(tier: dict, cycle: str) -> float | None:
    if cycle == "monthly":
        return tier.get("price_monthly")
    if cycle == "annual":
        return tier.get("price_annual")
    return None


def _apply_anomaly(
    amount: float, base: float, p: DbProvider, atype: str, rng: random.Random
) -> tuple[float, bool]:
    if atype == "price_hike":
        new = round(amount * rng.uniform(1.6, 2.5), 2)
        return new, True
    if atype == "plan_upgrade":
        # Find a higher tier
        higher = [t for t in p.tiers
                  if t["price_monthly"] and t["price_monthly"] > base * 1.4]
        if higher:
            new_tier = rng.choice(higher)
            return round(new_tier["price_monthly"], 2), True
        # Fall back to a multiplier hike
        return round(amount * 2.0, 2), True
    if atype == "duplicate":
        return amount, True   # the duplicate is added by the caller
    return amount, False


def _make_raw_alias(p: DbProvider, rng: random.Random) -> str:
    """Pick one of the provider's aliases (or canonical name) and add bank-style noise."""
    alias = rng.choice(p.aliases) if p.aliases and rng.random() < 0.85 else p.name
    if rng.random() < NOISE_RATE:
        alias = alias + rng.choice(NOISE_SUFFIXES)
    return alias


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def main():
    rng = random.Random(RANDOM_SEED)

    print("=" * 64)
    print("STAGE 1 — Load real DB into registry")
    print("=" * 64)
    service_registry.clear()
    feedback_store.clear()
    providers = load_providers()
    seed = to_seed_tuples(providers)
    service_registry.bootstrap_seed(seed)
    print(f"Loaded {len(providers)} providers, {sum(len(p.aliases) for p in providers)} aliases")
    print(f"Registry now has {len(service_registry.all_services())} canonical services.")

    print()
    print("=" * 64)
    print("STAGE 2 — Generate synthetic transaction stream")
    print("=" * 64)
    txns, truth = generate_stream(providers, rng)
    n_anom = sum(1 for g in truth if g.is_anomaly)
    print(f"Generated {len(txns)} transactions across {SAMPLE_PROVIDERS} sampled providers")
    print(f"Injected {n_anom} ground-truth anomalies "
          f"(rate {n_anom/len(txns)*100:.1f}%)")
    print(f"  by type: " + ", ".join(
        f"{t}={sum(1 for g in truth if g.anomaly_type == t)}" for t in ANOMALY_TYPES
    ))

    print()
    print("=" * 64)
    print("STAGE 3 — Resolve all merchants")
    print("=" * 64)
    resolutions = resolve_all(txns)
    correct = 0
    miss_examples = []
    method_counts: dict[str, int] = defaultdict(int)
    for txn, res, gt in zip(txns, resolutions, truth):
        method_counts[res.method] += 1
        if res.canonical_name == gt.expected_canonical:
            correct += 1
        elif len(miss_examples) < 8:
            miss_examples.append((txn.merchant_raw, res.canonical_name, gt.expected_canonical, res.method, res.confidence))

    print(f"Resolution accuracy: {correct}/{len(txns)} = {correct/len(txns)*100:.1f}%")
    print("Method breakdown:")
    for m, n in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"  {m:<22s} {n}")
    if miss_examples:
        print("\nSample misses:")
        for raw, got, want, method, conf in miss_examples:
            print(f"  raw={raw!r:<40s} got={got!r:<25s} want={want!r:<25s} method={method} conf={conf:.2f}")

    print()
    print("=" * 64)
    print("STAGE 4 — Run anomaly detection pipeline")
    print("=" * 64)
    print("Training ML model...", end=" ", flush=True)
    alerts = run(txns, use_ml=True)
    print("done.")
    print(f"Pipeline raised {len(alerts)} alert(s).")

    # Build the truth set: which transaction IDs are real anomalies?
    truth_anom_ids = {g.txn_id for g in truth if g.is_anomaly}
    alert_txn_ids  = {a.transaction.transaction_id for a in alerts}

    tp = len(truth_anom_ids & alert_txn_ids)
    fp = len(alert_txn_ids - truth_anom_ids)
    fn = len(truth_anom_ids - alert_txn_ids)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0

    print(f"  True positives:  {tp}")
    print(f"  False positives: {fp}")
    print(f"  False negatives: {fn}")
    print(f"  Precision:       {precision*100:.1f}%")
    print(f"  Recall:          {recall*100:.1f}%")

    # Show some sample alerts
    print("\nSample alerts (top 8 by severity):")
    for a in alerts[:8]:
        gt = next((g for g in truth if g.txn_id == a.transaction.transaction_id), None)
        tag = ""
        if gt:
            if gt.is_anomaly:
                tag = f" [TRUE POSITIVE: {gt.anomaly_type}]"
            else:
                tag = " [FALSE POSITIVE]"
        print(f"  [{a.severity:<7s}] {a.normalized_merchant:<25s} "
              f"${a.expected_amount:>7.2f} -> ${a.actual_amount:>7.2f}  "
              f"({a.percentage_change:+.1f}%){tag}")

    # Final summary
    print()
    print("=" * 64)
    print("SUMMARY")
    print("=" * 64)
    print(f"  Resolution accuracy: {correct/len(txns)*100:5.1f}%   ({correct}/{len(txns)})")
    print(f"  Anomaly precision:   {precision*100:5.1f}%   ({tp}/{tp+fp})")
    print(f"  Anomaly recall:      {recall*100:5.1f}%   ({tp}/{tp+fn})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
