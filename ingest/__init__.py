"""Data ingestion and analysis reporting for recurring-payment-detector."""

from ingest.runner import analyze, AnalysisReport
from ingest.parsers import (
    ParseResult,
    parse_csv,
    parse_json,
    parse_records,
    transactions_to_records,
)
from ingest.email_parser import EmailExtraction, parse_email_text, parse_eml
from ingest.serializers import (
    alerts_to_csv,
    alerts_to_json,
    report_to_json,
    resolutions_to_csv,
)

__all__ = [
    "analyze",
    "AnalysisReport",
    "ParseResult",
    "parse_csv",
    "parse_json",
    "parse_records",
    "EmailExtraction",
    "parse_email_text",
    "parse_eml",
    "transactions_to_records",
    "alerts_to_csv",
    "alerts_to_json",
    "report_to_json",
    "resolutions_to_csv",
]
