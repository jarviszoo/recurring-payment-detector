"""
Extracts ML-ready feature vectors from a list of historical transaction amounts.
All features are numeric so they work with any sklearn estimator.
"""

import numpy as np
from datetime import date

CATEGORIES = [
    "streaming", "music", "software", "cloud_storage", "gaming",
    "news", "fitness", "telecom", "utilities", "insurance",
    "app_store", "mixed_commerce", "delivery", "general",
]
_CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}

BILLING_CYCLES = [7, 14, 30, 91, 365]
_CYCLE_INDEX = {c: i for i, c in enumerate(BILLING_CYCLES)}


def extract(
    amounts: list[float],
    billing_cycle_days: int,
    category: str,
    days_since_last: int = 30,
) -> np.ndarray:
    """
    Return a 1-D feature vector for predicting the next charge amount.

    Features (14 total):
      0  last_amount
      1  second_last_amount
      2  median_amount
      3  mean_amount
      4  std_amount
      5  cv_amount              (std / median, clamped)
      6  last_delta_pct         (last - second_last) / second_last
      7  trend_slope_normalized (linear slope over last 6, divided by median)
      8  n_obs                  (capped at 12)
      9  billing_cycle_idx      (0–4 for weekly/biweekly/monthly/quarterly/annual)
      10 category_idx           (0–13)
      11 days_since_last        (capped at 400)
      12 max_amount
      13 min_amount
    """
    n = len(amounts)
    if n == 0:
        return np.zeros(14)

    arr = np.array(amounts, dtype=float)
    last = arr[-1]
    second_last = arr[-2] if n >= 2 else last
    med = float(np.median(arr))
    mean = float(np.mean(arr))
    std = float(np.std(arr)) if n > 1 else 0.0
    cv = std / med if med > 0 else 0.0
    cv = min(cv, 5.0)

    last_delta = (last - second_last) / second_last if second_last > 0 else 0.0

    window = arr[-6:] if n >= 3 else arr
    if len(window) >= 2:
        xs = np.arange(len(window), dtype=float)
        slope = float(np.polyfit(xs, window, 1)[0])
        slope_norm = slope / med if med > 0 else 0.0
    else:
        slope_norm = 0.0

    cycle_idx = _CYCLE_INDEX.get(
        min(BILLING_CYCLES, key=lambda c: abs(c - billing_cycle_days)), 0
    )
    cat_idx = _CAT_INDEX.get(category, _CAT_INDEX["general"])
    n_obs = min(n, 12)
    days_cap = min(days_since_last, 400)

    return np.array([
        last,
        second_last,
        med,
        mean,
        std,
        cv,
        last_delta,
        slope_norm,
        n_obs,
        cycle_idx,
        cat_idx,
        days_cap,
        float(np.max(arr)),
        float(np.min(arr)),
    ], dtype=float)
