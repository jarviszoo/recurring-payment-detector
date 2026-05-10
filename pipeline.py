"""
Full pipeline — Phases 1–4 integrated.

Phase 1: rule-based recurring detection + median predictor
Phase 2: category classification + per-category thresholds
Phase 3: ML-based expected-amount prediction (falls back to median)
Phase 4: feedback-adjusted outlier scoring

Usage:
    from pipeline import run
    alerts = run(transactions)
"""

from datetime import timedelta
from models import Transaction, RecurringPattern, Alert, PredictionResult
from merchant_normalizer import normalize
from category_classifier import classify
from category_rules import get_rule
from recurring_detector import BILLING_CYCLES, CYCLE_FIT_THRESHOLD, _best_billing_cycle
from outlier_detector import evaluate
from ml_predictor import get_predictor
import feedback_adjuster

MIN_HISTORY = 2
_SEASONAL_WINDOW_DAYS = 30


def run(transactions: list[Transaction], use_ml: bool = True) -> list[Alert]:
    """
    Full detection pipeline.

    Args:
        transactions: all known transactions for this user
        use_ml:       if False, skip ML and use median predictor only (Phase 1/2 mode)

    Returns alerts sorted by severity (high first), "none" severity suppressed.
    """
    predictor = get_predictor() if use_ml else None

    by_merchant: dict[str, list[Transaction]] = {}
    for txn in transactions:
        key = normalize(txn.merchant_raw)
        by_merchant.setdefault(key, []).append(txn)

    alerts: list[Alert] = []
    for merchant, txns in by_merchant.items():
        sample = txns[0]
        category = classify(sample.merchant_raw, mcc=sample.category_mcc)
        rule = get_rule(category)

        txns_sorted = sorted(txns, key=lambda t: t.date)
        alerts.extend(
            _evaluate_merchant(merchant, category, rule, txns_sorted, predictor)
        )

    # Phase 4: apply feedback-based score adjustments
    alerts = [feedback_adjuster.adjust(a) for a in alerts]

    # Drop suppressed alerts
    alerts = [a for a in alerts if a.severity != "none"]

    return _sort_alerts(alerts)


# ---------------------------------------------------------------------------
# Per-merchant evaluation
# ---------------------------------------------------------------------------

def _evaluate_merchant(
    merchant: str,
    category: str,
    rule,
    txns: list[Transaction],
    predictor,
) -> list[Alert]:
    alerts: list[Alert] = []

    for i in range(MIN_HISTORY, len(txns)):
        current = txns[i]
        history = txns[:i]
        all_clusters = _cluster_by_amount(history)

        same_tier = _find_same_tier_cluster(current.amount, all_clusters)

        if same_tier is not None:
            if not _is_recurring(same_tier):
                continue
            baseline = same_tier
        else:
            baseline = _closest_recurring_cluster(all_clusters)
            if baseline is None:
                continue

        baseline_limited = sorted(baseline, key=lambda t: t.date)[-rule.lookback:]

        if rule.seasonal:
            prior_year = _same_month_prior_year(current, history)
            if prior_year:
                baseline_limited = _merge_seasonal(baseline_limited, prior_year)

        # Detect billing cycle from this cluster
        billing_cycle = _detect_cycle(baseline_limited)

        # --- Phase 3: ML or median prediction ---
        prediction = _predict(
            baseline_limited, billing_cycle, category, current, predictor
        )

        alert = evaluate(
            txn=current,
            normalized_merchant=merchant,
            expected_amount=prediction.expected,
            category=category,
            category_thresholds=rule.thresholds,
            extra_checks=rule.extra_checks,
        )
        if alert:
            alert.prediction = prediction
            alerts.append(alert)

    return alerts


def _predict(
    baseline: list[Transaction],
    billing_cycle: int,
    category: str,
    current: Transaction,
    predictor,
) -> PredictionResult:
    if predictor is not None:
        sorted_base = sorted(baseline, key=lambda t: t.date)
        days_since = (
            (current.date - sorted_base[-1].date).days
            if sorted_base else billing_cycle
        )
        result = predictor.predict(
            history=sorted_base,
            billing_cycle_days=billing_cycle,
            category=category,
            days_since_last=days_since,
        )
        return result

    # Median fallback
    amounts = sorted(t.amount for t in baseline)
    n = len(amounts)
    mid = n // 2
    med = amounts[mid] if n % 2 else (amounts[mid - 1] + amounts[mid]) / 2
    return PredictionResult(
        expected=round(med, 2),
        lower_bound=round(med * 0.90, 2),
        upper_bound=round(med * 1.10, 2),
        confidence=0.0,
        method="median",
    )


# ---------------------------------------------------------------------------
# Cluster helpers
# ---------------------------------------------------------------------------

