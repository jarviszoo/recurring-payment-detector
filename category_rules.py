"""
Per-category detection rules.

Each entry defines:
  thresholds      : (min_dollar_diff, min_pct_change) override for outlier_detector
  lookback_months : how many months of history to compare against
  seasonal        : if True, compare same month prior year in addition to recent
  split_sub_tiers : if True, always split into sub-patterns by amount tier
  notes           : human-readable explanation

Categories not listed here fall through to the universal defaults.
"""

from dataclasses import dataclass, field


@dataclass
class CategoryRule:
    # (min_dollar_diff, min_pct_change) — overrides the tier-based defaults
    thresholds: tuple[float, float] | None = None
    # How many prior charges to use for expected-amount baseline
    lookback: int = 6
    # Compare against same-month-prior-year as an additional reference
    seasonal: bool = False
    # Split into sub-patterns by amount tier (for merchants with many services)
    split_sub_tiers: bool = False
    # Extra flags to include in alert output
    extra_checks: list[str] = field(default_factory=list)


CATEGORY_RULES: dict[str, CategoryRule] = {
    "streaming": CategoryRule(
        thresholds=(3.00, 0.15),  # flag if +$3 and +15%
        lookback=6,
    ),
    "music": CategoryRule(
        thresholds=(2.00, 0.15),
        lookback=6,
    ),
    "software": CategoryRule(
        thresholds=(5.00, 0.10),  # SaaS can change seat counts quickly
        lookback=6,
        extra_checks=["duplicate_charge", "annual_conversion"],
    ),
    "cloud_storage": CategoryRule(
        thresholds=(3.00, 0.15),
        lookback=6,
    ),
    "gaming": CategoryRule(
        thresholds=(3.00, 0.15),
        lookback=6,
    ),
    "news": CategoryRule(
        thresholds=(2.00, 0.20),
        lookback=6,
    ),
    "fitness": CategoryRule(
        thresholds=(5.00, 0.15),
        lookback=6,
    ),
    "telecom": CategoryRule(
        # Bills vary due to taxes, roaming, add-ons — be more tolerant
        thresholds=(15.00, 0.25),
        lookback=3,
        extra_checks=["roaming", "late_fee", "device_installment"],
    ),
    "utilities": CategoryRule(
        # Usage-based — compare seasonally; 6-month lookback captures seasonal range
        thresholds=(20.00, 0.30),
        lookback=6,
        seasonal=True,
        extra_checks=["seasonal_spike"],
    ),
    "insurance": CategoryRule(
        # Premiums change periodically — moderate tolerance
        thresholds=(10.00, 0.15),
        lookback=6,
        extra_checks=["annual_renewal"],
    ),
    "app_store": CategoryRule(
        # One merchant = many subscriptions; always split by amount tier
        thresholds=(3.00, 0.20),
        lookback=6,
        split_sub_tiers=True,
    ),
    "mixed_commerce": CategoryRule(
        # Amazon mixes shopping + subscription; split and be conservative
        thresholds=(5.00, 0.20),
        lookback=6,
        split_sub_tiers=True,
        extra_checks=["non_subscription_charge"],
    ),
    "delivery": CategoryRule(
        thresholds=(5.00, 0.20),
        lookback=4,
        extra_checks=["non_subscription_charge"],
    ),
    "general": CategoryRule(
        thresholds=(5.00, 0.20),
        lookback=6,
    ),
}


def get_rule(category: str) -> CategoryRule:
    return CATEGORY_RULES.get(category, CATEGORY_RULES["general"])
