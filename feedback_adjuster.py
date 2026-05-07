"""
Phase 4: Adjusts alert severity and thresholds based on stored user feedback.

Rules:
  - If the user has previously marked similar alerts for this merchant as
    "expected", raise the effective thresholds (more tolerant).
  - If marked "unexpected" or "cancel", keep or tighten sensitivity.
  - "remind_later" entries are neutral.

The adjuster works by computing a per-merchant tolerance_multiplier and
re-evaluating the outlier score before returning the final alert.
"""

from models import Alert, FeedbackEntry
import feedback_store

# A prior "expected" feedback raises the tolerance multiplier by this step
_EXPECTED_STEP = 0.25
# Cap: never raise threshold more than 3× the original
_MAX_MULTIPLIER = 3.0
# An "unexpected" feedback pushes sensitivity back toward 1.0
_UNEXPECTED_STEP = 0.15

SEVERITY_BANDS = [
    (0.85, "high"),
    (0.65, "warning"),
    (0.40, "low"),
]


def adjust(alert: Alert) -> Alert:
    """
    Re-score the alert given stored feedback for this merchant.
    Returns the same alert object (possibly with lower outlier_score / severity).
    """
    entries = feedback_store.load_for_merchant(alert.normalized_merchant)
    if not entries:
        return alert

    multiplier = _compute_multiplier(entries)
    if multiplier <= 1.0:
        return alert

    # Scale thresholds up: divide the outlier score by the multiplier
    adjusted_score = alert.outlier_score / multiplier
    new_severity = _severity(adjusted_score)

    alert.outlier_score = round(adjusted_score, 3)
    alert.severity = new_severity
    alert.feedback_adjusted = True
    return alert


def tolerance_multiplier(merchant: str) -> float:
    entries = feedback_store.load_for_merchant(merchant)
    return _compute_multiplier(entries)


# ---------------------------------------------------------------------------

def _compute_multiplier(entries: list[FeedbackEntry]) -> float:
    multiplier = 1.0
    for e in entries:
        if e.feedback == "expected":
            multiplier = min(multiplier + _EXPECTED_STEP, _MAX_MULTIPLIER)
        elif e.feedback in ("unexpected", "cancel"):
            multiplier = max(multiplier - _UNEXPECTED_STEP, 1.0)
    return round(multiplier, 3)


def _severity(score: float) -> str:
    for threshold, label in SEVERITY_BANDS:
        if score >= threshold:
            return label
    return "none"
