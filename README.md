# Recurring Payment Detector

Recurring Payment Detector ingests bank exports, JSON records, pasted email
receipts, and `.eml` files, resolves noisy merchant names into canonical
services, detects unusual recurring charges, and shows cancellation guidance
for subscriptions.

The detector does not depend on a fixed subscription-price table. It learns
from the user's transaction history, groups variants such as `NETFLIX.COM`,
`NFLX DIGITAL`, and `NETFLX`, then flags amount changes that are unusual for
that merchant and category.

## Highlights

- CSV, JSON, manual row, pasted email, and `.eml` ingestion.
- Receipt-aware email parsing for merchant, amount, charge date, and action
  links.
- Entity resolution with exact aliases, fuzzy matching, and TF-IDF embedding
  matching.
- Recurring charge detection with category-aware thresholds.
- ML amount prediction with median fallback for thin history.
- Streamlit UI for ingesting data, reviewing detections, saving feedback, and
  exporting reports.
- Cancellation guidance from an Excel database.
- API-backed web research for unknown cancellation procedures, saved back into
  the workbook in the same database format.

## Quick Start

```bash
pip install -r requirements.txt
python tests.py
python tests_ingest.py
streamlit run app.py
```

Open the Streamlit URL shown in the terminal, usually:

```text
http://localhost:8501
```

## Configuration

Runtime state is stored locally and ignored by Git:

- `services.json`: learned canonical merchant registry
- `feedback.json`: saved user feedback

Optional environment variables:

```bash
# Use a specific cancellation workbook instead of the default search paths.
SUBSCRIPTION_CANCELLATION_XLSX=/path/to/subscription_cancellation_process.xlsx

# Enable API-backed web search for unknown cancellation policies.
OPENAI_API_KEY=your_api_key

# Optional; defaults to gpt-4.1-mini.
OPENAI_WEBSEARCH_MODEL=gpt-4.1-mini
```

On Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key"
$env:SUBSCRIPTION_CANCELLATION_XLSX="C:\Users\user\Downloads\subscription_cancellation_process.xlsx"
```

## Streamlit Workflow

The app supports these ingest paths:

| Tab | Input |
| --- | --- |
| CSV upload | Bank export with `merchant_raw`, `amount`, and `date` |
| JSON upload | Array of transactions or `{"transactions": [...]}` |
| Email | Pasted receipt text or uploaded `.eml` |
| Manual entry | Editable transaction table |
| Demo data | Built-in sample transaction history |

After data is loaded, click **Run detection** in the sidebar. The app shows:

- Loaded transaction preview
- Cancellation guidance for recognized subscriptions
- Alert table with severity, expected amount, actual amount, and reasons
- Merchant resolution details
- Per-alert feedback controls
- JSON and CSV export buttons

## Email and `.eml` Parsing

The email parser handles plain text and HTML receipts. It ranks receipt fields
to avoid common mistakes such as choosing subtotal, tax, refund, or promo
amounts instead of the actual charged total.

For Apple subscription confirmations and similar emails, it can identify the
real subscription from body structure, such as:

- `App -> iCloud`
- `Plan -> iCloud+ with 200 GB storage`
- `Renewal Price -> $3.99/month`
- `Date of Upgrade -> Sep 9, 2025`

The parser also extracts useful action links from `.eml` HTML, such as account,
purchase-history, billing, manage, and subscription links.

## Cancellation Guidance

Cancellation guidance is loaded in this order:

1. Excel workbook database
2. Built-in fallback guide for common services
3. Structured web-search fallback

By default, the app looks for:

```text
./subscription_cancellation_process.xlsx
~/Downloads/subscription_cancellation_process.xlsx
```

You can override this with `SUBSCRIPTION_CANCELLATION_XLSX`.

The workbook is expected to use the existing database-style columns:

| Column | Purpose |
| --- | --- |
| Provider | Service or company name |
| Market Position | Market coverage or contextual note |
| Price Range | Typical plan pricing |
| Billing Cycle | Monthly, annual, quarterly, etc. |
| Website | Vendor website |
| Cancellation Process | Detailed cancellation workflow |
| additional resources | Official URLs, support links, or source notes |

## API Web Search for Unknown Providers

For unknown providers, the app shows **Research with API and update database**.
When clicked, it:

1. Uses `OPENAI_API_KEY` with the OpenAI Responses API web-search tool.
2. Searches for current official cancellation instructions.
3. Formats the result into the same workbook schema.
4. Saves or updates a row in the `LLM Web Search` sheet.
5. Reloads the guide from the workbook.

The generated cancellation process is deliberately workbook-style, for example:

```text
Type 1 - Direct subscription
Direct link: https://example.com/account
Workflow:
1. Sign in.
2. Open Billing or Subscriptions.
3. Select Cancel or turn off auto-renewal.
4. Confirm and keep the confirmation email.

