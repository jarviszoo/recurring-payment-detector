from models import Transaction, Alert

# Universal tier-based defaults: (max_expected, min_dollar_diff, min_pct_change)
UNIVERSAL_THRESHOLDS = [
    (20.00,  3.00, 0.20),
    (100.00, 10.00, 0.15),
    (float("inf"), 25.00, 0.10),
]

SEVERITY_BANDS = [
    (0.85, "high"),
    (0.65, "warning"),
    (0.40, "low"),
]

# Category-specific reason hints
_CATEGORY_REASONS: dict[str, list[str]] = {
    "telecom":       ["Roaming charges", "New device installment", "Plan add-on", "Late fee"],
    "utilities":     ["Seasonal usage spike", "Rate increase", "Usage overage"],
    "insurance":     ["Annual premium adjustment", "Coverage change", "Rate increase"],
    "software":      ["Seat count change", "Annual plan conversion", "Add-on feature"],
    "app_store":     ["New in-app subscription", "Plan upgrade", "Price increase"],
    "mixed_commerce":["New subscription added", "Membership fee change"],
}

_UNIVERSAL_REASONS = [
    "Plan upgrade",
    "Expired promotional discount",
    "Annual renewal",
    "Added feature or add-on",
    "Billing error",
]


def evaluate(
    txn: Transaction,
    normalized_merchant: str,
    expected_amount: float,
    category: str = "general",
    category_thresholds: tuple[float, float] | None = None,
    extra_checks: list[str] | None = None,
) -> "Alert | None":
    """
    Compare actual charge against expected amount using category-aware thresholds.
    Returns an Alert if anomalous, otherwise None.
    """
    actual = txn.amount
    difference = actual - expected_amount

    if difference <= 0 or expected_amount == 0:
        return None

    pct_change = difference / expected_amount

    if category_thresholds:
        dollar_threshold, pct_threshold = category_thresholds
    else:
        dollar_threshold, pct_threshold = _universal_thresholds(expected_amount)

    if difference < dollar_threshold or pct_change < pct_threshold:
        return None

    score = _outlier_score(difference, pct_change, expected_amount)
    severity = _severity(score)

    return Alert(
        transaction=txn,
        normalized_merchant=normalized_merchant,
        expected_amount=round(expected_amount, 2),
        actual_amount=round(actual, 2),
        difference=round(difference, 2),
        percentage_change=round(pct_change * 100, 1),
        severity=severity,
        outlier_score=round(score, 3),
        possible_reasons=_possible_reasons(pct_change, category, extra_checks),
    )


def _universal_thresholds(expected: float) -> tuple[float, float]:
    for cap, dollar, pct in UNIVERSAL_THRESHOLDS:
        if expected < cap:
            return dollar, pct
    return UNIVERSAL_THRESHOLDS[-1][1], UNIVERSAL_THRESHOLDS[-1][2]


def _outlier_score(difference: float, pct_change: float, expected: float) -> float:
    pct_score = min(1.0, pct_change / 1.0)
    dollar_score = min(1.0, difference / max(expected, 1.0))
    return pct_score * 0.60 + dollar_score * 0.40


def _severity(score: float) -> str:
    for threshold, label in SEVERITY_BANDS:
        if score >= threshold:
            return label
    return "none"


def _possible_reasons(
    pct_change: float,
    category: str,
    extra_checks: list[str] | None,
) -> list[str]:
    reasons = list(_CATEGORY_REASONS.get(category, _UNIVERSAL_REASONS))
    if not reasons:
        reasons = list(_UNIVERSAL_REASONS)
    if pct_change >= 1.0:
        reasons.insert(0, "Possible unauthorized charge")
    if extra_checks:
        for check in extra_checks:
            label = _check_label(check)
            if label and label not in reasons:
                reasons.append(label)
    return reasons


def _check_label(check: str) -> str | None:
    labels = {
        "annual_conversion": "Monthly-to-annual plan conversion",
        "duplicate_charge":  "Possible duplicate charge",
        "roaming":           "International roaming",
        "late_fee":          "Late payment fee",
        "device_installment":"New device installment added",
        "seasonal_spike":    "Seasonal usage increase",
        "annual_renewal":    "Annual renewal",
        "non_subscription_charge": "One-time purchase mixed with subscription",
    }
    return labels.get(check)
