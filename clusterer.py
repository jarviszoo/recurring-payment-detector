"""
Cluster unresolved merchants into candidate canonical services.

Used as a periodic batch job:
  1. Collect raw merchant strings the resolver couldn't match
  2. Vectorise (TF-IDF char n-grams, same as embedding_matcher)
  3. DBSCAN to cluster similar strings together
  4. Each cluster becomes a candidate new CanonicalService
  5. Pick the most frequent (or shortest) string in each cluster as the canonical name
"""

from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_distances
import numpy as np

# DBSCAN parameters tuned for character n-gram TF-IDF
EPS = 0.40            # max cosine distance between two points in same cluster
MIN_SAMPLES = 2       # need at least 2 raw strings to form a cluster


def cluster_unresolved(raw_strings: list[str]) -> list[dict]:
    """
    Group similar raw merchant strings.
    Returns a list of dicts:
        {
          "canonical_candidate": "Some Vendor",
          "members": ["SOME VENDOR LLC", "Some-Vendor", ...],
          "size": 3
        }
    Singletons (DBSCAN noise) are returned as their own cluster of size 1
    so the caller can decide whether to register them anyway.
    """
    if not raw_strings:
        return []

    cleaned = [s.lower().strip() for s in raw_strings]

    # If only one item, return it directly
    if len(cleaned) == 1:
        return [{
            "canonical_candidate": _pick_canonical([raw_strings[0]]),
            "members": [raw_strings[0]],
            "size": 1,
        }]

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(cleaned)
    dist = cosine_distances(matrix)

    db = DBSCAN(eps=EPS, min_samples=MIN_SAMPLES, metric="precomputed")
    labels = db.fit_predict(dist)

    clusters: dict[int, list[int]] = {}
    for idx, lbl in enumerate(labels):
        clusters.setdefault(int(lbl), []).append(idx)

    out: list[dict] = []
    for lbl, members in clusters.items():
        member_strs = [raw_strings[i] for i in members]
        if lbl == -1:
            # DBSCAN noise — emit each as its own singleton cluster
            for s in member_strs:
                out.append({
                    "canonical_candidate": _pick_canonical([s]),
                    "members": [s],
                    "size": 1,
                })
        else:
            out.append({
                "canonical_candidate": _pick_canonical(member_strs),
                "members": member_strs,
                "size": len(member_strs),
            })
    return out


# ---------------------------------------------------------------------------

def _pick_canonical(members: list[str]) -> str:
    """
    Choose the cluster representative.
    Heuristic: most common string; tiebreak on shortest (least noise).
    """
    counts = Counter(members)
    most_common = counts.most_common()
    top_count = most_common[0][1]
    candidates = [s for s, c in most_common if c == top_count]
    candidates.sort(key=lambda s: (len(s), s))
    chosen = candidates[0]
    # Render in title case but preserve all-caps brand styling like PG&E or AT&T
    if any(c in chosen for c in "&"):
        return chosen.upper()
    return chosen.title()
