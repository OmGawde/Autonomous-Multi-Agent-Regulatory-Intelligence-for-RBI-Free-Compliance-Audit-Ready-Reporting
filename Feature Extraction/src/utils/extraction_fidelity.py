"""
Did we read the statement correctly?

`reconciliation.py` asks whether the engines agree with each other and with the
parsed ledger. It cannot tell whether that ledger matches the document, because
every number in it is derived from the same extraction. This module closes that
gap by comparing the parsed frame against what the bank printed (`anchors.py`).

Why it catches what the balance chain cannot:

- **Column swap.** Exchange the debit and credit columns and the running balance
  still reconciles, because the chain only constrains the net. Comparing Sum(debit)
  and Sum(credit) against their printed totals *separately* catches it at once.
- **Silently truncated statements.** A parse that stops after page 1 chains
  perfectly across the rows it kept. Only the printed closing balance or the
  transaction count reveals the rest is missing.

Verdicts:
  VERIFIED   -- at least one anchor existed and every applicable check passed
  FAILED     -- an anchor existed and disagreed beyond tolerance
  UNVERIFIED -- the statement printed nothing to check against

UNVERIFIED is a real answer, not a soft pass. ICICI prints no balances or totals
at all; claiming its numbers are confirmed would be a lie.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger("ExtractionFidelity")

# Same convention as reconciliation.py: absolute rupees, not a percentage.
TOLERANCE = 1.0


def _num(value, default=0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def check(df: pd.DataFrame, anchors, extraction_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compare the parsed frame against the statement's own printed facts.

    `anchors` is a StatementAnchors (or anything with the same attributes).
    Returns the same shape as reconciliation.check so the UI can render both
    with one component.
    """
    checks = []
    stats = extraction_stats or {}

    def record(name: str, passed: bool, expected, actual, detail: str = "") -> None:
        delta = None
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            delta = round(float(actual) - float(expected), 2)
        checks.append({
            "check": name,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
            "delta": delta,
            "detail": detail,
        })
        if not passed:
            logger.warning(
                f"Extraction fidelity FAILED {name}: expected {expected}, got {actual}. {detail}"
            )

    if df is None or df.empty:
        return {"status": "UNVERIFIED", "checks": [], "failed_count": 0,
                "anchors_found": 0, "reason": "no transactions to verify"}

    total_debits = float(df["debit"].sum()) if "debit" in df.columns else 0.0
    total_credits = float(df["credit"].sum()) if "credit" in df.columns else 0.0

    # --- money anchors -----------------------------------------------------
    # Checked separately on purpose: a debit/credit column swap leaves the net
    # untouched, so only the individual totals expose it.
    if anchors.total_debits is not None:
        expected = abs(_num(anchors.total_debits))
        record("debits_match_printed_total",
               abs(total_debits - expected) <= TOLERANCE, round(expected, 2), round(total_debits, 2),
               "sum of the debit column against the total printed on the statement")

    if anchors.total_credits is not None:
        expected = abs(_num(anchors.total_credits))
        record("credits_match_printed_total",
               abs(total_credits - expected) <= TOLERANCE, round(expected, 2), round(total_credits, 2),
               "sum of the credit column against the total printed on the statement")

    if anchors.closing_balance is not None and "balance" in df.columns:
        actual_close = _num(df["balance"].iloc[-1])
        expected = _num(anchors.closing_balance)
        record("closing_matches_printed",
               abs(actual_close - expected) <= TOLERANCE, round(expected, 2), round(actual_close, 2),
               "last parsed balance against the printed closing balance; a truncated "
               "statement chains perfectly but stops short")

    if anchors.opening_balance is not None and "balance" in df.columns:
        # Derived the same way balance.py does it, so the two agree.
        derived_open = _num(df["balance"].iloc[0]) + _num(df["debit"].iloc[0]) - _num(df["credit"].iloc[0])
        expected = _num(anchors.opening_balance)
        record("opening_matches_printed",
               abs(derived_open - expected) <= TOLERANCE, round(expected, 2), round(derived_open, 2),
               "opening balance implied by the first parsed row against the printed one; "
               "a lost first page shows up here")

    # The full printed equation, when a statement prints all four terms.
    if all(v is not None for v in (anchors.opening_balance, anchors.closing_balance,
                                   anchors.total_debits, anchors.total_credits)):
        implied = (_num(anchors.opening_balance)
                   - abs(_num(anchors.total_debits))
                   + abs(_num(anchors.total_credits)))
        record("printed_figures_are_self_consistent",
               abs(implied - _num(anchors.closing_balance)) <= TOLERANCE,
               round(_num(anchors.closing_balance), 2), round(implied, 2),
               "opening - total debits + total credits against the printed closing "
               "balance; a failure here means we misread the anchors, not the rows")

    # --- count anchors -----------------------------------------------------
    if anchors.expected_row_count is not None:
        record("row_count_matches_statement",
               len(df) == int(anchors.expected_row_count),
               int(anchors.expected_row_count), len(df),
               anchors.sources.get("expected_row_count", ""))

    if getattr(anchors, "serial_gaps", None):
        record("serial_run_unbroken", False,
               f"{anchors.serial_first}..{anchors.serial_last} with no gaps",
               f"{len(anchors.serial_gaps)} missing: {anchors.serial_gaps[:10]}",
               "gaps in the statement's own serial column localise the loss to a page")

    # --- structural anchors ------------------------------------------------
    if anchors.period_start and anchors.period_end and "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        if not dates.empty:
            first, last = dates.min().date().isoformat(), dates.max().date().isoformat()
            within = first >= anchors.period_start and last <= anchors.period_end
            record("dates_within_printed_period", within,
                   f"{anchors.period_start}..{anchors.period_end}", f"{first}..{last}",
                   "parsed dates must fall inside the period the statement declares")

    if anchors.pages_declared and anchors.pages_actual:
        record("page_count_matches_declared",
               int(anchors.pages_declared) == int(anchors.pages_actual),
               int(anchors.pages_declared), int(anchors.pages_actual),
               "'Page N of M' against the pages actually present")

    # --- extraction-side signals ------------------------------------------
    if "balance_chain_mismatches" in stats:
        mismatches = int(stats.get("balance_chain_mismatches") or 0)
        record("balance_chain_intact", mismatches == 0, 0, mismatches,
               "rows where balance != previous - debit + credit after intra-day reordering")

    # Everything above compares against the document. What follows are hints
    # about *how* the parse was produced, and the document wins over the hint:
    # if the printed figures confirm the rows, it does not matter which template
    # produced them or that a trailing page held no table.
    anchors_found = sum(v is not None for v in (
        anchors.opening_balance, anchors.closing_balance, anchors.total_debits,
        anchors.total_credits, anchors.expected_row_count))
    anchor_checks_all_passed = anchors_found > 0 and all(c["passed"] for c in checks)

    if stats.get("template_fallback"):
        record("bank_template_available", anchor_checks_all_passed,
               f"a template for {stats.get('requested_bank')}", "generic 'Other' template",
               "column mapping was a guess. The printed figures confirm it parsed correctly "
               "anyway." if anchor_checks_all_passed else
               "column mapping is a guess and nothing on the statement confirms it. "
               "Calibrate this bank.")

    empty_pages = list(stats.get("pages_without_tables_index") or [])
    if empty_pages:
        total_pages = int(stats.get("pages_total") or 0)
        # A single trailing page without a table is ordinary -- end-of-statement
        # markers, legends and terms pages all look like this. Axis page 14 is
        # literally "++++ End of Statement ++++".
        benign_trailing = len(empty_pages) == 1 and empty_pages[0] == total_pages - 1
        record("every_page_yielded_rows", benign_trailing or anchor_checks_all_passed,
               f"{total_pages} page(s) with tables",
               f"{len(empty_pages)} without (indices {empty_pages[:8]})",
               "a single trailing page without a table is normal" if benign_trailing else
               "pages produced no table; if several are missing the statement is truncated")

    failed = [c for c in checks if not c["passed"]]

    if failed:
        status = "FAILED"
    elif anchors_found:
        status = "VERIFIED"
    else:
        status = "UNVERIFIED"

    return {
        "status": status,
        "checks": checks,
        "failed_count": len(failed),
        "anchors_found": anchors_found,
        "anchors": anchors.to_dict() if hasattr(anchors, "to_dict") else {},
        "reason": "" if anchors_found else
                  "this statement prints no balances, totals or serial column to check against",
    }