Watch-out:
If billed through Apple, Google Play, Amazon, PayPal, a mobile carrier, or
another partner, cancel through that billing provider.
```

The app does not run API web research silently on every page refresh. A user
must click the research button so API usage is explicit.

## Programmatic Usage

```python
from ingest import parse_csv, analyze

with open("charges.csv", encoding="utf-8") as f:
    parsed = parse_csv(f.read())

report = analyze(parsed.transactions, use_ml=True)

for alert in report.alerts:
    print(alert.merchant, alert.severity, alert.actual_amount)
```

Parse an `.eml` file:

```python
from pathlib import Path
from ingest.email_parser import parse_eml

extraction, parsed = parse_eml(Path("receipt.eml").read_bytes())

print(extraction.merchant_raw, extraction.amount, extraction.date)
print(parsed.transactions)
```

Research and save a cancellation procedure:

```python
from cancellation import research_and_update_cancellation_guide

guide = research_and_update_cancellation_guide("Example Vendor")
print(guide.service_name)
print(guide.cancellation_process)
```

## Pipeline

```text
raw transaction
  -> entity_resolver
  -> merchant registry and category
  -> recurring_detector
  -> category_rules
  -> ml_predictor or median fallback
  -> outlier_detector
  -> feedback_adjuster
  -> alert report
```

## File Map

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI for ingestion, detection, feedback, cancellation guidance, and exports |
| `cancellation.py` | Excel-backed cancellation database lookup plus API web-search update flow |
| `ingest/email_parser.py` | Receipt and `.eml` parsing |
| `ingest/parsers.py` | CSV, JSON, and record parsing into `Transaction` objects |
| `ingest/runner.py` | Structured analysis report builder |
| `ingest/serializers.py` | JSON and CSV export helpers |
| `models.py` | Core dataclasses |
| `entity_resolver.py` | Merchant identity resolution orchestrator |
| `merchant_normalizer.py` | Merchant cleaning and seed service aliases |
| `service_registry.py` | JSON-backed canonical merchant registry |
| `pipeline.py` | End-to-end detection pipeline |
| `recurring_detector.py` | Billing cycle and amount-tier detection |
| `ml_predictor.py` | Expected amount prediction |
| `outlier_detector.py` | Alert scoring and severity |
| `feedback_store.py` | Feedback persistence |
| `feedback_adjuster.py` | Feedback-based alert rescoring |
| `sample_data.py` | Demo transaction data |
| `templates/sample_transactions.csv` | Upload template |
| `tests.py` | Entity-resolution smoke tests |
| `tests_ingest.py` | Ingestion, `.eml`, cancellation, and analysis tests |

## Tests

```bash
python tests.py
python tests_ingest.py
```

Current coverage includes:

- Merchant text cleaning
- Exact alias, fuzzy, and embedding resolution
- Alias auto-learning
- Cross-variant grouping
- CSV and JSON ingestion
- Receipt and `.eml` parsing
- Apple/iCloud subscription parsing
- Cancellation database lookup
- API-researched row save/load behavior
- Analysis smoke test

## Security and Privacy

- Do not commit `services.json`, `feedback.json`, `.env`, or API keys.
- The app only calls the OpenAI API when the user clicks the research button.
- Unknown-provider API research should be reviewed before acting on cancellation
  instructions, especially for refunds, deadlines, and billing partners.
- The cancellation workbook can contain source URLs and support links; verify
  official domains before entering credentials.

## Limits

- ML training uses synthetic examples; retrain with labeled production data for
  sharper predictions.
- First-year utility users may see seasonal false positives until enough history
  exists.
- API web-search output is saved to the workbook but should still be reviewed
  for provider-specific terms and current refund policies.
