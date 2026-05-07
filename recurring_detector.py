from datetime import date, timedelta
from typing import Optional
from models import Transaction, RecurringPattern

# Recognized billing cycles: (label, min_days, max_days)
BILLING_CYCLES = [
    ("weekly",    5,   9),
    ("biweekly", 12,  16),
    ("monthly",  28,  35),
    ("quarterly", 85, 95),
    ("annual",  350, 380),
]

# Minimum charge occurrences to qualify as recurring
MIN_OCCURRENCES = 2

# Fraction of charges that must be within the tolerance window
CYCLE_FIT_THRESHOLD = 0.60

# Maximum relative difference between two amounts to be considered "similar"
AMOUNT_SIMILARITY_TOLERANCE = 0.30


def detect_recurring(
    transactions: list[Transaction],
) -> dict[str, list[RecurringPattern]]:
    """
    Group transactions by normalized merchant, then detect recurring patterns.
    Returns a dict: normalized_merchant -> list of RecurringPattern.
    Multiple patterns per merchant are possible (e.g. Apple $2.99 + $9.99).
    """
    from merchant_normalizer import normalize

    by_merchant: dict[str, list[Transaction]] = {}
    for txn in transactions:
        key = normalize(txn.merchant_raw)
        by_merchant.setdefault(key, []).append(txn)

    result: dict[str, list[RecurringPattern]] = {}
    for merchant, txns in by_merchant.items():
        patterns = _find_patterns(merchant, txns)
        if patterns:
            result[merchant] = patterns
    return result


def _find_patterns(
    merchant: str, txns: list[Transaction]
) -> list[RecurringPattern]:
    """Split transactions into amount clusters, then score each cluster."""
    clusters = _cluster_by_amount(txns)
    patterns = []
    for cluster in clusters:
        if len(cluster) < MIN_OCCURRENCES:
            continue
        pattern = _score_cluster(merchant, cluster)
        if pattern:
            patterns.append(pattern)
    return patterns


def _cluster_by_amount(
    txns: list[Transaction],
) -> list[list[Transaction]]:
    """Group transactions whose amounts are within AMOUNT_SIMILARITY_TOLERANCE of each other."""
    sorted_txns = sorted(txns, key=lambda t: t.amount)
    clusters: list[list[Transaction]] = []

    for txn in sorted_txns:
        placed = False
        for cluster in clusters:
            representative = cluster[0].amount
            if representative == 0:
                continue
            if abs(txn.amount - representative) / representative <= AMOUNT_SIMILARITY_TOLERANCE:
                cluster.append(txn)
                placed = True
                break
        if not placed:
            clusters.append([txn])

    return clusters


def _score_cluster(
    merchant: str, txns: list[Transaction]
) -> Optional[RecurringPattern]:
    """Detect the billing cycle and compute a confidence score."""
    txns_sorted = sorted(txns, key=lambda t: t.date)

    if len(txns_sorted) < MIN_OCCURRENCES:
        return None

    intervals = [
        (txns_sorted[i + 1].date - txns_sorted[i].date).days
        for i in range(len(txns_sorted) - 1)
    ]

    best_cycle, best_fit = _best_billing_cycle(intervals)
    if best_fit < CYCLE_FIT_THRESHOLD:
        return None

    # Confidence score components
    amount_consistency = _amount_consistency_score(txns)
    cycle_score = best_fit
    occurrence_score = min(1.0, len(txns) / 6)  # caps out at 6 occurrences

    confidence = (
        cycle_score * 0.45
        + amount_consistency * 0.35
        + occurrence_score * 0.20
    )

    return RecurringPattern(
        normalized_merchant=merchant,
        transactions=txns_sorted,
        billing_cycle_days=_cycle_label_to_days(best_cycle),
        confidence_score=round(confidence, 3),
    )


def _best_billing_cycle(intervals: list[int]) -> tuple[str, float]:
    """Return the cycle label and fraction of intervals that fit it."""
    if not intervals:
        return ("unknown", 0.0)

    best_label = "unknown"
    best_fit = 0.0

    for label, min_d, max_d in BILLING_CYCLES:
        fits = sum(1 for d in intervals if min_d <= d <= max_d)
        fit_ratio = fits / len(intervals)
        if fit_ratio > best_fit:
            best_fit = fit_ratio
            best_label = label

    return best_label, best_fit


def _amount_consistency_score(txns: list[Transaction]) -> float:
    """1.0 if all amounts identical, lower if they vary."""
    amounts = [t.amount for t in txns]
    if not amounts:
        return 0.0
    med = _median(amounts)
    if med == 0:
        return 1.0
    deviations = [abs(a - med) / med for a in amounts]
    avg_deviation = sum(deviations) / len(deviations)
    return max(0.0, 1.0 - avg_deviation)


def _cycle_label_to_days(label: str) -> int:
    defaults = {
        "weekly": 7,
        "biweekly": 14,
        "monthly": 30,
        "quarterly": 91,
        "annual": 365,
    }
    return defaults.get(label, 30)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
