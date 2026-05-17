"""Tests for data ingestion parsers."""

import sys
import io
import os
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from datetime import date
from cancellation import (
    cancellation_database_path,
    clear_cancellation_database_cache,
    get_cancellation_guide,
    save_researched_cancellation_record,
)
from ingest.parsers import parse_csv, parse_json, parse_records
from ingest.runner import analyze
from ingest.email_parser import parse_email_text, parse_eml


def test_parse_csv():
    csv_text = "merchant,amount,date\nNETFLIX.COM,15.49,2026-01-01\n"
    r = parse_csv(csv_text)
    assert len(r.transactions) == 1
    assert r.transactions[0].merchant_raw == "NETFLIX.COM"
    assert r.transactions[0].amount == 15.49
    print("  [PASS] parse_csv")


def test_parse_json():
    js = '{"transactions":[{"merchant_raw":"Spotify","amount":9.99,"date":"2026-02-01"}]}'
    r = parse_json(js)
    assert len(r.transactions) == 1
    print("  [PASS] parse_json")


def test_parse_email():
    r = parse_email_text(
        "Your subscription was charged $19.99",
        subject="Receipt from Adobe",
        merchant_override="Adobe",
        date_override=date(2026, 1, 1),
    )
    assert len(r.transactions) == 1
    assert r.transactions[0].amount == 19.99
    print("  [PASS] parse_email")


def test_parse_email_prefers_total():
    r = parse_email_text(
        "Subtotal $19.99\nTax $1.65\nTotal charged $21.64",
        subject="Your Canva receipt",
        date_override=date(2026, 1, 1),
    )
    assert len(r.transactions) == 1
    assert r.transactions[0].merchant_raw == "Canva"
    assert r.transactions[0].amount == 21.64
    print("  [PASS] parse_email_prefers_total")


def test_parse_eml_html_receipt():
    raw = b"""From: "Netflix" <no-reply@mailer.netflix.com>
To: user@example.com
Subject: Your Netflix receipt
Date: Sat, 17 Jan 2026 10:30:00 -0800
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body>
  <p>Subtotal $15.49</p>
  <p>Tax $1.32</p>
  <p>Total charged $16.81</p>
</body></html>
"""
    extraction, r = parse_eml(raw)
    assert extraction is not None
    assert extraction.merchant_raw == "Netflix"
    assert extraction.amount == 16.81
    assert len(r.transactions) == 1
    assert r.transactions[0].merchant_raw == "Netflix"
    assert r.transactions[0].amount == 16.81
    assert r.transactions[0].date == date(2026, 1, 17)
    print("  [PASS] parse_eml_html_receipt")


def test_parse_eml_processor_sender_body_vendor():
    raw = b"""From: Stripe Receipts <receipts@example.stripe.com>
To: user@example.com
Subject: Receipt from Bright Gym
Date: Sat, 14 Feb 2026 10:30:00 -0800
Content-Type: text/plain; charset="utf-8"

Merchant: Bright Gym
Transaction date: Feb 14, 2026
Monthly membership
Subtotal $20.00
Tax $1.70
Amount paid $21.70
"""
    extraction, r = parse_eml(raw)
    assert extraction is not None
    assert extraction.merchant_raw == "Bright Gym"
    assert extraction.amount == 21.70
    assert len(r.transactions) == 1
    assert r.transactions[0].merchant_raw == "Bright Gym"
    assert r.transactions[0].amount == 21.70
    assert r.transactions[0].date == date(2026, 2, 14)
    print("  [PASS] parse_eml_processor_sender_body_vendor")


