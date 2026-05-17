"""
Run the full detection pipeline on ingested transactions and build a structured report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from category_classifier import classify
from models import Alert, Transaction
from pipeline import format_alert, resolve_all, run
from merchant_normalizer import SEED_SERVICES

import entity_resolver
import feedback_store
import service_registry


@dataclass
class AlertRecord:
    severity: str
    merchant: str
    category: str
    expected_amount: float
    actual_amount: float
    difference: float
    percentage_change: float
    charge_date: str
    outlier_score: float
    possible_reasons: list[str]
    prediction_method: str | None
    prediction_confidence: float | None
    ci_lower: float | None
    ci_upper: float | None
    feedback_adjusted: bool
    raw_merchant: str
    transaction_id: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "merchant": self.merchant,
            "category": self.category,
            "expected_amount": self.expected_amount,
            "actual_amount": self.actual_amount,
            "difference": self.difference,
            "percentage_change": self.percentage_change,
            "date": self.charge_date,
            "outlier_score": self.outlier_score,
            "possible_reasons": self.possible_reasons,
            "prediction_method": self.prediction_method,
            "prediction_confidence": self.prediction_confidence,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "feedback_adjusted": self.feedback_adjusted,
            "raw_merchant": self.raw_merchant,
            "transaction_id": self.transaction_id,
        }


@dataclass
class AnalysisReport:
    transaction_count: int
    alert_count: int
    service_count: int
    alerts: list[AlertRecord] = field(default_factory=list)
    resolutions: list[dict] = field(default_factory=list)
    summary_by_severity: dict[str, int] = field(default_factory=dict)
    formatted_alerts: list[str] = field(default_factory=list)
    run_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    use_ml: bool = True

    def to_dict(self) -> dict:
        return {
            "run_at": self.run_at,
            "use_ml": self.use_ml,
            "transaction_count": self.transaction_count,
            "alert_count": self.alert_count,
            "service_count": self.service_count,
            "summary_by_severity": self.summary_by_severity,
            "alerts": [a.to_dict() for a in self.alerts],
            "resolutions": self.resolutions,
            "formatted_alerts": self.formatted_alerts,
        }


def _category_for(txn: Transaction) -> str:
    res = entity_resolver.resolve(txn.merchant_raw, txn_date=txn.date, mcc=txn.category_mcc, auto_create=False)
    if res.category:
        return res.category
    return classify(txn.merchant_raw, mcc=txn.category_mcc)


def _alert_to_record(alert: Alert, category: str) -> AlertRecord:
    p = alert.prediction
    return AlertRecord(
        severity=alert.severity,
        merchant=alert.normalized_merchant,
        category=category,
        expected_amount=alert.expected_amount,
        actual_amount=alert.actual_amount,
        difference=alert.difference,
        percentage_change=alert.percentage_change,
        charge_date=str(alert.transaction.date),
        outlier_score=alert.outlier_score,
        possible_reasons=list(alert.possible_reasons),
        prediction_method=p.method if p else None,
        prediction_confidence=round(p.confidence, 3) if p else None,
        ci_lower=round(p.lower_bound, 2) if p else None,
        ci_upper=round(p.upper_bound, 2) if p else None,
        feedback_adjusted=alert.feedback_adjusted,
        raw_merchant=alert.transaction.merchant_raw,
        transaction_id=alert.transaction.transaction_id,
    )


def analyze(
    transactions: list[Transaction],
    *,
    use_ml: bool = True,
    reset_registry: bool = False,
    reset_feedback: bool = False,
    seed_registry: bool = True,
) -> AnalysisReport:
    """
    Bootstrap registry (optional), resolve merchants, run detection, return structured output.
    """
    if reset_registry:
        service_registry.clear()
    if reset_feedback:
        feedback_store.clear()

    if seed_registry and len(service_registry.all_services()) == 0:
        service_registry.bootstrap_seed(SEED_SERVICES)

    # Dedupe by transaction_id (keep last)
    seen: dict[str, Transaction] = {}
    for t in sorted(transactions, key=lambda x: x.date):
        seen[t.transaction_id] = t
    txns = list(seen.values())

    resolutions_raw = resolve_all(txns)
    unique_res: dict[str, dict] = {}
    for txn, res in zip(txns, resolutions_raw):
        if txn.merchant_raw in unique_res:
            continue
        unique_res[txn.merchant_raw] = {
            "raw_merchant": res.raw,
            "cleaned": res.cleaned,
            "canonical_name": res.canonical_name,
            "category": res.category,
            "method": res.method,
            "confidence": res.confidence,
        }

    alerts = run(txns, use_ml=use_ml)

    alert_records: list[AlertRecord] = []
    formatted: list[str] = []
    severity_counts: dict[str, int] = {"high": 0, "warning": 0, "low": 0}

    for alert in alerts:
        cat = _category_for(alert.transaction)
        alert_records.append(_alert_to_record(alert, cat))
        formatted.append(format_alert(alert, category=cat))
        severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1

    return AnalysisReport(
        transaction_count=len(txns),
        alert_count=len(alert_records),
        service_count=len(service_registry.all_services()),
        alerts=alert_records,
        resolutions=sorted(unique_res.values(), key=lambda r: r["raw_merchant"]),
        summary_by_severity=severity_counts,
        formatted_alerts=formatted,
        use_ml=use_ml,
    )
