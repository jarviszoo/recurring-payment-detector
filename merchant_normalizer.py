import re
import unicodedata

# Maps known raw merchant fragments to a canonical name.
# This is an identity table, not a price database.
MERCHANT_ALIASES = {
    "netflix": "Netflix",
    "nflx": "Netflix",
    "spotify": "Spotify",
    "apple": "Apple",
    "apple.com": "Apple",
    "itunes": "Apple",
    "amazon": "Amazon",
    "amzn": "Amazon",
    "amazon prime": "Amazon",
    "adobe": "Adobe",
    "adobe creative": "Adobe",
    "google": "Google",
    "google play": "Google",
    "youtube": "YouTube",
    "hulu": "Hulu",
    "disney": "Disney+",
    "disneyplus": "Disney+",
    "paramount": "Paramount+",
    "hbomax": "Max",
    "max": "Max",
    "peacock": "Peacock",
    "canva": "Canva",
    "dropbox": "Dropbox",
    "github": "GitHub",
    "notion": "Notion",
    "slack": "Slack",
    "zoom": "Zoom",
    "microsoft": "Microsoft",
    "office365": "Microsoft",
    "xbox": "Xbox",
    "playstation": "PlayStation",
    "nintendo": "Nintendo",
    "twitch": "Twitch",
    "audible": "Audible",
    "kindle": "Kindle",
    "pandora": "Pandora",
    "duolingo": "Duolingo",
    "calm": "Calm",
    "headspace": "Headspace",
    "nytimes": "NY Times",
    "new york times": "NY Times",
    "wsj": "Wall Street Journal",
    "washington post": "Washington Post",
    "wapost": "Washington Post",
}

# Patterns to strip from raw merchant strings
_STRIP_PATTERNS = [
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone numbers
    r"\b\d{5,}\b",                            # long numeric IDs
    r"\b[A-Z]{2}\b(?=\s|$)",                  # 2-letter state codes at end
    r"#\S+",                                   # reference numbers like #12345
    r"\*+\S*",                                 # asterisk-prefixed tokens
    r"\b(llc|inc|corp|ltd|co)\b",             # legal suffixes
    r"[^\w\s./+-]",                            # misc punctuation
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _STRIP_PATTERNS]


def normalize(raw: str) -> str:
    """Return a canonical merchant name from a raw transaction description."""
    text = _clean(raw)
    return _lookup(text) or _title_case(text)


def _clean(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw)
    text = text.lower()
    for pattern in _COMPILED:
        text = pattern.sub(" ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove trailing domain-like suffixes (.com, .net, etc.)
    text = re.sub(r"\.(com|net|org|io|co|biz|app)(\s|$)", " ", text).strip()
    return text


def _lookup(cleaned: str) -> str | None:
    """Check alias table, trying progressively shorter prefixes."""
    if cleaned in MERCHANT_ALIASES:
        return MERCHANT_ALIASES[cleaned]
    # Try each word token against the alias table
    tokens = cleaned.split()
    for length in range(len(tokens), 0, -1):
        candidate = " ".join(tokens[:length])
        if candidate in MERCHANT_ALIASES:
            return MERCHANT_ALIASES[candidate]
    return None


def _title_case(text: str) -> str:
    return text.title()
