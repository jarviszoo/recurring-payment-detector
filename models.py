from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Transaction:
    transaction_id: str
    merchant_raw: str
    amount: float
    date: date
    currency: str = "USD"
    category_mcc: Optional[str] = None
    payment_method: Optional[str] = None
    description: Optional[str] = None


@dataclass
class RecurringPattern:
    normalized_merchant: str
    transactions: list
    billing_cycle_days: int
    confidence_score: float


@dataclass
class PredictionResult:
    expected: float
    lower_bound: float
    upper_bound: float
    confidence: float        # 0–1: how certain the model is
    method: str              # "ml" | "median"


@dataclass
class Alert:
    transaction: Transaction
    normalized_merchant: str
    expected_amount: float
    actual_amount: float
    difference: float
    percentage_change: float
    severity: str            # "low" | "warning" | "high"
    outlier_score: float
    possible_reasons: list = field(default_factory=list)
    prediction: Optional[PredictionResult] = None
    feedback_adjusted: bool = False


@dataclass
class FeedbackEntry:
    feedback_id: str
    merchant: str
    category: str
    expected_amount: float
    actual_amount: float
    feedback: str            # "expected" | "unexpected" | "cancel" | "remind_later"
    date: date
    note: str = ""
