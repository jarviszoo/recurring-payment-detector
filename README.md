# Recurring Payment Detector

An AI-powered subscription anomaly detector that turns noisy, raw transaction
data (from emails or Open Banking APIs) into a structured database of
canonical services, then flags charges that look unusual for a given user.

The system **does not rely on a hardcoded subscription price database**. It
learns each user's recurring patterns and resolves merchant identities
automatically from the transactions themselves — handling typos, formatting
variants, and previously-unseen vendors.

## What it does

1. **Resolves identity** — `NETFLIX.COM 866-579-7172`, `NFLX DIGITAL`,
   `Netflx.com`, and `Netflix LOS GATOS CA` all collapse to the canonical
   service `Netflix`.
2. **Discovers new services** — vendors not in the registry are auto-created
   as low-confidence entries. Periodic clustering merges duplicates.
3. **Detects recurring patterns** — splits transactions by amount tier and
   billing cycle (e.g. Apple's $2.99 iCloud and $9.99 Music as separate
   sub-patterns).
4. **Predicts expected amounts** — gradient-boosted regression with quantile
   confidence intervals; falls back to the median when prior history is too
   thin or too volatile to be useful.
5. **Flags anomalies with category-aware thresholds** — utilities and telecom
   tolerate more variance than streaming or news.
6. **Learns from user feedback** — alerts marked "expected" raise the
   tolerance for that merchant; "unexpected" keeps it sharp.

## Pipeline

```
raw transaction
     ↓
[ Phase 0 ] entity_resolver
     ↓                        ↓
   clean()                  service_registry  ← persisted to services.json
     ↓                        ↑
   exact alias  ──────────────┤
     ↓ miss                   │
   fuzzy_matcher (rapidfuzz)  │
     ↓ miss                   │
   embedding_matcher (TF-IDF) │
     ↓ miss                   │
   auto-create (low confidence) ─┘
     ↓
canonical service + category
     ↓
[ Phase 1 ] recurring_detector  → cluster by amount tier, detect billing cycle
     ↓
[ Phase 2 ] category_rules      → choose per-category thresholds
     ↓
[ Phase 3 ] ml_predictor        → expected amount + 10/90 quantile CI
     ↓
[ Phase 4 ] outlier_detector    → severity scoring
     ↓
            feedback_adjuster   → re-score using stored user feedback
     ↓
        Alert (high / warning / low)
```

## Quick start

```bash
pip install -r requirements.txt
python main.py        # full demo across all phases
python tests.py       # 31 assertions covering the resolver
```

The demo runs three passes:

- **Pass A** — cold start: empty registry → seeded with ~27 well-known
  services → resolves a noisy transaction batch → auto-learns aliases.
- **Pass B** — anomaly detection with no feedback yet.
- **Pass C** — simulates user feedback (expected / unexpected) and re-runs
  detection to show how scores shift.

## File map

| File | Purpose |
|---|---|
| `models.py` | Dataclasses: `Transaction`, `CanonicalService`, `ResolutionResult`, `RecurringPattern`, `PredictionResult`, `Alert`, `FeedbackEntry` |
| `merchant_normalizer.py` | `clean()` — regex strip / Unicode normalize, preserves `& + . /` for brand fidelity. Holds `SEED_SERVICES` for cold-start. |
| `service_registry.py` | Persistent canonical-service DB (JSON). CRUD, alias merging, confidence tracking, `bootstrap_seed()`. |
| `fuzzy_matcher.py` | rapidfuzz `token_set_ratio` + `ratio` against canonical names + learned aliases. |
| `embedding_matcher.py` | TF-IDF char n-gram (2–4) cosine similarity index, lazily rebuilt. |
| `clusterer.py` | DBSCAN clustering of unresolved merchants into candidate services. |
| `entity_resolver.py` | Multi-stage resolution orchestrator (exact → fuzzy → embedding → corroborated → auto-create). |
| `category_classifier.py` | MCC code → alias-table → keyword-regex layered classifier. |
| `category_rules.py` | Per-category thresholds, lookback, seasonal flag, extra reason hints. |
| `recurring_detector.py` | Billing-cycle scoring (weekly / biweekly / monthly / quarterly / annual), amount clustering. |
| `feature_extractor.py` | 14-dim feature vector for the ML predictor. |
| `synthetic_training.py` | Generates 2000 labeled training examples across 7 realistic subscription patterns. |
| `ml_predictor.py` | Three `GradientBoostingRegressor` models (median + 10th + 90th quantile) with confidence-based fallback. |
| `outlier_detector.py` | Threshold check, outlier scoring, severity bands, category-specific reason hints. |
| `feedback_store.py` | JSON-backed user feedback persistence. |
| `feedback_adjuster.py` | Re-scores alerts using prior feedback (raises tolerance for confirmed-expected merchants). |
| `pipeline.py` | Wires Phase 0–4 together: `run(transactions, use_ml=True) -> [Alert]`. |
| `sample_data.py` | 40 hand-crafted transactions covering every detection scenario. |
| `main.py` | End-to-end demo runner. |
| `tests.py` | 31 smoke assertions (text cleaning, all resolution paths, alias auto-learning, clustering). |

## Data model

### `CanonicalService`

