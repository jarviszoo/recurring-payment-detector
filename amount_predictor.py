from models import RecurringPattern


def predict_expected_amount(pattern: RecurringPattern, lookback: int = 6) -> float:
    """
    Return the expected amount for the next charge in this pattern.
    Uses the median of the most recent `lookback` charges.
    Median is more robust than mean against one-off anomalies.
    """
    recent = sorted(pattern.transactions, key=lambda t: t.date)[-lookback:]
    amounts = [t.amount for t in recent]
    return _median(amounts)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
