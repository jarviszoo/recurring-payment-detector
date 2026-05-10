import unittest
from datetime import date

from merchant_normalizer import normalize
from models import Transaction
from pipeline import _same_month_prior_year


class MerchantNormalizerRegressionTests(unittest.TestCase):
    def test_pge_aliases_normalize_to_canonical_name(self):
        self.assertEqual(normalize("PG&E AUTOPAY"), "PG&E")
        self.assertEqual(normalize("PG E AUTOPAY"), "PG&E")
        self.assertEqual(normalize("PGE AUTOPAY"), "PG&E")

    def test_verizon_aliases_normalize_to_canonical_name(self):
        self.assertEqual(normalize("VERIZON"), "Verizon Wireless")
        self.assertEqual(normalize("VERIZON WIRELESS"), "Verizon Wireless")

    def test_chess_and_youtube_premium_aliases(self):
        self.assertEqual(normalize("CHESS.COM PREMIUM"), "Chess.com")
        self.assertEqual(normalize("YOUTUBE PREMIUM"), "YouTube")


class SeasonalLookupRegressionTests(unittest.TestCase):
    def test_same_month_prior_year_handles_leap_day(self):
        current = Transaction(
            transaction_id="t-current",
            merchant_raw="PG&E AUTOPAY",
            amount=120.0,
            date=date(2024, 2, 29),
            currency="USD",
            category_mcc="utilities",
            payment_method="card",
            description="PG&E AUTOPAY",
        )
        history = [
            Transaction(
                transaction_id="t-prior-match",
                merchant_raw="PG&E AUTOPAY",
                amount=110.0,
                date=date(2023, 2, 28),
                currency="USD",
                category_mcc="utilities",
                payment_method="card",
                description="PG&E AUTOPAY",
            ),
            Transaction(
                transaction_id="t-prior-other",
                merchant_raw="PG&E AUTOPAY",
                amount=100.0,
                date=date(2022, 12, 31),
                currency="USD",
                category_mcc="utilities",
                payment_method="card",
                description="PG&E AUTOPAY",
            ),
        ]

        results = _same_month_prior_year(current, history)
        self.assertEqual([t.transaction_id for t in results], ["t-prior-match"])


if __name__ == "__main__":
    unittest.main()
