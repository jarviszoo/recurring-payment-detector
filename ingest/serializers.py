"""
Export analysis results to JSON and CSV.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ingest.runner import AnalysisReport


def _alert_rows(report: AnalysisReport) -> list[dict[str, Any]]:
    return [a.to_dict() for a in report.alerts]


def alerts_to_json(report: AnalysisReport, *, indent: int = 2) -> str:
    return json.dumps(_alert_rows(report), indent=indent, default=str)


def alerts_to_csv(report: AnalysisReport) -> str:
    rows = _alert_rows(report)
    if not rows:
        return "severity,merchant,category,expected_amount,actual_amount,difference,pct_change,date,outlier_score,reasons\n"

    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        r = dict(row)
        if isinstance(r.get("possible_reasons"), list):
            r["possible_reasons"] = "; ".join(r["possible_reasons"])
        writer.writerow(r)
    return buf.getvalue()


def resolutions_to_csv(report: AnalysisReport) -> str:
    if not report.resolutions:
        return "raw_merchant,cleaned,canonical_name,category,method,confidence\n"

    fieldnames = list(report.resolutions[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(report.resolutions)
    return buf.getvalue()


def report_to_json(report: AnalysisReport, *, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, default=str)
