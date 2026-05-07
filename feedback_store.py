"""
Phase 4: Persistent feedback store.

Feedback is saved to feedback.json in the working directory.
Each entry records how the user responded to a specific alert.
"""

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from models import Alert, FeedbackEntry

FEEDBACK_FILE = Path(__file__).parent / "feedback.json"

VALID_FEEDBACK = {"expected", "unexpected", "cancel", "remind_later"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record(alert: Alert, category: str, feedback: str, note: str = "") -> FeedbackEntry:
    """Persist one piece of user feedback and return the saved entry."""
    if feedback not in VALID_FEEDBACK:
        raise ValueError(f"feedback must be one of {VALID_FEEDBACK}")

    entry = FeedbackEntry(
        feedback_id=str(uuid.uuid4())[:8],
        merchant=alert.normalized_merchant,
        category=category,
        expected_amount=alert.expected_amount,
        actual_amount=alert.actual_amount,
        feedback=feedback,
        date=alert.transaction.date,
        note=note,
    )
    _append(entry)
    return entry


def load_all() -> list[FeedbackEntry]:
    """Load every saved feedback entry."""
    if not FEEDBACK_FILE.exists():
        return []
    raw = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    return [_deserialize(r) for r in raw]


def load_for_merchant(merchant: str) -> list[FeedbackEntry]:
    return [e for e in load_all() if e.merchant == merchant]


def clear() -> None:
    """Wipe all stored feedback (useful in tests / demos)."""
    if FEEDBACK_FILE.exists():
        FEEDBACK_FILE.unlink()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _append(entry: FeedbackEntry) -> None:
    existing = []
    if FEEDBACK_FILE.exists():
        existing = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    existing.append(_serialize(entry))
    FEEDBACK_FILE.write_text(
        json.dumps(existing, indent=2, default=str),
        encoding="utf-8",
    )


def _serialize(e: FeedbackEntry) -> dict:
    return {
        "feedback_id": e.feedback_id,
        "merchant": e.merchant,
        "category": e.category,
        "expected_amount": e.expected_amount,
        "actual_amount": e.actual_amount,
        "feedback": e.feedback,
        "date": str(e.date),
        "note": e.note,
    }


def _deserialize(d: dict) -> FeedbackEntry:
    return FeedbackEntry(
        feedback_id=d["feedback_id"],
        merchant=d["merchant"],
        category=d["category"],
        expected_amount=d["expected_amount"],
        actual_amount=d["actual_amount"],
        feedback=d["feedback"],
        date=date.fromisoformat(d["date"]),
        note=d.get("note", ""),
    )
