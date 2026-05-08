"""
End-to-end demo covering all phases:

  Phase 0  Entity resolution: raw -> canonical service registry
           (cold start, fuzzy + embedding fallback, auto-learned aliases)
  Phase 1  Rule-based recurring detection
  Phase 2  Category classification + per-category thresholds
  Phase 3  ML expected-amount prediction with confidence intervals
  Phase 4  Human-in-the-loop feedback to adjust scores

The demo intentionally uses noisy raw merchant strings (typos, formatting
variants) to exercise the resolver.
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from datetime import date
from sample_data import SAMPLE_TRANSACTIONS
from models import Transaction
from pipeline import run, format_alert, resolve_all
from category_classifier import classify

import service_registry
import feedback_store
import entity_resolver
import clusterer

from merchant_normalizer import SEED_SERVICES


# Add some intentionally noisy / typo'd transactions to exercise the resolver
NOISY_EXTRAS = [
    Transaction("n001", "NETFLX",                  15.49, date(2026, 4, 1)),
    Transaction("n002", "Netflx.com 866-579-7172", 15.49, date(2026, 5, 1)),
    Transaction("n003", "SPOTIFY-USA*REF99921",    11.18, date(2026, 4, 10)),
    Transaction("n004", "PG E AUTOPAY",            205.00, date(2026, 1, 15)),
    Transaction("n005", "ATT WIRELESS 8004310023", 95.00, date(2026, 4, 5)),
    Transaction("n006", "TOTALLY UNKNOWN VENDOR",  4.99,  date(2026, 4, 20)),
    Transaction("n007", "Totally Unknown Vendor",  4.99,  date(2026, 5, 20)),
    Transaction("n008", "totally-unknown vendor",  4.99,  date(2026, 6, 20)),
]


def _category_for(merchant_raw: str, mcc: str | None) -> str:
    """Prefer the registry's resolved category; fall back to keyword classifier."""
    res = entity_resolver.resolve(merchant_raw, mcc=mcc, auto_create=False)
    if res.category:
        return res.category
    return classify(merchant_raw, mcc=mcc)


SIMULATED_FEEDBACK = {
    "Adobe":     "unexpected",
    "Canva":     "expected",
    "PG&E":      "expected",
    "GitHub":    "unexpected",
    "Verizon":   "expected",
    "Apple":     "expected",
    "AT&T":      "expected",
}


def main():
    # ---------------------- Cold-start setup ----------------------
    feedback_store.clear()
    service_registry.clear()
    print("=" * 64)
    print("STAGE A — Cold start")
    print("=" * 64)
    print(f"Registry has {len(service_registry.all_services())} services.")

    print("\nSeeding registry with well-known services for warm-start...")
    service_registry.bootstrap_seed(SEED_SERVICES)
    print(f"Registry now has {len(service_registry.all_services())} services.")

    # ---------------------- Resolution demo ----------------------
    print("\n" + "=" * 64)
    print("STAGE B — Entity resolution (raw merchant -> canonical service)")
    print("=" * 64)

    all_txns = SAMPLE_TRANSACTIONS + NOISY_EXTRAS
    resolutions = resolve_all(all_txns)

    print(f"\n{'RAW':<35s} {'CANONICAL':<22s} {'METHOD':<18s} CONF")
    print("-" * 90)
    seen_raws = set()
    for txn, res in zip(all_txns, resolutions):
        if txn.merchant_raw in seen_raws:
            continue
        seen_raws.add(txn.merchant_raw)
        cn = res.canonical_name or "(unresolved)"
        print(f"{txn.merchant_raw[:34]:<35s} {cn[:21]:<22s} {res.method:<18s} {res.confidence:.2f}")

    print(f"\nRegistry now has {len(service_registry.all_services())} services after auto-learning.")

    # Show services that grew aliases or were auto-created
    print("\nNotable registry entries:")
    for s in service_registry.all_services():
        if len(s.aliases) > 1 or s.source != "manual":
            cls = "auto" if s.source == "auto" else s.source
            print(f"  {s.canonical_name:<20s} [{cls:<10s}] aliases={s.aliases[:4]}")

    # ---------------------- Anomaly detection (Pass 1) ----------------------
    print("\n" + "=" * 64)
    print("STAGE C — Anomaly detection (Pass 1, no feedback yet)")
    print("=" * 64)
    print("Training ML model on synthetic data...", end=" ", flush=True)
    alerts_pass1 = run(all_txns, use_ml=True)
    print("done.")
    print(f"\n{len(alerts_pass1)} alert(s):\n")
    for alert in alerts_pass1:
        cat = _category_for(alert.transaction.merchant_raw, alert.transaction.category_mcc)
        print(format_alert(alert, category=cat))
        print()

    # ---------------------- User feedback ----------------------
    print("=" * 64)
    print("STAGE D — User feedback")
    print("=" * 64)
    icons = {"expected": "[OK]", "unexpected": "[!!]", "cancel": "[X]", "remind_later": "[?]"}
    for alert in alerts_pass1:
        feedback = SIMULATED_FEEDBACK.get(alert.normalized_merchant, "remind_later")
        cat = _category_for(alert.transaction.merchant_raw, alert.transaction.category_mcc)
        feedback_store.record(alert, cat, feedback)
        print(f"  {icons[feedback]} {alert.normalized_merchant:<22s} ${alert.actual_amount:>8.2f}  ->  [{feedback}]")

    # ---------------------- Anomaly detection (Pass 2) ----------------------
    print("\n" + "=" * 64)
    print("STAGE E — Anomaly detection (Pass 2, after feedback)")
    print("=" * 64)
    alerts_pass2 = run(all_txns, use_ml=True)
    print(f"\n{len(alerts_pass2)} alert(s):\n")
    for alert in alerts_pass2:
        cat = _category_for(alert.transaction.merchant_raw, alert.transaction.category_mcc)
        print(format_alert(alert, category=cat))
        print()

    # ---------------------- Clustering demo ----------------------
    print("=" * 64)
    print("STAGE F — Batch clustering of low-confidence canonical names")
    print("=" * 64)
    low_conf_services = [s for s in service_registry.all_services() if s.confidence < 0.5]
    if low_conf_services:
        print(f"Running clustering over {len(low_conf_services)} low-confidence services:")
        all_aliases = []
        for s in low_conf_services:
            all_aliases.extend(s.aliases)
        clusters = clusterer.cluster_unresolved(all_aliases)
        for c in clusters:
            print(f"  cluster size={c['size']} -> {c['canonical_candidate']!r}, members={c['members'][:5]}")
    else:
        print("No low-confidence services to cluster.")

    # ---------------------- Summary ----------------------
    print("\n" + "=" * 64)
    print("SUMMARY")
    print("=" * 64)
    by1 = {a.normalized_merchant: a.severity for a in alerts_pass1}
    by2 = {a.normalized_merchant: a.severity for a in alerts_pass2}
    for m in sorted(set(by1) | set(by2)):
        before = by1.get(m, "—")
        after = by2.get(m, "suppressed")
        change = " ← changed" if before != after else ""
        print(f"  {m:<22s} {before:<10s} → {after}{change}")
    print(f"\nFinal registry: {len(service_registry.all_services())} canonical services.")


if __name__ == "__main__":
    main()
