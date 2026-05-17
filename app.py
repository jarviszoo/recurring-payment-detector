"""
Streamlit UI for ingesting transactions and running recurring-payment detection.

Run:  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path when launched via streamlit
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
import pandas as pd

from datetime import date

from models import Transaction
from sample_data import NOISY_EXTRAS, SAMPLE_TRANSACTIONS
from cancellation import (
    CancellationGuide,
    WebSearchCancellationError,
    get_cancellation_guide,
    research_and_update_cancellation_guide,
)
from ingest.parsers import parse_csv, parse_json, parse_records, transactions_to_records
from ingest.email_parser import parse_email_text, parse_eml
from ingest.runner import analyze, AnalysisReport
from ingest.serializers import alerts_to_csv, alerts_to_json, report_to_json, resolutions_to_csv
import feedback_store

TEMPLATE_CSV = _ROOT / "templates" / "sample_transactions.csv"
VALID_FEEDBACK = ("expected", "unexpected", "cancel", "remind_later")

st.set_page_config(
    page_title="Recurring Payment Detector",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .severity-high { color: #c0392b; font-weight: 600; }
    .severity-warning { color: #d68910; font-weight: 600; }
    .severity-low { color: #2874a6; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_state() -> None:
    defaults = {
        "transactions": [],
        "report": None,
        "parse_errors": [],
        "parse_warnings": [],
        "email_action_links": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _set_transactions(
    txns: list[Transaction],
    errors: list[str],
    warnings: list[str],
    *,
    email_action_links: list[dict[str, str]] | None = None,
) -> None:
    st.session_state.transactions = txns
    st.session_state.parse_errors = errors
    st.session_state.parse_warnings = warnings
    st.session_state.email_action_links = email_action_links or []
    st.session_state.report = None


def _severity_badge(sev: str) -> str:
    css = {"high": "severity-high", "warning": "severity-warning", "low": "severity-low"}.get(sev, "")
    return f'<span class="{css}">{sev.upper()}</span>'


def _render_cancellation_guide(guide: CancellationGuide) -> None:
    source_labels = {
        "xlsx_database": "spreadsheet database",
        "built_in_database": "built-in database",
        "web_search": "web-search fallback",
    }
    source = source_labels.get(guide.source, guide.source)
    st.caption(f"Matched via {source} ({guide.confidence:.2f} confidence).")

    details = [
        ("Provider", guide.service_name),
        ("Category", guide.category),
        ("Market Position", guide.market_position),
        ("Price Range", guide.price_range),
        ("Billing Cycle", guide.billing_cycle),
        ("Website", guide.website),
    ]
    visible_details = [{"Field": k, "Value": v} for k, v in details if v]
    if visible_details:
        st.dataframe(pd.DataFrame(visible_details), use_container_width=True, hide_index=True)

    links: list[str] = []
    if guide.manage_url:
        links.append(f"[Open manage/cancel page]({guide.manage_url})")
    if guide.source_url:
        links.append(f"[Official instructions]({guide.source_url})")
    links.append(f"[Web search]({guide.search_url})")
    st.markdown(" | ".join(links))

    if guide.cancellation_process:
        st.text(guide.cancellation_process)
    elif guide.steps:
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(guide.steps, 1)))
    if guide.additional_resources and guide.additional_resources != guide.source_url:
        with st.expander("Additional resources"):
            st.text(guide.additional_resources)
    if guide.notes:
        st.caption(" ".join(guide.notes))


def _render_research_button(merchant: str, category: str | None = None) -> None:
    key_base = f"research_{merchant}_{category or ''}".replace(" ", "_").replace("/", "_")
    if st.button("Research with API and update database", key=key_base):
        with st.spinner("Searching official sources and updating the cancellation database..."):
            try:
                researched = research_and_update_cancellation_guide(merchant, category=category)
            except WebSearchCancellationError as exc:
                st.error(str(exc))
                st.caption("Set `OPENAI_API_KEY` and try again. Optional: set `OPENAI_WEBSEARCH_MODEL`.")
                return
        st.success(f"Saved cancellation procedure for {researched.service_name}.")
        _render_cancellation_guide(researched)


def _render_ingest_tabs() -> None:
    tab_csv, tab_json, tab_email, tab_manual, tab_demo = st.tabs(
        ["CSV upload", "JSON upload", "Email", "Manual entry", "Demo data"]
    )

    with tab_csv:
        st.caption("Columns: `merchant_raw` (or merchant/description), `amount`, `date` (YYYY-MM-DD). Optional: `transaction_id`, `category_mcc`.")
        if TEMPLATE_CSV.exists():
            st.download_button(
                "Download sample CSV template",
                data=TEMPLATE_CSV.read_bytes(),
                file_name="sample_transactions.csv",
                mime="text/csv",
            )
        uploaded = st.file_uploader("Upload CSV", type=["csv"], key="csv_up")
        if uploaded is not None:
            result = parse_csv(uploaded.getvalue())
            if result.transactions:
                _set_transactions(result.transactions, result.errors, result.warnings)
                st.success(f"Loaded {len(result.transactions)} transaction(s).")
            for err in result.errors:
                st.error(err)
            for w in result.warnings:
                st.warning(w)

    with tab_json:
        st.caption('JSON array or `{"transactions": [...]}` with the same fields as CSV.')
        uploaded = st.file_uploader("Upload JSON", type=["json"], key="json_up")
        pasted = st.text_area("Or paste JSON", height=120, key="json_paste")
        if uploaded is not None:
            result = parse_json(uploaded.getvalue())
            if result.transactions:
                _set_transactions(result.transactions, result.errors, result.warnings)
                st.success(f"Loaded {len(result.transactions)} transaction(s).")
            for err in result.errors:
                st.error(err)
        elif pasted.strip():
            if st.button("Parse pasted JSON", key="parse_json_btn"):
                result = parse_json(pasted)
                if result.transactions:
                    _set_transactions(result.transactions, result.errors, result.warnings)
                    st.success(f"Loaded {len(result.transactions)} transaction(s).")
                for err in result.errors:
                    st.error(err)

    with tab_email:
        st.caption("Paste receipt text or upload a `.eml` file. Review detected merchant/amount before analyzing.")
        eml_file = st.file_uploader("Upload .eml", type=["eml"], key="eml_up")
        subject = st.text_input("Email subject (optional)", key="email_subj")
        body = st.text_area("Email body", height=160, key="email_body")
        c1, c2, c3 = st.columns(3)
        with c1:
            merchant_ov = st.text_input("Merchant override", key="email_merch")
        with c2:
            amount_ov = st.number_input("Amount override", min_value=0.0, value=0.0, step=0.01, key="email_amt")
        with c3:
            date_ov = st.date_input("Charge date", value=date.today(), key="email_date")

        if eml_file is not None:
            extraction, result = parse_eml(eml_file.getvalue())
            if extraction:
                detected_bits = []
                if extraction.merchant_raw:
                    detected_bits.append(f"merchant: {extraction.merchant_raw}")
                if extraction.amount is not None:
                    detected_bits.append(f"amount: ${extraction.amount:.2f}")
                if extraction.date is not None:
                    detected_bits.append(f"date: {extraction.date.isoformat()}")
                detected = ", ".join(detected_bits) if detected_bits else "no charge details"
                st.info(f"Detected from .eml: {detected}. Subject: {extraction.subject[:80]!r}")
                if extraction.action_links:
                    with st.expander("Action links found in email"):
                        for link in extraction.action_links:
                            st.markdown(f"- [{link['label']}]({link['url']})")
            if result.transactions:
                _set_transactions(
                    result.transactions,
                    result.errors,
                    result.warnings,
                    email_action_links=extraction.action_links if extraction else None,
                )
                st.success(f"Loaded {len(result.transactions)} transaction(s) from email.")
            for err in result.errors:
                st.error(err)
            for w in result.warnings:
                st.warning(w)

        if st.button("Parse pasted email", key="parse_email_btn"):
            amt = amount_ov if amount_ov > 0 else None
            merch = merchant_ov.strip() or None
            result = parse_email_text(
                body,
                subject=subject,
                merchant_override=merch,
                amount_override=amt,
                date_override=date_ov,
            )
            if result.transactions:
                _set_transactions(result.transactions, result.errors, result.warnings)
                st.success(f"Loaded {len(result.transactions)} transaction(s).")
            for err in result.errors:
                st.error(err)
            for w in result.warnings:
                st.warning(w)

    with tab_manual:
        st.caption("Add rows below, then click **Apply manual rows**.")
        default = pd.DataFrame(
            [
                {"merchant_raw": "NETFLIX.COM", "amount": 15.49, "date": "2026-01-01", "category_mcc": ""},
                {"merchant_raw": "NETFLIX.COM", "amount": 15.49, "date": "2026-02-01", "category_mcc": ""},
            ]
        )
        edited = st.data_editor(
            default,
            num_rows="dynamic",
            use_container_width=True,
            key="manual_editor",
        )
        if st.button("Apply manual rows", key="apply_manual"):
            records = edited.fillna("").to_dict(orient="records")
            result = parse_records(records)
            if result.transactions:
                _set_transactions(result.transactions, result.errors, result.warnings)
                st.success(f"Loaded {len(result.transactions)} transaction(s).")
            for err in result.errors:
                st.error(err)

    with tab_demo:
        st.write("Load the built-in demo dataset (sample + noisy merchants).")
        if st.button("Load demo transactions", key="load_demo"):
            demo = SAMPLE_TRANSACTIONS + NOISY_EXTRAS
            _set_transactions(demo, [], [])
            st.success(f"Loaded {len(demo)} demo transactions.")


def _render_sidebar() -> tuple[bool, bool, bool, bool]:
    st.sidebar.header("Analysis")
    use_ml = st.sidebar.checkbox("Use ML predictor", value=True)
    reset_registry = st.sidebar.checkbox("Reset merchant registry", value=False)
    reset_feedback = st.sidebar.checkbox("Reset saved feedback", value=False)
    st.sidebar.divider()
    run = st.sidebar.button("Run detection", type="primary", use_container_width=True)
    return use_ml, reset_registry, reset_feedback, run


def _render_loaded_preview() -> None:
    txns = st.session_state.transactions
    if not txns:
        st.info("No transactions loaded yet. Use a tab above to ingest data.")
        return

    st.subheader(f"Loaded transactions ({len(txns)})")
    df = pd.DataFrame(transactions_to_records(txns))
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.session_state.parse_warnings:
        for w in st.session_state.parse_warnings:
            st.warning(w)

    guides: dict[str, CancellationGuide] = {}
    source_priority = {"xlsx_database": 0, "built_in_database": 1, "web_search": 2}
    for txn in txns:
        guide = get_cancellation_guide(txn.merchant_raw)
        existing = guides.get(guide.service_name)
        if existing is None or source_priority.get(guide.source, 3) < source_priority.get(existing.source, 3):
            guides[guide.service_name] = guide

    if guides:
        st.subheader("Cancellation guidance")
        if st.session_state.email_action_links:
            with st.expander("Links from uploaded email"):
                for link in st.session_state.email_action_links:
                    st.markdown(f"- [{link['label']}]({link['url']})")
        source_order = {"xlsx_database": 0, "built_in_database": 1, "web_search": 2}
        for guide in sorted(guides.values(), key=lambda g: (source_order.get(g.source, 3), g.service_name)):
            with st.expander(f"{guide.service_name}: how to cancel"):
                _render_cancellation_guide(guide)
                if guide.source == "web_search":
                    _render_research_button(guide.service_name, guide.category or None)


def _render_report(report: AnalysisReport) -> None:
    st.subheader("Results")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Transactions", report.transaction_count)
    m2.metric("Alerts", report.alert_count)
    m3.metric("High severity", report.summary_by_severity.get("high", 0))
    m4.metric("Services in registry", report.service_count)

    if report.alert_count == 0:
        st.success("No unusual charges detected for the loaded history.")
    else:
        alert_df = pd.DataFrame([a.to_dict() for a in report.alerts])
        if "possible_reasons" in alert_df.columns:
            alert_df["possible_reasons"] = alert_df["possible_reasons"].apply(
                lambda x: "; ".join(x) if isinstance(x, list) else x
            )
        st.dataframe(alert_df, use_container_width=True, hide_index=True)

        with st.expander("Alert details (formatted)"):
            for i, block in enumerate(report.formatted_alerts, 1):
                st.text(block)
                if i < len(report.formatted_alerts):
                    st.divider()

        st.subheader("Feedback")
        st.caption("Mark alerts to tune future runs (saved to feedback.json).")
        for idx, alert_rec in enumerate(report.alerts):
            cols = st.columns([3, 2, 2, 2])
            cols[0].markdown(
                f"{_severity_badge(alert_rec.severity)} **{alert_rec.merchant}** — ${alert_rec.actual_amount:.2f}",
                unsafe_allow_html=True,
            )
            choice = cols[1].selectbox(
                "Feedback",
                VALID_FEEDBACK,
                key=f"fb_{idx}_{alert_rec.transaction_id}",
                label_visibility="collapsed",
            )
            note = cols[2].text_input("Note", key=f"fb_note_{idx}", label_visibility="collapsed")
            if cols[3].button("Save", key=f"fb_save_{idx}"):
                from models import Alert, Transaction, PredictionResult
                from datetime import date as date_cls

                dummy_txn = Transaction(
                    alert_rec.transaction_id,
                    alert_rec.raw_merchant,
                    alert_rec.actual_amount,
                    date_cls.fromisoformat(alert_rec.charge_date),
                )
                dummy_alert = Alert(
                    transaction=dummy_txn,
                    normalized_merchant=alert_rec.merchant,
                    expected_amount=alert_rec.expected_amount,
                    actual_amount=alert_rec.actual_amount,
                    difference=alert_rec.difference,
                    percentage_change=alert_rec.percentage_change,
                    severity=alert_rec.severity,
                    outlier_score=alert_rec.outlier_score,
                    possible_reasons=alert_rec.possible_reasons,
                    prediction=PredictionResult(
                        expected=alert_rec.expected_amount,
                        lower_bound=alert_rec.ci_lower or alert_rec.expected_amount,
                        upper_bound=alert_rec.ci_upper or alert_rec.expected_amount,
                        confidence=alert_rec.prediction_confidence or 0.0,
                        method=alert_rec.prediction_method or "median",
                    ),
                )
                feedback_store.record(dummy_alert, alert_rec.category, choice, note=note)
                st.toast(f"Saved feedback for {alert_rec.merchant}")
            if choice == "cancel":
                guide = get_cancellation_guide(alert_rec.merchant, category=alert_rec.category)
                with st.expander(f"How to cancel {guide.service_name}", expanded=True):
                    _render_cancellation_guide(guide)
                    if guide.source == "web_search":
                        _render_research_button(alert_rec.merchant, alert_rec.category)

    st.subheader("Merchant resolution")
    if report.resolutions:
        st.dataframe(pd.DataFrame(report.resolutions), use_container_width=True, hide_index=True)

    st.subheader("Export")
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "Download full report (JSON)",
        data=report_to_json(report),
        file_name="detection_report.json",
        mime="application/json",
    )
    c2.download_button(
        "Download alerts (CSV)",
        data=alerts_to_csv(report),
        file_name="alerts.csv",
        mime="text/csv",
    )
    c3.download_button(
        "Download resolutions (CSV)",
        data=resolutions_to_csv(report),
        file_name="resolutions.csv",
        mime="text/csv",
    )


def main() -> None:
    _init_state()
    st.title("Recurring Payment Detector")
    st.write(
        "Ingest bank or receipt data, resolve merchants, and flag unusual recurring charges. "
        "Supports CSV, JSON, email paste, and manual entry."
    )

    use_ml, reset_registry, reset_feedback, run_clicked = _render_sidebar()
    _render_ingest_tabs()
    st.divider()
    _render_loaded_preview()

    if run_clicked:
        if not st.session_state.transactions:
            st.sidebar.error("Load transactions first.")
        else:
            with st.spinner("Training ML model and analyzing…"):
                report = analyze(
                    st.session_state.transactions,
                    use_ml=use_ml,
                    reset_registry=reset_registry,
                    reset_feedback=reset_feedback,
                )
            st.session_state.report = report

    if st.session_state.report is not None:
        st.divider()
        _render_report(st.session_state.report)


if __name__ == "__main__":
    main()
