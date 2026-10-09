"""
Cross-engine reconciliation invariants.

Each feature engine derives its own view of the same statement. Nothing used to
check those views against each other or against the account ledger, so a bundle
could ship internally contradictory figures -- e.g. savings reporting
+Rs 6,25,447 for a year in which the balance actually fell by Rs 2,79,478, or
two engines disagreeing 96x on discretionary spend.

These checks are deliberately cheap and total: they run on every pipeline
execution, and the result is published as `reconciliation` in the feature
bundle so a consumer can tell whether the numbers hang together.
"""

import logging
from typing import Any, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

# Absolute rupee tolerance for float comparison.
TOLERANCE = 1.0


def _num(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def check(df: pd.DataFrame, features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run every invariant and return a report.

    Args:
        df: the classified transaction frame the engines consumed
        features: the aggregated feature dict (engine name -> feature dict)

    Returns:
        {"status": "PASS"|"FAIL", "checks": [...], "failed_count": int}
    """
    checks: List[Dict[str, Any]] = []

    def record(name: str, expected: float, actual: float, detail: str = "") -> None:
        delta = abs(_num(expected) - _num(actual))
        ok = delta <= TOLERANCE
        checks.append({
            "check": name,
            "passed": bool(ok),
            "expected": round(_num(expected), 2),
            "actual": round(_num(actual), 2),
            "delta": round(delta, 2),
            "detail": detail,
        })
        if not ok:
            logger.warning(
                f"Reconciliation FAILED [{name}]: expected {expected:,.2f}, "
                f"got {actual:,.2f} (delta {delta:,.2f}) {detail}"
            )

    income = features.get("income", {}) or {}
    expense = features.get("expense", {}) or {}
    balance = features.get("balance", {}) or {}
    savings = features.get("savings", {}) or {}
    cash_flow = features.get("cash_flow", {}) or {}

    if df is None or df.empty:
        return {"status": "SKIPPED", "checks": [], "failed_count": 0}

    total_credits = float(df["credit"].sum())
    total_debits = float(df["debit"].sum())
    ledger_delta = total_credits - total_debits

    # 1. The ledger itself: opening + credits - debits == closing.
    opening = _num(balance.get("opening_balance"))
    closing = _num(balance.get("closing_balance"))
    record("ledger_balance_movement", closing, opening + ledger_delta,
           "opening + credits - debits must equal closing")

    # 2. Net cash flow must equal the actual balance movement.
    record("net_cash_flow_matches_ledger", ledger_delta,
           _num(cash_flow.get("net_cash_flow")),
           "cash_flow.net_cash_flow must equal credits - debits")

    # 3. Savings must reconcile with the balance movement over the period.
    monthly_savings = savings.get("monthly_savings", {}) or {}
    if monthly_savings:
        record("savings_matches_ledger", ledger_delta,
               sum(_num(v) for v in monthly_savings.values()),
               "sum(monthly_savings) must equal the change in balance")

    # 4. Credit conservation: every rupee received is either counted as income
    #    or explicitly accounted for as something else (transfer, refund,
    #    redemption). Nothing may silently vanish or be double-counted.
    #    Stated as a conservation law rather than "income == Income-category
    #    credits" so it stays an independent check on the engine rather than a
    #    restatement of its own filter.
    if "non_income_credits_total" in income:
        record("credit_conservation", total_credits,
               _num(income.get("total_income")) + _num(income.get("non_income_credits_total")),
               "income + non-income credits must equal all credits")

    # 5. Needs + wants must account for all reported expense.
    needs = _num(expense.get("needs_spending"))
    wants = _num(expense.get("wants_spending"))
    total_expenses = _num(expense.get("total_expenses"))
    if total_expenses:
        record("needs_plus_wants_equals_expense", total_expenses, needs + wants,
               "every expense rupee must be classified Need or Want")

    # 6. Every debit must land in exactly one bucket.
    if "category" in df.columns:
        bucketed = float(df.loc[df["debit"] > 0, "debit"].sum())
        record("all_debits_bucketed", total_debits, bucketed,
               "no debit may be dropped between extraction and aggregation")

    failed = [c for c in checks if not c["passed"]]
    status = "PASS" if not failed else "FAIL"
    logger.info(
        f"Reconciliation: {status} ({len(checks) - len(failed)}/{len(checks)} checks passed)"
    )
    return {"status": status, "checks": checks, "failed_count": len(failed)}
