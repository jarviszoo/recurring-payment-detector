"""
Text-cleaning layer for merchant strings.

This module ONLY does syntactic cleanup (regex stripping, whitespace
collapse, case normalisation).  Mapping cleaned strings to canonical
services is the job of entity_resolver.py — which uses service_registry as
its source of truth, not a hardcoded table here.

The legacy MERCHANT_ALIASES dict is kept as a *seed* for cold-start
bootstrapping only; it's no longer consulted on every resolve() call.
"""

import re
import unicodedata

# Seed used by service_registry.bootstrap_seed() for cold-start.
# (canonical_name, category, [aliases])
SEED_SERVICES: list[tuple[str, str, list[str]]] = [
    ("Netflix",   "streaming", ["netflix", "nflx", "netflix com"]),
    ("Spotify",   "music",     ["spotify", "spotify usa", "spotify premium"]),
    ("Apple",     "app_store", ["apple", "apple com bill", "itunes"]),
    ("Amazon",    "mixed_commerce", ["amazon", "amzn", "amazon prime"]),
    ("Adobe",     "software",  ["adobe", "adobe creative", "adobe creative cloud"]),
    ("Google",    "app_store", ["google", "google play"]),
    ("YouTube",   "streaming", ["youtube", "youtube premium"]),
    ("Hulu",      "streaming", ["hulu"]),
    ("Disney+",   "streaming", ["disney", "disneyplus", "disney plus"]),
    ("Max",       "streaming", ["max", "hbomax", "hbo max"]),
    ("Paramount+","streaming", ["paramount", "paramount plus"]),
    ("Peacock",   "streaming", ["peacock"]),
    ("Canva",     "software",  ["canva"]),
    ("iCloud+",   "cloud_storage", ["icloud", "icloud+", "icloud plus"]),
    ("Dropbox",   "cloud_storage", ["dropbox"]),
    ("GitHub",    "software",  ["github"]),
    ("Notion",    "software",  ["notion"]),
    ("Microsoft", "software",  ["microsoft", "office365", "office 365"]),
    ("Zoom",      "software",  ["zoom"]),
    ("Audible",   "music",     ["audible"]),
    ("Twitch",    "streaming", ["twitch"]),
    ("PG&E",      "utilities", ["pg&e", "pg e", "pge", "pacific gas electric", "pg&e autopay"]),
    ("AT&T",      "telecom",   ["at&t", "att", "at t", "at&t wireless"]),
    ("Verizon",   "telecom",   ["verizon", "verizon wireless", "vzw"]),
    ("T-Mobile",  "telecom",   ["t-mobile", "tmobile", "t mobile"]),
    ("Comcast",   "telecom",   ["comcast", "xfinity"]),
    ("Geico",     "insurance", ["geico", "geico insurance"]),
    ("State Farm","insurance", ["state farm"]),
]

# Patterns to strip from raw merchant strings — preserves & + - . / for brand fidelity
_STRIP_PATTERNS = [
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone numbers
    r"\b\d{5,}\b",                           # long numeric IDs
    r"\b[A-Z]{2}\b(?=\s|$)",                 # 2-letter state codes at end
    r"#\S+",                                  # reference numbers
    r"\*+\S*",                                # asterisk-prefixed tokens
    r"\b(llc|inc|corp|ltd|co)\b",            # legal suffixes
    r"[^\w\s.&+/-]",                          # punctuation except & + . / -
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _STRIP_PATTERNS]


def clean(raw: str) -> str:
    """
    Strip phone numbers, IDs, location/state codes, and punctuation noise
    from a raw merchant string.  Preserves brand-defining characters
    (& + . /).  Returns lowercase, single-spaced text.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKD", raw).lower()
    for pat in _COMPILED:
        text = pat.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Drop trailing domain suffixes
    text = re.sub(r"\.(com|net|org|io|co|biz|app)\b", " ", text).strip()
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Backward-compat: legacy normalize() returns a presentable canonical name
# without consulting the registry.  Used by old call sites that haven't been
# migrated to entity_resolver.resolve().
# ---------------------------------------------------------------------------

def normalize(raw: str) -> str:
    cleaned = clean(raw)
    if not cleaned:
        return cleaned
    if "&" in cleaned:
        return cleaned.upper()
    return cleaned.title()