```python
service_id          str       # UUID prefix
canonical_name      str       # "Netflix"
category            str       # "streaming"
aliases             list[str] # ["netflix", "nflx", "netflix com", ...]
first_seen          date
last_seen           date
transaction_count   int
confidence          float     # 0–1
source              str       # "manual" | "auto" | "fuzzy" | "embedding" | "cluster"
```

Persisted to `services.json` (gitignored). New aliases are auto-attached
when a fuzzy / embedding match scores ≥ 0.80, so the registry learns variant
spellings without explicit labels.

### `ResolutionResult`

```python
raw             str               # original bank string
cleaned         str               # post-regex
canonical_name  str | None        # None if unresolved
service_id      str | None
category        str | None
method          str               # "exact_alias" | "fuzzy" | "embedding"
                                  # | "fuzzy+embedding" | "new_service" | "unresolved"
confidence      float             # 0–1
candidates      list[(name, score)]   # top-N alternatives for traceability
```

### `Alert`

```python
transaction          Transaction
normalized_merchant  str
expected_amount      float
actual_amount        float
difference           float
percentage_change    float
severity             str        # "low" | "warning" | "high"
outlier_score        float      # 0–1
prediction           PredictionResult   # method + CI + confidence
possible_reasons     list[str]
feedback_adjusted    bool
```

## Resolution thresholds

| Signal | High accept | Corroborated accept |
|---|---|---|
| rapidfuzz token-set / ratio | ≥ 0.92 | ≥ 0.80 if embedding agrees |
| TF-IDF cosine | ≥ 0.75 | ≥ 0.55 if fuzzy agrees |
| Auto-attach alias | confidence ≥ 0.80 | — |
| Auto-create new service | always (when nothing else accepts) | starting confidence 0.30 |

Thresholds live at the top of `entity_resolver.py` — tune them to trade
precision against recall.

## Outlier thresholds

Universal tier-based defaults; categories can override.

| Expected amount | Min $ diff | Min % change |
|---|---|---|
| < $20 | $3 | 20% |
| $20 – $100 | $10 | 15% |
| > $100 | $25 | 10% |

| Category | Override |
|---|---|
| `telecom` | $15 + 25% (taxes / roaming variance) |
| `utilities` | $20 + 30%, seasonal lookup of same-month-prior-year |
| `software` | $5 + 10% (seat / annual flips) |
| `streaming`, `music`, `news`, `cloud_storage`, `gaming`, `fitness`, `app_store`, `mixed_commerce`, `delivery` | each tuned in `category_rules.py` |

## ML predictor

Three `GradientBoostingRegressor` models trained at startup on 2000 synthetic
subscription histories covering: stable recurring, gradual price creep,
sudden plan upgrade, discount expiry, monthly→annual conversion, telecom
variance, and seasonal utility patterns.

| Model | Loss | Role |
|---|---|---|
| Median | `squared_error` | Point prediction |
| Lower | `quantile, alpha=0.10` | 10th-percentile bound |
| Upper | `quantile, alpha=0.90` | 90th-percentile bound |

Falls back to the simple median predictor when:

- fewer than 3 prior charges in the cluster, or
- the ML interval is too wide (confidence < 0.50 → `1 - (upper-lower)/expected`)

## Feedback loop

Each alert can be marked `expected`, `unexpected`, `cancel`, or
`remind_later`. Feedback is appended to `feedback.json`. On the next
detection pass, `feedback_adjuster.adjust()` computes a per-merchant
tolerance multiplier:

- `+0.25` per prior `expected` (capped at 3×)
- `−0.15` per prior `unexpected` / `cancel` (floored at 1×)

The outlier score is divided by the multiplier; severity may drop from
`high` → `warning` or be suppressed entirely.

## Tech stack

- **Python 3.10+**
- `scikit-learn` — `TfidfVectorizer`, `DBSCAN`, `GradientBoostingRegressor`
- `rapidfuzz` — token-set + edit-distance string scoring
- `numpy` — feature vectors and array math
- JSON files (`services.json`, `feedback.json`) for persistence — no DB
  dependency

## Tests

```bash
python tests.py
```

Runs 31 assertions across:

- Text cleaning (preservation of `&` in `PG&E`, `AT&T`)
- Exact alias resolution
- Fuzzy resolution of typos (`NETFLX`, `NETFLIIX`)
- Embedding resolution of variants (`PG E AUTOPAY` → `PG&E`)
- New-service creation for unknown vendors
- Alias auto-learning (second `NETFLX` hits `exact_alias`)
- Cross-variant grouping (5 Netflix variants → one canonical)
- DBSCAN clustering of duplicate strings

## Limits & next steps

- Synthetic training only — once real labeled data is available, retrain on
  it for sharper quantile bounds.
- Same-month-prior-year seasonal blend needs ≥ 12 months of history to
  shine; first-year users will see one-off seasonal alerts that resolve
  themselves once feedback arrives.
- Fuzzy / embedding thresholds are conservative; users in domains with
  many similarly-named merchants (e.g. local utilities) should tune them
  down and add more `SEED_SERVICES` entries to disambiguate.
- No streaming / online deployment — the registry is read on every
  resolve. For production scale, swap the JSON store for SQLite or a
  proper KV store and cache the embedding index in memory.
