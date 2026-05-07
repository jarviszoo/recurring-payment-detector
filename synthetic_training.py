"""
Generates synthetic recurring-payment training examples for the ML predictor.

Each example is (feature_vector, next_amount).  Covers:
  - Stable subscriptions (most common)
  - Gradual price creep
  - Sudden plan upgrades
  - Annual-to-monthly and monthly-to-annual conversions
  - Telecom / utility variance
  - Promotional discount expiry
"""

import numpy as np
from feature_extractor import extract, CATEGORIES, BILLING_CYCLES


_RNG = np.random.default_rng(42)


def generate(n: int = 2000) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, y) where X.shape == (n, 14) and y.shape == (n,)."""
    X_rows, y_vals = [], []

    generators = [
        (_stable,              0.40),
        (_gradual_creep,       0.15),
        (_plan_upgrade,        0.15),
        (_discount_expiry,     0.10),
        (_annual_conversion,   0.05),
        (_telecom_variance,    0.08),
        (_utility_seasonal,    0.07),
    ]

    counts = [int(n * w) for _, w in generators]
    counts[-1] += n - sum(counts)  # absorb rounding remainder

    for (fn, _), count in zip(generators, counts):
        for _ in range(count):
            amounts, cycle, category, next_amt = fn()
            days = cycle + _RNG.integers(-3, 4)
            feat = extract(amounts, cycle, category, int(days))
            X_rows.append(feat)
            y_vals.append(next_amt)

    X = np.array(X_rows, dtype=float)
    y = np.array(y_vals, dtype=float)
    idx = _RNG.permutation(len(y))
    return X[idx], y[idx]


# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------

def _base_amount() -> float:
    return float(_RNG.choice([
        2.99, 4.99, 5.99, 6.99, 7.99, 9.99, 10.99, 11.99, 12.99,
        14.99, 15.49, 17.99, 19.99, 24.99, 29.99, 34.99, 39.99,
        49.99, 59.99, 79.99, 99.99, 119.99, 149.99, 199.99,
    ]))


def _jitter(amount: float, pct: float = 0.02) -> float:
    """Tiny realistic noise (tax, rounding)."""
    return round(amount * (1 + _RNG.uniform(-pct, pct)), 2)


def _stable():
    base = _base_amount()
    cycle = int(_RNG.choice(BILLING_CYCLES))
    category = str(_RNG.choice(CATEGORIES))
    n = int(_RNG.integers(3, 13))
    amounts = [_jitter(base, 0.015) for _ in range(n)]
    return amounts, cycle, category, _jitter(base, 0.015)


def _gradual_creep():
    base = _base_amount()
    cycle = int(_RNG.choice([30, 91, 365]))
    category = str(_RNG.choice(["streaming", "software", "music", "news"]))
    n = int(_RNG.integers(4, 13))
    monthly_increase = _RNG.uniform(0.002, 0.008)
    amounts = [round(base * (1 + monthly_increase * i) + _RNG.uniform(-0.05, 0.05), 2)
               for i in range(n)]
    next_amt = round(amounts[-1] * (1 + monthly_increase), 2)
    return amounts, cycle, category, next_amt


def _plan_upgrade():
    base = _base_amount()
    upgrade_factor = float(_RNG.choice([1.5, 2.0, 2.5, 3.0, 4.0]))
    cycle = 30
    category = str(_RNG.choice(["software", "streaming", "gaming"]))
    n_before = int(_RNG.integers(2, 7))
    amounts = [_jitter(base) for _ in range(n_before)]
    # one upgraded charge already in history
    upgraded = round(base * upgrade_factor, 2)
    amounts.append(upgraded)
    return amounts, cycle, category, _jitter(upgraded, 0.01)


def _discount_expiry():
    discounted = _base_amount() * float(_RNG.uniform(0.5, 0.8))
    discounted = round(discounted, 2)
    full_price = round(discounted / _RNG.uniform(0.5, 0.8), 2)
    cycle = 30
    category = str(_RNG.choice(["streaming", "music", "software", "fitness"]))
    n_discounted = int(_RNG.integers(2, 7))
    amounts = [_jitter(discounted) for _ in range(n_discounted)]
    return amounts, cycle, category, _jitter(full_price, 0.01)


def _annual_conversion():
    monthly = _base_amount()
    annual = round(monthly * float(_RNG.uniform(9.0, 11.5)), 2)
    cycle = 365
    category = str(_RNG.choice(["software", "streaming", "fitness"]))
    n_monthly = int(_RNG.integers(2, 6))
    amounts = [_jitter(monthly) for _ in range(n_monthly)]
    return amounts, cycle, category, annual


def _telecom_variance():
    base = float(_RNG.uniform(40, 180))
    cycle = 30
    category = "telecom"
    n = int(_RNG.integers(3, 10))
    amounts = [round(base * (1 + _RNG.uniform(-0.08, 0.08)), 2) for _ in range(n)]
    next_amt = round(base * (1 + _RNG.uniform(-0.08, 0.08)), 2)
    return amounts, cycle, category, next_amt


def _utility_seasonal():
    summer_base = float(_RNG.uniform(60, 120))
    winter_mult = float(_RNG.uniform(1.5, 2.5))
    cycle = 30
    category = "utilities"
    month_idx = int(_RNG.integers(0, 12))
    n = int(_RNG.integers(3, 10))
    amounts = []
    for i in range(n):
        m = (month_idx + i) % 12
        mult = winter_mult if m in (11, 0, 1, 2) else (1.1 if m in (3, 10) else 1.0)
        amounts.append(round(summer_base * mult * (1 + _RNG.uniform(-0.04, 0.04)), 2))
    m_next = (month_idx + n) % 12
    mult_next = winter_mult if m_next in (11, 0, 1, 2) else (1.1 if m_next in (3, 10) else 1.0)
    next_amt = round(summer_base * mult_next * (1 + _RNG.uniform(-0.04, 0.04)), 2)
    return amounts, cycle, category, next_amt
