"""
Smoke tests for the entity resolution pipeline.
Run with:  python tests.py
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from datetime import date

import service_registry
import feedback_store
import entity_resolver
from merchant_normalizer import SEED_SERVICES, clean


def setup():
    service_registry.clear()
    feedback_store.clear()
    service_registry.bootstrap_seed(SEED_SERVICES)


def assert_eq(actual, expected, label):
    ok = actual == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: got {actual!r}, expected {expected!r}")
    return ok


def assert_in(member, container, label):
    ok = member in container
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: {member!r} {'in' if ok else 'NOT in'} {container!r}")
    return ok


def test_text_cleaning():
    print("\n=== test_text_cleaning ===")
    cases = [
        ("NETFLIX.COM 866-579-7172", "netflix"),
        ("PG&E AUTOPAY", "pg&e autopay"),
        ("AT&T WIRELESS 8004310023", "at&t wireless"),
        ("ADOBE CREATIVE CLOUD", "adobe creative cloud"),
        ("APPLE.COM/BILL", "apple /bill"),
        ("", ""),
    ]
    passed = sum(assert_eq(clean(raw), expected, raw) for raw, expected in cases)
    return passed, len(cases)


def test_exact_alias_resolution():
    print("\n=== test_exact_alias_resolution ===")
    setup()
    cases = [
        ("NETFLIX.COM",        "Netflix",   "exact_alias"),
        ("ADOBE CREATIVE CLOUD","Adobe",    "exact_alias"),
        ("PG&E AUTOPAY",       "PG&E",      "exact_alias"),
        ("Spotify Premium",    "Spotify",   "exact_alias"),
    ]
    passed = 0
    total = 0
    for raw, expected_canonical, expected_method in cases:
        res = entity_resolver.resolve(raw, txn_date=date(2026, 1, 1))
        passed += assert_eq(res.canonical_name, expected_canonical, f"{raw} canonical")
        passed += assert_eq(res.method, expected_method, f"{raw} method")
        total += 2
    return passed, total


def test_fuzzy_typo_resolution():
    print("\n=== test_fuzzy_typo_resolution ===")
    setup()
    cases = [
        "NETFLX",          # missing letter
        "NETFLIIX",        # extra letter
        "NETFLIX LOS GATOS CA",  # noise after
    ]
    passed = 0
    total = 0
    for raw in cases:
        res = entity_resolver.resolve(raw, txn_date=date(2026, 1, 1))
        passed += assert_eq(res.canonical_name, "Netflix", f"{raw} canonical")
        passed += (1 if res.confidence >= 0.80 else 0)
        total += 2
        print(f"      method={res.method!r} conf={res.confidence}")
    return passed, total


def test_embedding_resolution():
    print("\n=== test_embedding_resolution ===")
    setup()
    cases = [
        ("PG E AUTOPAY", "PG&E"),       # missing &
        ("ATT WIRELESS", "AT&T"),
    ]
    passed = 0
    total = 0
    for raw, expected in cases:
        res = entity_resolver.resolve(raw, txn_date=date(2026, 1, 1))
        passed += assert_eq(res.canonical_name, expected, f"{raw}")
        passed += (1 if res.method in ("fuzzy", "embedding", "fuzzy+embedding", "exact_alias") else 0)
        total += 2
        print(f"      method={res.method!r} conf={res.confidence}")
    return passed, total


def test_new_service_creation():
    print("\n=== test_new_service_creation ===")
    setup()
    res = entity_resolver.resolve("BRAND NEW STARTUP XYZ", txn_date=date(2026, 1, 1))
    p = 0
    p += assert_eq(res.method, "new_service", "method")
    p += (1 if res.canonical_name and res.canonical_name.lower().startswith("brand new startup") else 0)
    p += (1 if 0.0 < res.confidence < 0.5 else 0)
    return p, 3


def test_alias_auto_learning():
    print("\n=== test_alias_auto_learning ===")
    setup()
    # First match by fuzzy — should auto-attach the cleaned form as a new alias
    res1 = entity_resolver.resolve("NETFLX", txn_date=date(2026, 1, 1))
    netflix = service_registry.find_by_canonical("Netflix")
    p = 0
    p += assert_in("netflx", [a.lower() for a in netflix.aliases], "netflx attached as alias")
    # Second occurrence should now hit exact_alias
    res2 = entity_resolver.resolve("NETFLX", txn_date=date(2026, 2, 1))
    p += assert_eq(res2.method, "exact_alias", "second NETFLX hits exact_alias")
    return p, 2


def test_canonical_grouping():
    """Different raw strings for the same service must group under the same canonical name."""
    print("\n=== test_canonical_grouping ===")
    setup()
    raws = [
        "NETFLIX.COM",
        "NFLX DIGITAL",
        "Netflix.com",
        "NETFLIX LOS GATOS CA",
        "NETFLX",
    ]
    canonicals = set()
    for r in raws:
        res = entity_resolver.resolve(r, txn_date=date(2026, 1, 1))
        canonicals.add(res.canonical_name)
    p = assert_eq(canonicals, {"Netflix"}, "all variants group to Netflix")
    return p, 1


def test_clustering():
    print("\n=== test_clustering ===")
    import clusterer
    raws = [
        "Bobs Burgers Cafe",
        "BOBS BURGERS CAFE",
        "bobs burgers cafe llc",
        "Some Other Place",
    ]
    clusters = clusterer.cluster_unresolved(raws)
    cluster_sizes = sorted(c["size"] for c in clusters)
    # Expect a cluster of 3 + a singleton
    p = assert_in(3, cluster_sizes, "found cluster of 3 Bobs variants")
    return p, 1


def main():
    suites = [
        test_text_cleaning,
        test_exact_alias_resolution,
        test_fuzzy_typo_resolution,
        test_embedding_resolution,
        test_new_service_creation,
        test_alias_auto_learning,
        test_canonical_grouping,
        test_clustering,
    ]
    total_passed, total_count = 0, 0
    for fn in suites:
        p, t = fn()
        total_passed += p
        total_count += t

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {total_passed} / {total_count} assertions passed")
    print('=' * 60)
    return 0 if total_passed == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