def test_parse_eml_apple_subscription_service():
    raw = b"""From: Apple <no_reply@email.apple.com>
To: user@example.com
Subject: Your Subscription is Confirmed
Date: Tue, 09 Sep 2025 09:28:06 +0000
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: quoted-printable

<html><body>
  <h1>Confirmation</h1>
  <p>iCloud+</p>
  <p>1 month</p>
  <p>Renews monthly for $3.99</p>
  <p>This email confirms your storage plan upgrade:</p>
  <p>App</p>
  <p>iCloud</p>
  <p>Plan</p>
  <p>iCloud+ with 200 GB storage</p>
  <p>Date of Upgrade</p>
  <p>Sep 9, 2025</p>
  <p>Renewal Price</p>
  <p>$3.99/month</p>
  <a href="https://account.apple.com/">Apple Account</a>
</body></html>
"""
    extraction, r = parse_eml(raw)
    assert extraction is not None
    assert extraction.merchant_raw == "iCloud+"
    assert extraction.amount == 3.99
    assert extraction.date == date(2025, 9, 9)
    assert len(r.transactions) == 1
    assert r.transactions[0].merchant_raw == "iCloud+"
    assert r.transactions[0].amount == 3.99
    assert r.transactions[0].date == date(2025, 9, 9)
    assert extraction.action_links[0]["url"] == "https://account.apple.com/"
    print("  [PASS] parse_eml_apple_subscription_service")


def test_cancellation_guides():
    icloud = get_cancellation_guide("iCloud+")
    assert icloud.source in {"xlsx_database", "built_in_database"}
    assert icloud.service_name == "iCloud+"
    assert icloud.cancellation_process or icloud.steps

    if cancellation_database_path() is not None:
        netflix = get_cancellation_guide("Netflix")
        assert netflix.source == "xlsx_database"
        assert netflix.category == "Streaming Video"
        assert netflix.cancellation_process

    unknown = get_cancellation_guide("Totally Unknown Vendor")
    assert unknown.source == "web_search"
    assert "official+cancel+subscription" in unknown.search_url
    print("  [PASS] cancellation_guides")


def test_save_researched_cancellation_record():
    old_path = os.environ.get("SUBSCRIPTION_CANCELLATION_XLSX")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "subscription_cancellation_process.xlsx")
        os.environ["SUBSCRIPTION_CANCELLATION_XLSX"] = db_path
        clear_cancellation_database_cache()
        try:
            save_researched_cancellation_record(
                {
                    "provider": "Example Vendor",
                    "category": "software",
                    "market_position": "AI/web researched",
                    "price_range": "Unknown",
                    "billing_cycle": "Monthly",
                    "website": "example.com",
                    "cancellation_process": "Type 1 — Web\nDirect link: https://example.com/account\nWorkflow:\n1. Sign in.\n2. Cancel.",
                    "additional_resources": "https://example.com/help",
                }
            )
            guide = get_cancellation_guide("Example Vendor")
            assert guide.source == "xlsx_database"
            assert guide.service_name == "Example Vendor"
            assert guide.billing_cycle == "Monthly"
            assert "Direct link" in guide.cancellation_process
        finally:
            if old_path is None:
                os.environ.pop("SUBSCRIPTION_CANCELLATION_XLSX", None)
            else:
                os.environ["SUBSCRIPTION_CANCELLATION_XLSX"] = old_path
            clear_cancellation_database_cache()
    print("  [PASS] save_researched_cancellation_record")


def test_analyze_smoke():
    r = parse_records([
        {"merchant_raw": "NETFLIX.COM", "amount": 15.49, "date": "2026-01-01"},
        {"merchant_raw": "NETFLIX.COM", "amount": 15.49, "date": "2026-02-01"},
        {"merchant_raw": "NETFLIX.COM", "amount": 99.99, "date": "2026-03-01"},
    ])
    report = analyze(r.transactions, reset_registry=True, reset_feedback=True)
    assert report.transaction_count == 3
    assert report.alert_count >= 1
    print("  [PASS] analyze_smoke")


def main():
    tests = [
        test_parse_csv,
        test_parse_json,
        test_parse_email,
        test_parse_email_prefers_total,
        test_parse_eml_html_receipt,
        test_parse_eml_processor_sender_body_vendor,
        test_parse_eml_apple_subscription_service,
        test_cancellation_guides,
        test_save_researched_cancellation_record,
        test_analyze_smoke,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
    print(f"\nIngest tests: {passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