def _cluster_by_amount(
    txns: list[Transaction],
    tolerance: float = 0.30,
) -> list[list[Transaction]]:
    sorted_txns = sorted(txns, key=lambda t: t.amount)
    clusters: list[list[Transaction]] = []
    for txn in sorted_txns:
        placed = False
        for cluster in clusters:
            rep = cluster[0].amount
            if rep > 0 and abs(txn.amount - rep) / rep <= tolerance:
                cluster.append(txn)
                placed = True
                break
        if not placed:
            clusters.append([txn])
    return clusters


def _find_same_tier_cluster(
    amount: float,
    clusters: list[list[Transaction]],
    tolerance: float = 0.30,
) -> list[Transaction] | None:
    for cluster in clusters:
        rep = cluster[0].amount
        if rep > 0 and abs(amount - rep) / rep <= tolerance:
            return cluster
    return None


def _closest_recurring_cluster(
    clusters: list[list[Transaction]],
) -> list[Transaction] | None:
    recurring = [c for c in clusters if _is_recurring(c)]
    if not recurring:
        return None
    return max(recurring, key=_median_amount)


def _is_recurring(cluster: list[Transaction]) -> bool:
    if len(cluster) < MIN_HISTORY:
        return False
    sorted_dates = sorted(t.date for t in cluster)
    intervals = [
        (sorted_dates[i + 1] - sorted_dates[i]).days
        for i in range(len(sorted_dates) - 1)
    ]
    _, fit = _best_billing_cycle(intervals)
    return fit >= CYCLE_FIT_THRESHOLD


def _median_amount(cluster: list[Transaction]) -> float:
    amounts = sorted(t.amount for t in cluster)
    n = len(amounts)
    mid = n // 2
    return amounts[mid] if n % 2 else (amounts[mid - 1] + amounts[mid]) / 2


def _detect_cycle(cluster: list[Transaction]) -> int:
    """Return the most likely billing cycle in days for this cluster."""
    from recurring_detector import BILLING_CYCLES as _CYCLES
    cycle_defaults = {
        "weekly": 7, "biweekly": 14, "monthly": 30,
        "quarterly": 91, "annual": 365,
    }
    if len(cluster) < 2:
        return 30
    sorted_dates = sorted(t.date for t in cluster)
    intervals = [
        (sorted_dates[i + 1] - sorted_dates[i]).days
        for i in range(len(sorted_dates) - 1)
    ]
    label, _ = _best_billing_cycle(intervals)
    return cycle_defaults.get(label, 30)


def _same_month_prior_year(
    current: Transaction,
    history: list[Transaction],
) -> list[Transaction]:
    try:
        target = current.date.replace(year=current.date.year - 1)
    except ValueError:
        # Handle leap-day transactions by anchoring to Feb 28 in non-leap years.
        target = current.date.replace(year=current.date.year - 1, day=28)
    return [
        t for t in history
        if abs((t.date - target).days) <= _SEASONAL_WINDOW_DAYS
    ]


def _merge_seasonal(
    recent: list[Transaction],
    prior_year: list[Transaction],
) -> list[Transaction]:
    seen = {t.transaction_id for t in recent}
    extra = [t for t in prior_year if t.transaction_id not in seen]
    return recent + extra


def _sort_alerts(alerts: list[Alert]) -> list[Alert]:
    order = {"high": 0, "warning": 1, "low": 2, "none": 3}
    return sorted(alerts, key=lambda a: order.get(a.severity, 3))


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_alert(alert: Alert, category: str = "") -> str:
    p = alert.prediction
    method_tag = f" [{p.method.upper()} confidence={p.confidence:.2f}]" if p else ""
    ci_line = (
        f"  Prediction CI:    ${p.lower_bound:.2f} – ${p.upper_bound:.2f}{method_tag}"
        if p else ""
    )
    fb_tag = "  [feedback-adjusted]\n" if alert.feedback_adjusted else ""
    lines = [
        f"[{alert.severity.upper()}] Unusual charge detected",
        f"  Merchant:         {alert.normalized_merchant}",
        f"  Category:         {category}" if category else None,
        f"  Expected:         ${alert.expected_amount:.2f}",
        ci_line if ci_line else None,
        f"  Actual:           ${alert.actual_amount:.2f}",
        f"  Difference:       +${alert.difference:.2f} ({alert.percentage_change:.1f}%)",
        f"  Date:             {alert.transaction.date}",
        f"  Outlier score:    {alert.outlier_score:.3f}",
        fb_tag.rstrip() if fb_tag else None,
        f"  Possible reasons: {', '.join(alert.possible_reasons[:3])}",
    ]
    return "\n".join(l for l in lines if l is not None)
