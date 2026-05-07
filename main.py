"""
Full demo: Phases 1–4.

Run 1: detect anomalies with ML predictions
Run 2: simulate user feedback on each alert
Run 3: re-run detection — show how scores shift after feedback
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import feedback_store
from sample_data import SAMPLE_TRANSACTIONS
from pipeline import run, format_alert
from category_classifier import classify

# Simulated user responses for demo purposes:
#   merchant → feedback type
SIMULATED_FEEDBACK = {
    "Adobe":           "unexpected",   # user did NOT authorise the upgrade
    "Canva":           "expected",     # user knew about the annual plan
    "Pg E Autopay":    "expected",     # seasonal winter spike, user confirms
    "GitHub":          "unexpected",   # user didn't upgrade the plan
    "Verizon Wireless":"expected",     # user added a line on purpose
    "Apple.Com/Bill":  "expected",     # user upgraded to Apple Music Individual
}


def _category(alert) -> str:
    return classify(alert.transaction.merchant_raw, mcc=alert.transaction.category_mcc)


def main():
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
    print("Training ML model on synthetic data...", end=" ", flush=True)
    alerts_pass1 = run(SAMPLE_TRANSACTIONS, use_ml=True)
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
        feedback = SIMULATED_FEEDBACK.get(alert.normalized_merchant, "remind_later")
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
    alerts_pass2 = run(SAMPLE_TRANSACTIONS, use_ml=True)
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
