"""
Layered merchant category classification.

Layer 1: MCC code lookup (most authoritative when available)
Layer 2: Known merchant-to-category alias table
Layer 3: Keyword/NLP classification on the raw description
"""

import re
from merchant_normalizer import normalize

# ---------------------------------------------------------------------------
# Layer 1: MCC → category
# ---------------------------------------------------------------------------
MCC_MAP: dict[str, str] = {
    "4812": "telecom",
    "4813": "telecom",
    "4814": "telecom",
    "4816": "software",
    "4899": "streaming",
    "4900": "utilities",
    "5045": "software",
    "5065": "software",
    "5734": "software",
    "5945": "gaming",
    "7372": "software",
    "7375": "software",
    "7399": "software",
    "7922": "streaming",
    "7994": "gaming",
    "7995": "gaming",
    "8011": "insurance",
    "8049": "insurance",
    "6300": "insurance",
    "6321": "insurance",
}

# ---------------------------------------------------------------------------
# Layer 2: Canonical merchant name → category
# ---------------------------------------------------------------------------
MERCHANT_CATEGORY: dict[str, str] = {
    # Streaming
    "Netflix": "streaming",
    "Hulu": "streaming",
    "Disney+": "streaming",
    "Max": "streaming",
    "Peacock": "streaming",
    "Paramount+": "streaming",
    "YouTube": "streaming",
    "Twitch": "streaming",
    # Music
    "Spotify": "music",
    "Pandora": "music",
    "Audible": "music",
    # Software / SaaS
    "Adobe": "software",
    "Canva": "software",
    "Dropbox": "software",
    "GitHub": "software",
    "Notion": "software",
    "Slack": "software",
    "Zoom": "software",
    "Microsoft": "software",
    "Kindle": "software",
    "Duolingo": "software",
    "Calm": "software",
    "Headspace": "software",
    # Mixed / app store
    "Apple": "app_store",
    "Google": "app_store",
    "Amazon": "mixed_commerce",
    # Gaming
    "Xbox": "gaming",
    "PlayStation": "gaming",
    "Nintendo": "gaming",
    # News
    "NY Times": "news",
    "Wall Street Journal": "news",
    "Washington Post": "news",
    # Cloud storage
    "Dropbox": "cloud_storage",
    # Telecom (common US carriers)
    "Verizon": "telecom",
    "At&T": "telecom",
    "T-Mobile": "telecom",
    "Sprint": "telecom",
    "Comcast": "telecom",
    "Xfinity": "telecom",
    "Spectrum": "telecom",
    "Cox": "telecom",
    # Utilities
    "Pg&E": "utilities",
    "Con Edison": "utilities",
    "Duke Energy": "utilities",
    "Sce": "utilities",
    "Dominion": "utilities",
    # Insurance
    "Geico": "insurance",
    "State Farm": "insurance",
    "Allstate": "insurance",
    "Progressive": "insurance",
    "Aetna": "insurance",
    "Cigna": "insurance",
    # Fitness / delivery
    "Peloton": "fitness",
    "Planet Fitness": "fitness",
    "Doordash": "delivery",
    "Instacart": "delivery",
}

# ---------------------------------------------------------------------------
# Layer 3: keyword patterns → category
# ---------------------------------------------------------------------------
_KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"stream|video|watch|movies?|tv\b", re.I), "streaming"),
    (re.compile(r"music|audio|podcast|radio|sound", re.I), "music"),
    (re.compile(r"cloud|storage|backup|drive|sync", re.I), "cloud_storage"),
    (re.compile(r"software|saas|license|subscription|pro\b|premium", re.I), "software"),
    (re.compile(r"game|gaming|xbox|playstation|steam|nintendo", re.I), "gaming"),
    (re.compile(r"wireless|cellular|mobile|phone|telecom|internet|broadband|cable", re.I), "telecom"),
    (re.compile(r"electric|gas|water|power|energy|utility|utilities|autopay", re.I), "utilities"),
    (re.compile(r"insurance|insur|policy|premium|coverage|geico|allstate", re.I), "insurance"),
    (re.compile(r"news|magazine|journal|times|post|press|media", re.I), "news"),
    (re.compile(r"gym|fitness|workout|yoga|health|wellness", re.I), "fitness"),
    (re.compile(r"delivery|groceries|meal|food.*kit", re.I), "delivery"),
    (re.compile(r"app\.?com|app.*bill|itunes|google.*play|play.*store", re.I), "app_store"),
]


def classify(
    merchant_raw: str,
    mcc: str | None = None,
) -> str:
    """Return the category string for this transaction."""

    # Layer 1: MCC
    if mcc and mcc in MCC_MAP:
        return MCC_MAP[mcc]

    # Layer 2: canonical merchant alias table
    canonical = normalize(merchant_raw)
    if canonical in MERCHANT_CATEGORY:
        return MERCHANT_CATEGORY[canonical]

    # Layer 3: keyword scan on the raw description
    for pattern, category in _KEYWORD_RULES:
        if pattern.search(merchant_raw):
            return category

    return "general"
