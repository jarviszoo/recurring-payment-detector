"""
Heuristic extraction of charge hints from receipt and billing emails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from ingest.parsers import ParseResult, parse_records
from merchant_normalizer import SEED_SERVICES, clean as clean_merchant


_MONEY_RE = re.compile(
    r"(?P<prefix>\$|US\$|USD|CAD|AUD|EUR|GBP)?\s*"
    r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})"
    r"\s*(?P<suffix>USD|CAD|AUD|EUR|GBP)?",
    re.IGNORECASE,
)

_SUBJECT_MERCHANT_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (
        re.compile(
            r"\b(?:receipt|invoice|bill|billing|payment|subscription|renewal|order)"
            r"\s+(?:from|for|with)\s+(.+?)(?:\s*[-|:]|\s*$)",
            re.IGNORECASE,
        ),
        0.95,
    ),
    (
        re.compile(r"\b(?:you paid|payment to|paid to)\s+(.+?)(?:\s*[-|:]|\s*$)", re.IGNORECASE),
        0.95,
    ),
    (
        re.compile(
            r"\b(?:your|a|an)\s+(.+?)\s+"
            r"(?:receipt|invoice|subscription|membership|renewal|payment|bill)\b",
            re.IGNORECASE,
        ),
        0.72,
    ),
    (
        re.compile(
            r"^(.+?)\s+(?:receipt|invoice|subscription|membership|renewal|payment|bill)\b",
            re.IGNORECASE,
        ),
        0.70,
    ),
)

_BODY_MERCHANT_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (
        re.compile(
            r"\b(?:merchant|vendor|seller|store|biller|paid to|payment to|billed by|sold by)"
            r"\s*[:\-]\s*(.+)",
            re.IGNORECASE,
        ),
        0.97,
    ),
    (
        re.compile(r"\b(?:receipt|invoice|order)\s+(?:from|for)\s+(.+)", re.IGNORECASE),
        0.92,
    ),
    (
        re.compile(r"\b(?:you paid|paid to)\s+(.+?)(?:\s+[$]|$)", re.IGNORECASE),
        0.88,
    ),
)

_AMOUNT_GOOD_LABELS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\b(?:amount paid|total paid|paid today|payment amount|amount charged)\b", re.IGNORECASE), 6.0),
    (re.compile(r"\b(?:total charged|charged today|you were charged|charged)\b", re.IGNORECASE), 5.7),
    (re.compile(r"\b(?:grand total|order total|invoice total|receipt total|total due|total)\b", re.IGNORECASE), 5.2),
    (re.compile(r"\b(?:subscription|membership|plan|renewal|monthly|annual|billed|billing)\b", re.IGNORECASE), 2.0),
    (re.compile(r"\b(?:amount|payment|paid)\b", re.IGNORECASE), 1.8),
)

_AMOUNT_BAD_LABELS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\b(?:subtotal|sub total|tax|vat|tip|fee|fees|shipping|handling)\b", re.IGNORECASE), -4.5),
    (re.compile(r"\b(?:discount|promo|promotion|coupon|credit|cashback|savings|refunded|refund)\b", re.IGNORECASE), -6.0),
    (re.compile(r"\b(?:previous balance|remaining balance|minimum payment|available balance)\b", re.IGNORECASE), -5.0),
    (re.compile(r"\b(?:ending in|card|visa|mastercard|amex|discover)\b", re.IGNORECASE), -1.0),
)

_DATE_LINE_RE = re.compile(
    r"\b(?:transaction|charge|billing|payment|paid|invoice|order|purchase|renewal|upgrade)"
    r"\s+date\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b")
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/20\d{2})\b")
_MONTH_DATE_RE = re.compile(
    r"\b("
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
    r"\s+\d{1,2},?\s+20\d{2}"
    r")\b",
    re.IGNORECASE,
)

_MERCHANT_SPLIT_RE = re.compile(r"\s+(?:[-|:]|\u2013|\u2014)\s+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_GENERIC_MERCHANT_WORDS = {
    "app",
    "receipt",
    "invoice",
    "billing",
    "bill",
    "payment",
    "payments",
    "subscription",
    "renewal",
    "order",
    "confirmation",
    "support",
    "customer support",
    "sales",
    "hello",
    "hi",
    "team",
    "noreply",
    "no reply",
    "no-reply",
    "donotreply",
    "do not reply",
    "notifications",
    "notification",
    "mailer",
    "mail",
    "account",
    "accounts",
    "plan",
    "product",
    "service",
}
_GENERIC_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "yahoo.com",
    "aol.com",
    "mailgun.net",
    "sendgrid.net",
    "amazonses.com",
    "mandrillapp.com",
    "postmarkapp.com",
    "sparkpostmail.com",
}
_PROCESSOR_DOMAINS = {"stripe.com", "paypal.com", "squareup.com", "square.com"}
_BODY_LABEL_SCORES = {
    "merchant": 0.98,
    "vendor": 0.98,
    "seller": 0.97,
    "store": 0.94,
    "biller": 0.94,
    "app": 0.96,
    "service": 0.96,
    "subscription": 0.94,
    "product": 0.92,
    "plan": 0.84,
}
_GENERIC_TITLE_WORDS = {
    "confirmation",
    "subscription confirmation",
    "receipt",
    "invoice",
    "order confirmation",
    "purchase confirmation",
}
_DATE_LABELS = {
    "date",
    "date of upgrade",
    "purchase date",
    "transaction date",
    "billing date",
    "payment date",
    "renewal date",
}


@dataclass
class EmailExtraction:
    merchant_raw: str
    amount: float | None
    date: date | None
    subject: str
    source: str  # "eml" | "text"
    merchant_source: str = ""
    amount_source: str = ""
    action_links: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _MerchantCandidate:
    value: str
    score: float
    source: str


@dataclass
class _AmountCandidate:
    amount: float
    score: float
    context: str


class _HTMLTextExtractor(HTMLParser):
    """Tiny HTML-to-text helper that keeps receipt table cells separated."""

    _BLOCK_TAGS = {
        "address",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        text = unescape(" ".join(self._chunks))
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


class _HTMLActionLinkExtractor(HTMLParser):
    _LINK_KEYWORDS = (
        "account",
        "billing",
        "cancel",
        "manage",
        "membership",
        "purchase",
        "subscription",
    )

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href.strip()
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None and data.strip():
            self._text_parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        label = re.sub(r"\s+", " ", " ".join(self._text_parts)).strip()
        haystack = f"{label} {self._href}".lower()
        if any(k in haystack for k in self._LINK_KEYWORDS):
            self.links.append({"label": label or self._href, "url": self._href})
        self._href = None
        self._text_parts = []


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.text()


def _decode_part(part: Any) -> str:
    try:
        content = part.get_content()
        return content if isinstance(content, str) else str(content)
    except Exception:
        payload = part.get_payload(decode=True)
        if payload is None:
            raw = part.get_payload()
            return raw if isinstance(raw, str) else ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")


def _extract_bodies(msg: Any) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            plain_parts.append(_decode_part(part))
        elif ctype == "text/html":
            html_parts.append(_html_to_text(_decode_part(part)))

    plain = "\n".join(p for p in plain_parts if p.strip())
    html = "\n".join(p for p in html_parts if p.strip())
    return plain, html


def _extract_action_links(msg: Any) -> list[dict[str, str]]:
    seen: set[str] = set()
    links: list[dict[str, str]] = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() != "text/html":
            continue
        parser = _HTMLActionLinkExtractor()
        parser.feed(_decode_part(part))
        for link in parser.links:
            url = link["url"]
            if url in seen:
                continue
            seen.add(url)
            links.append(link)
    return links[:8]


def _line_window(text: str, start: int, end: int) -> str:
    left = text.rfind("\n", 0, start)
    right = text.find("\n", end)
    if left == -1:
        left = max(0, start - 80)
    if right == -1:
        right = min(len(text), end + 80)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _amount_candidates(text: str) -> list[_AmountCandidate]:
    candidates: list[_AmountCandidate] = []
    matches = list(_MONEY_RE.finditer(text))
    for i, m in enumerate(matches):
        has_currency = bool(m.group("prefix") or m.group("suffix"))
        raw_amount = m.group("amount")
        if not has_currency and "." not in raw_amount:
            continue
        try:
            amount = float(raw_amount.replace(",", ""))
        except ValueError:
            continue
        if amount <= 0:
            continue

        context = _line_window(text, m.start(), m.end())
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end == -1:
            line_end = len(text)
        prev_end = matches[i - 1].end() if i > 0 and matches[i - 1].end() > line_start else line_start
        scoring_context = re.sub(
            r"\s+",
            " ",
            text[prev_end : min(line_end, m.end() + 32)],
        ).strip()
        score = 0.0
        if has_currency:
            score += 1.0
        for pattern, delta in _AMOUNT_GOOD_LABELS:
            if pattern.search(scoring_context):
                score += delta
        for pattern, delta in _AMOUNT_BAD_LABELS:
            if pattern.search(scoring_context):
                score += delta
        if re.search(r"\b(?:per month|/month|monthly|per year|/year|annually)\b", scoring_context, re.IGNORECASE):
            score += 0.8
        if re.search(r"\b(?:total|charged|paid)\b", scoring_context, re.IGNORECASE):
            score += 0.6

        candidates.append(_AmountCandidate(amount=amount, score=score, context=context[:160]))

    candidates.sort(key=lambda c: (c.score, c.amount), reverse=True)
    return candidates


def _amounts_from_text(text: str) -> list[float]:
    return [c.amount for c in _amount_candidates(text)]


def _best_amount(text: str) -> tuple[float | None, str, list[_AmountCandidate]]:
    candidates = _amount_candidates(text)
    if not candidates:
        return None, "", []
    best = candidates[0]
    return best.amount, best.context, candidates


def _clean_merchant_candidate(raw: str) -> str | None:
    text = unescape(str(raw or ""))
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n'\".,;()[]{}")
    if not text:
        return None

    text = _MERCHANT_SPLIT_RE.split(text, maxsplit=1)[0]
    text = re.sub(r"\b(?:via|through|using)\s+(?:stripe|paypal|square)\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:your|a|an|the|from|for|by|to|merchant|vendor|seller|store|biller)\s*[:\-]?\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:receipt|invoice|billing|bill|payment|subscription|renewal|order|confirmation)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+with\s+\d+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n'\".,;()[]{}")
    if not text:
        return None
    if len(text) > 80:
        text = text[:80].strip()

    cleaned = clean_merchant(text)
    if not cleaned or cleaned in _GENERIC_MERCHANT_WORDS:
        return None
    if re.search(r"\d+\.\d{2}", text) or re.search(r"\b20\d{2}\b", text):
        return None
    if re.search(r"\b(?:month|monthly|year|yearly|annual|renews?|starts?|cancelled)\b", text, re.IGNORECASE):
        return None
    if len(cleaned) <= 2 and cleaned not in {"at&t", "pg&e"}:
        return None
    return text


def _receipt_lines(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip() for line in body.splitlines() if line.strip()]


def _line_label(line: str) -> str:
    text = re.sub(r"[:\-]+$", "", line.strip().lower())
    text = re.sub(r"\s+", " ", text)
    return text


def _looks_like_amount_or_date(line: str) -> bool:
    return bool(_MONEY_RE.search(line) or _ISO_DATE_RE.search(line) or _SLASH_DATE_RE.search(line) or _MONTH_DATE_RE.search(line))


def _body_structure_candidates(body: str, subject: str) -> list[_MerchantCandidate]:
    lines = _receipt_lines(body)
    candidates: list[_MerchantCandidate] = []

    # Many subscription confirmations render semantic table cells as separate
    # text lines, e.g. "App" on one line and "iCloud" on the next.
    for i, line in enumerate(lines[:120]):
        label = _line_label(line)
        if label not in _BODY_LABEL_SCORES:
            continue
        for value in lines[i + 1 : i + 4]:
            value_label = _line_label(value)
            if value_label in _BODY_LABEL_SCORES or value_label in _DATE_LABELS:
                break
            if _looks_like_amount_or_date(value):
                continue
            cleaned = _clean_merchant_candidate(value)
            if cleaned:
                candidates.append(_MerchantCandidate(cleaned, _BODY_LABEL_SCORES[label], f"body-{label}"))
                break

    # Product-led subscription emails often start with a generic heading, then
    # the actual service name, then renewal cadence/price.
    subject_is_generic = bool(
        re.search(r"\b(subscription|confirmed|confirmation|renewal|receipt|invoice)\b", subject, re.IGNORECASE)
    )
    for i, line in enumerate(lines[:12]):
        label = _line_label(line)
        if label in _GENERIC_TITLE_WORDS or label in _BODY_LABEL_SCORES or label in _DATE_LABELS:
            continue
        if re.match(r"^\s*(?:merchant|vendor|seller|store|biller|app|service|subscription|product|plan)\s*:", line, re.IGNORECASE):
            continue
        if _looks_like_amount_or_date(line):
            continue
        if re.search(r"\b(?:dear|regards|copyright|terms|privacy|account|history|rights reserved)\b", line, re.IGNORECASE):
            continue
        cleaned = _clean_merchant_candidate(line)
        if not cleaned:
            continue

        nearby = " ".join(lines[i + 1 : i + 5])
        score = 0.88
        if subject_is_generic:
            score += 0.04
        if re.search(r"\b(?:renews?|subscription|monthly|annual|plan|renewal price)\b", nearby, re.IGNORECASE):
            score += 0.08
        candidates.append(_MerchantCandidate(cleaned, min(score, 0.99), "body-title"))

    return candidates


def _domain_to_merchant(address: str) -> str | None:
    if not address:
        return None
    parsed = urlparse(address if "://" in address else f"mailto:{address}")
    domain = parsed.path.split("@")[-1] if parsed.scheme == "mailto" else parsed.netloc
    domain = domain.lower().strip()
    if not domain or domain in _GENERIC_DOMAINS:
        return None

    bits = [b for b in domain.split(".") if b]
    if len(bits) < 2:
        return None
    registered = ".".join(bits[-2:])
    if registered in _GENERIC_DOMAINS:
        return None

    label = bits[-2]
    if registered in _PROCESSOR_DOMAINS and len(bits) > 2:
        label = bits[-3]
    if label in _GENERIC_MERCHANT_WORDS:
        return None
    return label.replace("-", " ").title()


def _known_service_candidates(text: str) -> list[_MerchantCandidate]:
    lowered = clean_merchant(text[:12000])
    candidates: list[_MerchantCandidate] = []
    for canonical, _category, aliases in SEED_SERVICES:
        names = [canonical, *aliases]
        for name in names:
            cleaned = clean_merchant(name)
            if cleaned and re.search(rf"\b{re.escape(cleaned)}\b", lowered):
                candidates.append(_MerchantCandidate(canonical, 0.80, "known-service"))
                break
    return candidates


def _merchant_candidates(subject: str, from_header: str, body: str) -> list[_MerchantCandidate]:
    candidates: list[_MerchantCandidate] = []

    for pattern, score in _SUBJECT_MERCHANT_PATTERNS:
        for match in pattern.finditer(subject):
            value = _clean_merchant_candidate(match.group(1))
            if value:
                candidates.append(_MerchantCandidate(value, score, "subject"))

    for line in body.splitlines()[:80]:
        for pattern, score in _BODY_MERCHANT_PATTERNS:
            match = pattern.search(line)
            if match:
                value = _clean_merchant_candidate(match.group(1))
                if value:
                    candidates.append(_MerchantCandidate(value, score, "body"))

    candidates.extend(_body_structure_candidates(body, subject))

    display, address = parseaddr(from_header or "")
    display_value = _clean_merchant_candidate(display)
    if display_value:
        cleaned_display = clean_merchant(display_value)
        score = 0.74 if cleaned_display not in _GENERIC_MERCHANT_WORDS else 0.35
        candidates.append(_MerchantCandidate(display_value, score, "from-name"))

    domain_value = _domain_to_merchant(address)
    if domain_value:
        registered = address.lower().split("@")[-1]
        score = 0.68 if not any(registered.endswith(d) for d in _PROCESSOR_DOMAINS) else 0.45
        candidates.append(_MerchantCandidate(domain_value, score, "from-domain"))

    candidates.extend(_known_service_candidates(f"{subject}\n{from_header}\n{body[:4000]}"))
    return candidates


def _best_merchant(subject: str, from_header: str, body: str) -> tuple[str | None, str]:
    candidates = _merchant_candidates(subject, from_header, body)
    if not candidates:
        return None, ""

    by_key: dict[str, _MerchantCandidate] = {}
    for candidate in candidates:
        key = clean_merchant(candidate.value)
        if not key:
            continue
        existing = by_key.get(key)
        if existing is None or candidate.score > existing.score:
            by_key[key] = candidate
        elif existing is not None:
            existing.score += 0.05

    ranked = sorted(by_key.values(), key=lambda c: (c.score, -len(c.value)), reverse=True)
    best = ranked[0]
    if best.score < 0.5:
        return None, ""
    return best.value, best.source


def _merchant_from_subject(subject: str) -> str | None:
    merchant, _source = _best_merchant(subject, "", "")
    if merchant:
        return merchant
    subject = subject.strip()
    if not subject:
        return None
    fallback = _clean_merchant_candidate(subject)
    return fallback[:80] if fallback else None


def _parse_date_fragment(text: str) -> date | None:
    text = text.strip().strip(".,;")
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%b %d %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%B %d, %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _date_from_text(text: str) -> date | None:
    lines = _receipt_lines(text)
    for i, line in enumerate(lines[:120]):
        label = _line_label(line)
        if label in _DATE_LABELS and i + 1 < len(lines):
            for pattern in (_ISO_DATE_RE, _SLASH_DATE_RE, _MONTH_DATE_RE):
                found = pattern.search(lines[i + 1])
                if found:
                    parsed = _parse_date_fragment(found.group(1).replace(",", ""))
                    if parsed:
                        return parsed

        match = _DATE_LINE_RE.search(line)
        if not match:
            continue
        fragment = match.group(1)
        for pattern in (_ISO_DATE_RE, _SLASH_DATE_RE, _MONTH_DATE_RE):
            found = pattern.search(fragment)
            if found:
                parsed = _parse_date_fragment(found.group(1).replace(",", ""))
                if parsed:
                    return parsed
    for pattern in (_ISO_DATE_RE, _SLASH_DATE_RE, _MONTH_DATE_RE):
        found = pattern.search(text[:4000])
        if found:
            parsed = _parse_date_fragment(found.group(1).replace(",", ""))
            if parsed:
                return parsed
    return None


def parse_email_text(
    body: str,
    *,
    subject: str = "",
    from_header: str = "",
    merchant_override: str | None = None,
    amount_override: float | None = None,
    date_override: date | None = None,
) -> ParseResult:
    """Extract a candidate transaction from pasted receipt or billing text."""
    combined = f"{subject}\n{from_header}\n{body}"
    amount, amount_context, amount_candidates = _best_amount(combined)
    merchant, merchant_source = _best_merchant(subject, from_header, body)
    merchant = (merchant_override or merchant or "").strip()

    if not merchant:
        for line in body.splitlines():
            line = line.strip()
            if line and len(line) > 2 and not line.lower().startswith(("hi ", "hello", "dear")):
                merchant = _clean_merchant_candidate(line) or ""
                merchant_source = "body-first-line"
                break

    if not merchant:
        return ParseResult(errors=["Could not detect merchant; enter it in the form."])

    if amount_override is not None:
        amount = amount_override
        amount_context = "manual override"
    if amount is None:
        return ParseResult(
            errors=["Could not detect amount in email text; enter amount manually."],
            warnings=["Parsed merchant only."],
        )

    txn_date = date_override or _date_from_text(combined) or date.today()
    warnings: list[str] = []
    distinct_amounts = sorted({round(c.amount, 2) for c in amount_candidates})
    if amount_override is None and len(distinct_amounts) > 1:
        warnings.append(
            f"Found {len(distinct_amounts)} prices; selected ${amount:.2f}"
            + (f" from '{amount_context[:80]}'." if amount_context else ".")
        )

    result = parse_records(
        [
            {
                "transaction_id": "email-1",
                "merchant_raw": merchant,
                "amount": amount,
                "date": txn_date.isoformat(),
                "note": subject[:200] if subject else f"email merchant source: {merchant_source}",
            }
        ]
    )
    result.warnings.extend(warnings)
    return result


def parse_eml(content: bytes) -> tuple[EmailExtraction | None, ParseResult]:
    """Parse a .eml file into extraction metadata and ParseResult."""
    try:
        msg = BytesParser(policy=policy.default).parsebytes(content)
    except Exception as e:
        return None, ParseResult(errors=[f"Invalid .eml file: {e}"])

    subject = str(msg.get("Subject", "") or "")
    from_header = str(msg.get("From", "") or "")
    plain_body, html_body = _extract_bodies(msg)
    action_links = _extract_action_links(msg)
    body = plain_body or html_body
    combined = f"{subject}\n{from_header}\n{body}"

    txn_date = _date_from_text(combined)
    if txn_date is None:
        try:
            if msg.get("Date"):
                txn_date = parsedate_to_datetime(str(msg["Date"])).date()
        except (ValueError, TypeError, OverflowError):
            txn_date = None

    merchant, merchant_source = _best_merchant(subject, from_header, body)
    amount, amount_context, _amount_candidates_list = _best_amount(combined)
    extraction = EmailExtraction(
        merchant_raw=merchant or "",
        amount=amount,
        date=txn_date,
        subject=subject,
        source="eml",
        merchant_source=merchant_source,
        amount_source=amount_context,
        action_links=action_links,
    )

    result = parse_email_text(
        body,
        subject=subject,
        from_header=from_header,
        merchant_override=merchant,
        amount_override=amount,
        date_override=txn_date,
    )
    return extraction, result
