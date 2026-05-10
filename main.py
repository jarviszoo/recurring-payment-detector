"""
Full pipeline runner (Phases 1–4).

Supports:
  - demo mode with bundled sample data
  - dynamic per-user mode from a JSON transaction file
"""

import argparse
import json
import sys, io
from datetime import date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import feedback_store
from models import Transaction
from sample_data import SAMPLE_TRANSACTIONS
from pipeline import run, format_alert
from category_classifier import classify
from entity_resolution import build_canonical_registry, save_registry_snapshot

# Simulated user responses for demo purposes:
#   merchant → feedback type
SIMULATED_FEEDBACK = {
    "Adobe":           "unexpected",   # user did NOT authorise the upgrade
    "Canva":           "expected",     # user knew about the annual plan
    "PG&E":            "expected",     # seasonal winter spike, user confirms
    "GitHub":          "unexpected",   # user didn't upgrade the plan
    "Verizon Wireless":"expected",     # user added a line on purpose
    "Apple.Com/Bill":  "expected",     # user upgraded to Apple Music Individual
}


def _category(alert) -> str:
    return classify(alert.transaction.merchant_raw, mcc=alert.transaction.category_mcc)


def _load_transactions(path: str | None) -> list[Transaction]:
    if not path:
        return SAMPLE_TRANSACTIONS
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    txns = []
    for i, row in enumerate(raw):
        txns.append(
            Transaction(
                transaction_id=str(row.get("transaction_id", f"user-{i+1}")),
                merchant_raw=row["merchant_raw"],
                amount=float(row["amount"]),
                date=date.fromisoformat(row["date"]),
                currency=row.get("currency", "USD"),
                category_mcc=row.get("category_mcc"),
                payment_method=row.get("payment_method"),
                description=row.get("description"),
            )
        )
    return txns


def _load_feedback_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def main():
    parser = argparse.ArgumentParser(description="Recurring-payment anomaly detector")
    parser.add_argument(
        "--transactions-file",
        help="Path to JSON array of transactions. If omitted, demo sample data is used.",
    )
    parser.add_argument(
        "--feedback-file",
        help="Optional JSON object mapping normalized merchant -> feedback "
             "(expected|unexpected|cancel|remind_later).",
    )
    parser.add_argument(
        "--use-simulated-feedback",
        action="store_true",
        help="Use built-in demo feedback map when no --feedback-file is provided.",
    )
    parser.add_argument(
        "--registry-output",
        help="Optional path to write canonical provider registry JSON snapshot.",
    )
    args = parser.parse_args()

    transactions = _load_transactions(args.transactions_file)
    if args.registry_output:
        providers, events = build_canonical_registry(transactions)
        save_registry_snapshot(providers, events, args.registry_output)
        print(f"Saved registry snapshot to: {args.registry_output}")
    feedback_map = _load_feedback_map(args.feedback_file)
    if not feedback_map and args.use_simulated_feedback:
        feedback_map = SIMULATED_FEEDBACK

    # ------------------------------------------------------------------
    # Clean slate each run
    # ------------------------------------------------------------------
    feedback_store.clear()

    # ------------------------------------------------------------------
    # Pass 1: Initial detection (no feedback yet)
    # ------------------------------------------------------------------
    print("=" * 60)
    print("PASS 1 — Initial detection (no prior feedback)")
    print("=" * 60)
    print("Training ML model on provided transactions...", end=" ", flush=True)
    alerts_pass1 = run(transactions, use_ml=True)
    print("done.\n")

    if not alerts_pass1:
        print("No anomalies detected.")
        return

    print(f"{len(alerts_pass1)} alert(s):\n")
    for alert in alerts_pass1:
        print(format_alert(alert, category=_category(alert)))
        print()

    # ------------------------------------------------------------------
    # Phase 4: Simulate user feedback on each alert
    # ------------------------------------------------------------------
    print("=" * 60)
    print("PHASE 4 — User feedback")
    print("=" * 60)
    for alert in alerts_pass1:
        feedback = feedback_map.get(alert.normalized_merchant, "remind_later")
        entry = feedback_store.record(alert, _category(alert), feedback)
        icon = {"expected": "[OK]", "unexpected": "[!!]", "cancel": "[X]", "remind_later": "[?]"}.get(feedback, "[?]")
        print(
            f"  {icon} {alert.normalized_merchant:20s} "
            f"${alert.actual_amount:>8.2f}  ->  [{feedback}]"
        )

    # ------------------------------------------------------------------
    # Pass 2: Re-run with feedback in store
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("PASS 2 — Re-run after feedback (scores adjusted)")
    print("=" * 60)
    alerts_pass2 = run(transactions, use_ml=True)
    print(f"{len(alerts_pass2)} alert(s) remaining after feedback:\n")
    for alert in alerts_pass2:
        fb_note = " [score lowered by feedback]" if alert.feedback_adjusted else ""
        print(format_alert(alert, category=_category(alert)) + fb_note)
        print()

    # ------------------------------------------------------------------
    # Summary: what changed
    # ------------------------------------------------------------------
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    merchants1 = {a.normalized_merchant: a.severity for a in alerts_pass1}
    merchants2 = {a.normalized_merchant: a.severity for a in alerts_pass2}

    all_merchants = sorted(set(merchants1) | set(merchants2))
    for m in all_merchants:
        before = merchants1.get(m, "—")
        after  = merchants2.get(m, "suppressed")
        changed = " ← changed" if before != after else ""
        print(f"  {m:22s}  {before:8s} → {after}{changed}")


if __name__ == "__main__":
    main()
