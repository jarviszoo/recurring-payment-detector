"""
End-to-end email evaluator.

Takes raw email text → parsed fields → entity-resolved service →
price-tier evaluation → human-readable verdict.

Designed to be called from a CLI, a notebook, or a future web UI.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import email_parser
import entity_resolver
import price_lookup
import service_registry
from db_loader import load_providers, to_seed_tuples
from merchant_normalizer import SEED_SERVICES


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

@dataclass
class EmailEvaluation:
    parsed: email_parser.ParsedEmail
    chosen_candidate: Optional[str] = None
    resolution: Optional[object] = None              # ResolutionResult
    candidates_tried: list[tuple[str, str, float]] = field(default_factory=list)
    price_eval: Optional[price_lookup.PriceEvaluation] = None
    verdict_summary: str = ""                         # one-line human-readable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_registry_initialised = False


def ensure_registry_loaded() -> None:
    """Populate the registry from providers.db on first call (DB is source of truth)."""
    global _registry_initialised
    if _registry_initialised:
        return
    # Wipe any stale state from previous demo runs, then rebuild
    service_registry.clear()
    try:
        providers = load_providers()
        service_registry.bootstrap_seed(to_seed_tuples(providers))
    except Exception:
        # DB unavailable — fall back to the small hand-curated SEED list
        service_registry.bootstrap_seed(SEED_SERVICES)
    _registry_initialised = True


def evaluate_email(email_text: str) -> EmailEvaluation:
    """Full pipeline: parse text, resolve merchant, look up price tier, render verdict."""
    ensure_registry_loaded()

    parsed = email_parser.parse(email_text)
    result = EmailEvaluation(parsed=parsed)

    if not parsed.merchant_candidates:
        result.verdict_summary = "No merchant candidate could be extracted from this email."
        return result

    # Try each candidate; pick the highest-confidence resolution
    best_res = None
    best_cand = None
    for cand in parsed.merchant_candidates:
        res = entity_resolver.resolve(cand, txn_date=parsed.charge_date, auto_create=False)
        result.candidates_tried.append((cand, res.method, res.confidence))
        if res.canonical_name is None:
            continue
        if best_res is None or res.confidence > best_res.confidence:
            best_res = res
            best_cand = cand

    if best_res is None or best_res.canonical_name is None:
        result.verdict_summary = (
            f"Could not confidently resolve any merchant candidate "
            f"({', '.join(parsed.merchant_candidates[:3])}...) against the provider database."
        )
        return result

    result.chosen_candidate = best_cand
    result.resolution = best_res

    if parsed.amount is None:
        result.verdict_summary = (
            f"Resolved to {best_res.canonical_name} (confidence {best_res.confidence:.2f}), "
            f"but no amount was found in the email."
        )
        return result

    # Look up price tiers
    pe = price_lookup.evaluate(
        canonical_name=best_res.canonical_name,
        charge_amount=parsed.amount,
        billing_cycle=parsed.billing_cycle or "monthly",
    )
    result.price_eval = pe
    result.verdict_summary = _render_verdict(best_res, pe, parsed)
    return result


# ---------------------------------------------------------------------------
# Verdict rendering
# ---------------------------------------------------------------------------

_VERDICT_TAG = {
    "match":         "[NORMAL]",
    "unknown_tier":  "[CHECK]",
    "price_hike":    "[ALERT]",
    "below_known":   "[BELOW]",
    "no_data":       "[?]",
}


def _render_verdict(res, pe: price_lookup.PriceEvaluation, parsed) -> str:
    tag = _VERDICT_TAG.get(pe.verdict, "[?]")
    cycle = parsed.billing_cycle or "monthly"
    return (
        f"{tag} {res.canonical_name} ({res.category}) "
        f"${parsed.amount:.2f}/{cycle} on {parsed.charge_date or '?'} — {pe.explanation}"
    )


# ---------------------------------------------------------------------------
# Pretty printer for the CLI / demo
# ---------------------------------------------------------------------------

def format_report(ev: EmailEvaluation) -> str:
    p = ev.parsed
    lines = [
        "=" * 64,
        "EMAIL ANALYSIS",
        "=" * 64,
    ]
    if p.sender:
        lines.append(f"  Sender:        {p.sender}")
    if p.subject:
        lines.append(f"  Subject:       {p.subject}")
    if p.charge_date:
        lines.append(f"  Date:          {p.charge_date}")
    if p.amount is not None:
        lines.append(f"  Amount:        ${p.amount:.2f} {p.currency}")
    if p.billing_cycle:
        lines.append(f"  Billing:       {p.billing_cycle}")
    if p.plan_tier:
        lines.append(f"  Plan keyword:  {p.plan_tier}")
    lines.append("")
    lines.append("  Merchant candidates extracted:")
    for c in p.merchant_candidates:
        lines.append(f"    - {c!r}")
    lines.append("")
    if ev.candidates_tried:
        lines.append("  Resolution attempts:")
        for cand, method, conf in ev.candidates_tried:
            lines.append(f"    {cand!r:<40s} -> {method:<14s} conf={conf:.2f}")
        lines.append("")
    if ev.resolution and ev.resolution.canonical_name:
        lines.append(f"  RESOLVED:      {ev.resolution.canonical_name} "
                     f"({ev.resolution.category}) via {ev.resolution.method} "
                     f"@ {ev.resolution.confidence:.2f}")
    if ev.price_eval:
        pe = ev.price_eval
        lines.append("")
        lines.append("  PRICE EVALUATION")
        lines.append(f"    Verdict:        {pe.verdict}")
        lines.append(f"    Explanation:    {pe.explanation}")
        if pe.closest_tier:
            lines.append(f"    Closest tier:   {pe.closest_tier.tier_name} "
                         f"(${pe.closest_tier_price:.2f} {pe.matched_cycle_field})")
        if pe.all_tiers:
            lines.append("    Known tiers for this service:")
            for t in pe.all_tiers:
                bits = []
                if t.price_monthly:   bits.append(f"${t.price_monthly:.2f}/mo")
                if t.price_annual:    bits.append(f"${t.price_annual:.2f}/yr")
                if t.price_quarterly: bits.append(f"${t.price_quarterly:.2f}/qtr")
                promo = " (PROMO)" if t.is_promo else ""
                lines.append(f"      - {t.tier_name:<22s}{', '.join(bits)}{promo}")
    lines.append("")
    lines.append(f"  >>> {ev.verdict_summary}")
    lines.append("=" * 64)
    return "\n".join(lines)
