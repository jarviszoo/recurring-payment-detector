"""
Email parser — extracts structured signals from raw email text.

The goal is not to perfectly parse every email format, but to surface enough
candidate signals (merchant name, amount, date, billing cycle) that the
downstream entity_resolver + price_lookup can do their work.

We don't run NLP/LLM here — pure regex + heuristics, so it stays cheap and
deterministic. The resolver handles the noisy merchant string anyway.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class ParsedEmail:
    raw_text: str
    sender: Optional[str] = None
    subject: Optional[str] = None
    merchant_candidates: list[str] = field(default_factory=list)
    amount: Optional[float] = None
    currency: str = "USD"
    charge_date: Optional[date] = None
    billing_cycle: Optional[str] = None       # "monthly" | "annual" | "weekly" | "quarterly"
    plan_tier: Optional[str] = None            # if mentioned: "Premium", "Family", etc.
    raw_amounts: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(email_text: str) -> ParsedEmail:
    """Extract structured fields from a raw email body (with optional headers)."""
    text = email_text.replace("\r", "")
    result = ParsedEmail(raw_text=text)

    headers, body = _split_headers(text)
    result.sender = _extract_sender(headers)
    result.subject = _extract_subject(headers)

    result.amount, result.currency, result.raw_amounts = _extract_amount(text)
    result.charge_date = _extract_date(text)
    result.billing_cycle = _extract_billing_cycle(text)
    result.plan_tier = _extract_plan_tier(text)
    result.merchant_candidates = _extract_merchants(result.sender, result.subject, text)

    return result


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

_HEADER_FIELDS = ("from", "to", "subject", "date", "sender", "reply-to")


def _split_headers(text: str) -> tuple[dict[str, str], str]:
    headers: dict[str, str] = {}
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            body_start = i + 1
            break
        m = re.match(r"^([A-Za-z\-]+):\s*(.*)$", line)
        if m and m.group(1).lower() in _HEADER_FIELDS:
            headers[m.group(1).lower()] = m.group(2).strip()
        else:
            # No more headers
            body_start = i
            break
    body = "\n".join(lines[body_start:])
    return headers, body


def _extract_sender(headers: dict) -> Optional[str]:
    return headers.get("from") or headers.get("sender")


def _extract_subject(headers: dict) -> Optional[str]:
    return headers.get("subject")


# ---------------------------------------------------------------------------
# Amount extraction
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {
    "$": "USD", "USD": "USD",
    "€": "EUR", "EUR": "EUR",
    "£": "GBP", "GBP": "GBP",
    "¥": "JPY", "JPY": "JPY",
}

# Matches "$15.49", "USD 15.49", "15.49 USD", "€10.99"
_AMOUNT_PATTERNS = [
    re.compile(r"(?:USD|EUR|GBP|JPY)\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"([\d,]+\.\d{2})\s*(?:USD|EUR|GBP|JPY)", re.IGNORECASE),
    re.compile(r"[\$€£¥]\s*([\d,]+\.\d{2})"),
]

# Keywords near the amount we want — used to disambiguate when multiple amounts appear
_AMOUNT_KEYWORDS = re.compile(
    r"(total|amount|charged|billed|paid|payment|subscription|charge)\s*[:\-]?\s*",
    re.IGNORECASE,
)


def _extract_amount(text: str) -> tuple[Optional[float], str, list[float]]:
    """Return (best_amount, currency, all_amounts_found)."""
    all_matches: list[tuple[float, str, int]] = []  # (value, currency, pos)
    for pat in _AMOUNT_PATTERNS:
        for m in pat.finditer(text):
            try:
                val = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            cur = _detect_currency(m.group(0))
            all_matches.append((val, cur, m.start()))

    if not all_matches:
        return None, "USD", []

    # Prefer amounts that follow keywords like "Total: $X"
    best = None
    for val, cur, pos in all_matches:
        window = text[max(0, pos - 40):pos]
        if _AMOUNT_KEYWORDS.search(window):
            if best is None or val > best[0]:
                best = (val, cur)

    if best is None:
        # No keyword nearby — fall back to the largest amount
        val, cur, _ = max(all_matches, key=lambda x: x[0])
        best = (val, cur)

    return best[0], best[1], [v for v, _, _ in all_matches]


def _detect_currency(snippet: str) -> str:
    upper = snippet.upper()
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in upper or symbol in snippet:
            return code
    return "USD"


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    # "March 14, 2026" / "Mar 14, 2026"
    (re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE),
     "%b %d %Y"),
    # "2026-03-14"
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y-%m-%d"),
    # "03/14/2026"
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "%m/%d/%Y"),
    # "14 Mar 2026"
    (re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b", re.IGNORECASE),
     "%d %b %Y"),
]


def _extract_date(text: str) -> Optional[date]:
    for pat, fmt in _DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        raw = m.group(0).replace(",", "")
        # Normalise month name to title case so strptime accepts it
        raw = re.sub(r"\b([A-Z][a-z]*)\b", lambda mm: mm.group(0)[:3].title(), raw)
        for try_fmt in (fmt, fmt.replace("%b", "%B")):
            try:
                return datetime.strptime(raw, try_fmt).date()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Billing cycle + plan tier
# ---------------------------------------------------------------------------

_CYCLE_KEYWORDS = [
    (re.compile(r"\b(year|annual|yearly)\b|/yr\b", re.IGNORECASE), "annual"),
    (re.compile(r"\b(month|monthly)\b|/mo\b", re.IGNORECASE),       "monthly"),
    (re.compile(r"\bquarterly\b|/qtr\b", re.IGNORECASE),            "quarterly"),
    (re.compile(r"\bweekly\b|/wk\b", re.IGNORECASE),                "weekly"),
]

_PLAN_KEYWORDS = re.compile(
    r"\b(Premium|Standard|Basic|Pro|Plus|Family|Individual|Duo|"
    r"Personal|Business|Team|Enterprise|Starter|Free|Unlimited|"
    r"Student|Annual|Monthly)\b",
    re.IGNORECASE,
)


def _extract_billing_cycle(text: str) -> Optional[str]:
    for pat, cycle in _CYCLE_KEYWORDS:
        if pat.search(text):
            return cycle
    return None


def _extract_plan_tier(text: str) -> Optional[str]:
    m = _PLAN_KEYWORDS.search(text)
    return m.group(1).title() if m else None


# ---------------------------------------------------------------------------
# Merchant extraction
# ---------------------------------------------------------------------------

_DOMAIN_SUFFIXES = {"com", "net", "org", "co", "io", "app", "tv"}


def _extract_merchants(
    sender: Optional[str],
    subject: Optional[str],
    body: str,
) -> list[str]:
    """
    Surface candidate merchant strings.  The resolver does the heavy lifting;
    we just want to give it good candidates to score.
    """
    cands: list[str] = []

    # 1. Sender domain (strongest signal)
    if sender:
        for dom in re.findall(r"@([A-Za-z0-9.\-]+)", sender):
            parts = dom.split(".")
            if len(parts) >= 2:
                core = parts[-2]
                if core.lower() not in {"mail", "email", "no-reply", "noreply", "smtp"}:
                    cands.append(core)
        # Also try the display name
        m = re.match(r'^\s*"?([^"<@]+?)"?\s*<', sender)
        if m:
            cands.append(m.group(1).strip())

    # 2. Subject line — pull noun-phrasey tokens
    if subject:
        cands.append(subject)
        # Common patterns: "Your X invoice", "X subscription", "Receipt from X"
        for pat in (
            r"(?:your|from)\s+([A-Z][\w\.\-]+(?:\s+[A-Z][\w\.\-]+)?)",
            r"([A-Z][\w\.\-]+(?:\s+[A-Z][\w\.\-]+)?)\s+(?:invoice|receipt|subscription|payment)",
        ):
            for m in re.finditer(pat, subject, re.IGNORECASE):
                cands.append(m.group(1))

    # 3. Body — phrases like "Thank you for subscribing to X" / "Your X invoice"
    body_patterns = [
        r"thank(?:s)? (?:you )?for (?:subscribing to|your (?:purchase|order|subscription) (?:to|of)?)\s+([A-Z][\w\.\-\+]+(?:\s+[A-Z][\w\.\-\+]+)?)",
        r"your\s+([A-Z][\w\.\-\+]+(?:\s+[A-Z][\w\.\-\+]+)?)\s+(?:account|subscription|membership|plan)",
        r"(?:from|by)\s+([A-Z][\w\.\-\+]+(?:\s+[A-Z][\w\.\-\+]+)?)\b",
    ]
    for pat in body_patterns:
        for m in re.finditer(pat, body, re.IGNORECASE):
            cand = m.group(1).strip()
            if cand and len(cand) >= 3:
                cands.append(cand)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for c in cands:
        norm = c.strip().lower()
        if norm and norm not in seen and len(norm) >= 2:
            seen.add(norm)
            deduped.append(c.strip())
    return deduped[:8]
