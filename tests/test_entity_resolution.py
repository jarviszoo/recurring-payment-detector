import unittest
from datetime import date

from models import Transaction
from entity_resolution import build_canonical_registry


class EntityResolutionTests(unittest.TestCase):
    def test_aliases_resolve_to_single_provider(self):
        txns = [
            Transaction("t1", "NETFLIX.COM 866-579-7172", 15.49, date(2026, 1, 1)),
            Transaction("t2", "NFLX DIGITAL", 15.49, date(2026, 2, 1)),
            Transaction("t3", "Netflix.com", 15.49, date(2026, 3, 1)),
        ]
        providers, events = build_canonical_registry(txns)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].canonical_name, "Netflix")
        self.assertEqual(len(events), 3)

    def test_unseen_service_creates_new_provider(self):
        txns = [
            Transaction("t1", "SOME NEW VIDEO LAB", 9.99, date(2026, 1, 1)),
            Transaction("t2", "ANOTHER UNKNOWN APP", 7.99, date(2026, 1, 2)),
        ]
        providers, _ = build_canonical_registry(txns)
        self.assertEqual(len(providers), 2)


if __name__ == "__main__":
    unittest.main()
