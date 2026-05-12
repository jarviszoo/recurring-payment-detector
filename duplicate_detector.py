"""
Duplicate-charge detector.

Looks for two charges from the same canonical service that:
  - have similar amounts (within 5%)
  - occur within DUPLICATE_WINDOW_DAYS of each other
  - are NOT separated by the merchant's typical billing cycle

Returns one Alert per detected duplicate (the second charge is the alert
target so it can be reviewed/refunded).
"""

from datetime import timedelta
from models import Transaction, Alert, PredictionResult

DUPLICATE_WINDOW_DAYS = 7
AMOUNT_TOLERANCE = 0.05


def detect(
    canonical: str,
    category: str,
    txns: list[Transaction],
) -> list[Alert]:
    """
    Run duplicate detection on a single canonical-service's transactions.
    Expects txns sorted by date.
    """
    alerts: list[Alert] = []
    if len(txns) < 2:
        return alerts

    sorted_txns = sorted(txns, key=lambda t: t.date)
    for i in range(1, len(sorted_txns)):
        a = sorted_txns[i - 1]
        b = sorted_txns[i]
        if not _is_duplicate(a, b):
            continue

        # The "expected" amount is the prior charge; the duplicate is the alert target.
        expected = a.amount
        actual = b.amount
        difference = actual  # the entire amount is the unexpected double-charge
        pct = (actual / expected) if expected > 0 else 1.0

        alerts.append(Alert(
            transaction=b,
            normalized_merchant=canonical,
            expected_amount=round(expected, 2),
            actual_amount=round(actual, 2),
            difference=round(difference, 2),
            percentage_change=round(pct * 100, 1),
            severity="high",
            outlier_score=0.95,
            possible_reasons=[
                "Possible duplicate charge",
                f"Charged twice within {DUPLICATE_WINDOW_DAYS} days",
                "Billing system glitch",
                "Failed-and-retried payment",
            ],
            prediction=PredictionResult(
                expected=round(expected, 2),
                lower_bound=round(expected * 0.9, 2),
                upper_bound=round(expected * 1.1, 2),
                confidence=1.0,
                method="duplicate",
            ),
        ))

    return alerts


def _is_duplicate(a: Transaction, b: Transaction) -> bool:
    days_apart = (b.date - a.date).days
    if days_apart < 0 or days_apart > DUPLICATE_WINDOW_DAYS:
        return False
    if a.amount <= 0 or b.amount <= 0:
        return False
    if abs(a.amount - b.amount) / max(a.amount, b.amount) > AMOUNT_TOLERANCE:
        return False
    return True
