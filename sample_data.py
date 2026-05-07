"""
Sample transactions covering:
  Phase 1 scenarios (streaming, software, app store)
  Phase 2 new scenarios (telecom, utilities, SaaS, insurance)
"""

from datetime import date
from models import Transaction

SAMPLE_TRANSACTIONS = [
    # -------------------------------------------------------------------------
    # Netflix: stable $15.49 — no alert expected
    # -------------------------------------------------------------------------
    Transaction("t001", "NETFLIX.COM 866-579-7172", 15.49, date(2025, 11, 1)),
    Transaction("t002", "NETFLIX.COM",              15.49, date(2025, 12, 1)),
    Transaction("t003", "NFLX DIGITAL",             15.49, date(2026,  1, 1)),
    Transaction("t004", "Netflix.com",              15.49, date(2026,  2, 1)),
    Transaction("t005", "NETFLIX LOS GATOS CA",     15.49, date(2026,  3, 1)),

    # -------------------------------------------------------------------------
    # Adobe: $19.99 → $59.99 — HIGH alert expected
    # -------------------------------------------------------------------------
    Transaction("t010", "ADOBE CREATIVE CLOUD", 19.99, date(2025, 11, 15)),
    Transaction("t011", "ADOBE CREATIVE CLOUD", 19.99, date(2025, 12, 15)),
    Transaction("t012", "ADOBE CREATIVE CLOUD", 19.99, date(2026,  1, 15)),
    Transaction("t013", "ADOBE CREATIVE CLOUD", 59.99, date(2026,  2, 15)),

    # -------------------------------------------------------------------------
    # Canva: monthly $12.99 → annual $119.99 — HIGH alert expected
    # -------------------------------------------------------------------------
    Transaction("t020", "CANVA", 12.99, date(2025, 10, 20)),
    Transaction("t021", "CANVA", 12.99, date(2025, 11, 20)),
    Transaction("t022", "CANVA", 12.99, date(2025, 12, 20)),
    Transaction("t023", "CANVA", 119.99, date(2026,  1, 20)),

    # -------------------------------------------------------------------------
    # Apple: two tiers ($2.99 iCloud + $9.99 Apple Music)
    # $14.99 Apple Music price hike — LOW alert expected; no false cross-tier alert
    # -------------------------------------------------------------------------
    Transaction("t030", "APPLE.COM/BILL", 2.99,  date(2025, 11,  5)),
    Transaction("t031", "APPLE.COM/BILL", 9.99,  date(2025, 11,  5)),
    Transaction("t032", "APPLE.COM/BILL", 2.99,  date(2025, 12,  5)),
    Transaction("t033", "APPLE.COM/BILL", 9.99,  date(2025, 12,  5)),
    Transaction("t034", "APPLE.COM/BILL", 2.99,  date(2026,  1,  5)),
    Transaction("t035", "APPLE.COM/BILL", 9.99,  date(2026,  1,  5)),
    Transaction("t036", "APPLE.COM/BILL", 2.99,  date(2026,  2,  5)),
    Transaction("t037", "APPLE.COM/BILL", 14.99, date(2026,  2,  5)),

    # -------------------------------------------------------------------------
    # Spotify: minor tax change $10.99 → $11.18 — no alert (1.7%)
    # -------------------------------------------------------------------------
    Transaction("t040", "SPOTIFY USA",     10.99, date(2025, 11, 10)),
    Transaction("t041", "SPOTIFY",         10.99, date(2025, 12, 10)),
    Transaction("t042", "Spotify Premium", 10.99, date(2026,  1, 10)),
    Transaction("t043", "SPOTIFY USA",     11.18, date(2026,  2, 10)),

    # -------------------------------------------------------------------------
    # Verizon (telecom): stable ~$85 with small variation, then spike to $145
    # Telecom threshold is $15 + 25%, so $60 / 71% → WARNING expected
    # -------------------------------------------------------------------------
    Transaction("t050", "VERIZON WIRELESS", 85.00, date(2025, 11,  3), category_mcc="4814"),
    Transaction("t051", "VERIZON WIRELESS", 87.50, date(2025, 12,  3), category_mcc="4814"),
    Transaction("t052", "VERIZON WIRELESS", 86.00, date(2026,  1,  3), category_mcc="4814"),
    Transaction("t053", "VERIZON WIRELESS", 145.00, date(2026, 2,  3), category_mcc="4814"),

    # -------------------------------------------------------------------------
    # PG&E (utilities): seasonal — winter higher, summer lower
    # Jan 2026 = $210 vs Jan 2025 = $185 and recent $90-$95 (summer) → alert
    # Utility threshold is $20 + 30%, and $210 is way above recent AND seasonal
    # -------------------------------------------------------------------------
    Transaction("t060", "PG&E AUTOPAY", 95.00,  date(2025,  7, 15), category_mcc="4900"),
    Transaction("t061", "PG&E AUTOPAY", 90.00,  date(2025,  8, 15), category_mcc="4900"),
    Transaction("t062", "PG&E AUTOPAY", 92.00,  date(2025,  9, 15), category_mcc="4900"),
    Transaction("t063", "PG&E AUTOPAY", 185.00, date(2025, 10, 15), category_mcc="4900"),
    Transaction("t064", "PG&E AUTOPAY", 190.00, date(2025, 11, 15), category_mcc="4900"),
    Transaction("t065", "PG&E AUTOPAY", 188.00, date(2025, 12, 15), category_mcc="4900"),
    Transaction("t066", "PG&E AUTOPAY", 210.00, date(2026,  1, 15), category_mcc="4900"),

    # -------------------------------------------------------------------------
    # GitHub (SaaS/software): $4/mo stable, then jumps to $21 (team plan)
    # Software threshold is $5 + 10% → WARNING expected
    # -------------------------------------------------------------------------
    Transaction("t070", "GITHUB", 4.00, date(2025, 11, 22), category_mcc="7372"),
    Transaction("t071", "GITHUB", 4.00, date(2025, 12, 22), category_mcc="7372"),
    Transaction("t072", "GITHUB", 4.00, date(2026,  1, 22), category_mcc="7372"),
    Transaction("t073", "GITHUB", 21.00, date(2026, 2, 22), category_mcc="7372"),

    # -------------------------------------------------------------------------
    # Geico (insurance): $120/mo stable, small annual renewal bump to $138
    # Insurance threshold is $10 + 15% → $18 / 15% → WARNING expected
    # -------------------------------------------------------------------------
    Transaction("t080", "GEICO INSURANCE", 120.00, date(2025, 11, 1), category_mcc="6300"),
    Transaction("t081", "GEICO INSURANCE", 120.00, date(2025, 12, 1), category_mcc="6300"),
    Transaction("t082", "GEICO INSURANCE", 120.00, date(2026,  1, 1), category_mcc="6300"),
    Transaction("t083", "GEICO INSURANCE", 138.00, date(2026,  2, 1), category_mcc="6300"),
]
