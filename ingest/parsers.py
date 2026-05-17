"""
Parse uploaded CSV/JSON and in-memory records into Transaction objects.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from models import Transaction

# Maps normalized header names -> internal field
_FIELD_ALIASES: dict[str, str] = {
    "transaction_id": "transaction_id",
    "id": "transaction_id",
    "txn_id": "transaction_id",
    "merchant_raw": "merchant_raw",
    "merchant": "merchant_raw",
    "description": "merchant_raw",
    "payee": "merchant_raw",
    "name": "merchant_raw",
    "amount": "amount",
    "value": "amount",
    "charge": "amount",
    "date": "date",
    "txn_date": "date",
    "transaction_date": "date",
    "posted_date": "date",
    "category_mcc": "category_mcc",
    "mcc": "category_mcc",
    "currency": "currency",
    "payment_method": "payment_method",
    "note": "description",
    "memo": "description",
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%Y%m%d",
)


@dataclass
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_rows: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.transactions) and not self.errors


def _normalize_header(h: str) -> str:
    key = re.sub(r"[\s\-]+", "_", h.strip().lower())
    return _FIELD_ALIASES.get(key, key)


def _parse_date(raw: str) -> date:
    text = str(raw).strip()
    if not text:
        raise ValueError("empty date")
    if "T" in text:
        text = text.split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _parse_amount(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "").replace("$", "")
    if not text:
        raise ValueError("empty amount")
    return float(text)


def _row_to_transaction(row: dict[str, Any], line_no: int) -> Transaction:
    mapped: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        norm = _normalize_header(str(key))
        if norm in _FIELD_ALIASES.values():
            mapped[norm] = value

    merchant = str(mapped.get("merchant_raw", "")).strip()
    if not merchant:
        raise ValueError("missing merchant (merchant_raw / merchant / description)")

    amount = _parse_amount(mapped.get("amount"))
    txn_date = _parse_date(mapped.get("date"))

    txn_id = str(mapped.get("transaction_id") or "").strip()
    if not txn_id:
        txn_id = f"ingest-{uuid.uuid4().hex[:8]}"

    mcc = mapped.get("category_mcc")
    category_mcc = str(mcc).strip() if mcc not in (None, "") else None

    currency = str(mapped.get("currency") or "USD").strip() or "USD"
    payment_method = mapped.get("payment_method")
    description = mapped.get("description")

    return Transaction(
        transaction_id=txn_id,
        merchant_raw=merchant,
        amount=amount,
        date=txn_date,
        currency=currency,
        category_mcc=category_mcc,
        payment_method=str(payment_method).strip() if payment_method else None,
        description=str(description).strip() if description else None,
    )


def parse_records(records: list[dict[str, Any]]) -> ParseResult:
    result = ParseResult()
    for i, row in enumerate(records, start=1):
        try:
            result.transactions.append(_row_to_transaction(row, i))
        except (ValueError, TypeError) as e:
            result.errors.append(f"Row {i}: {e}")
            result.skipped_rows += 1
    if not result.transactions and not result.errors:
        result.errors.append("No valid rows found.")
    return result


def parse_csv(
    content: str | bytes,
    *,
    delimiter: str | None = None,
) -> ParseResult:
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content

    if not text.strip():
        return ParseResult(errors=["CSV file is empty."])

    sample = text[:4096]
    delim = delimiter or ("," if sample.count(",") >= sample.count(";") else ";")

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        return ParseResult(errors=["CSV has no header row."])

    return parse_records(list(reader))


def parse_json(content: str | bytes) -> ParseResult:
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return ParseResult(errors=[f"Invalid JSON: {e}"])

    if isinstance(data, dict):
        if "transactions" in data:
            records = data["transactions"]
        elif "data" in data:
            records = data["data"]
        else:
            return ParseResult(errors=["JSON object must contain a 'transactions' array."])
    elif isinstance(data, list):
        records = data
    else:
        return ParseResult(errors=["JSON must be an array of transactions or an object with 'transactions'."])

    if not isinstance(records, list):
        return ParseResult(errors=["'transactions' must be an array."])

    return parse_records(records)


def transactions_to_records(transactions: list[Transaction]) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": t.transaction_id,
            "merchant_raw": t.merchant_raw,
            "amount": t.amount,
            "date": t.date.isoformat(),
            "currency": t.currency,
            "category_mcc": t.category_mcc,
            "payment_method": t.payment_method,
            "description": t.description,
        }
        for t in transactions
    ]
