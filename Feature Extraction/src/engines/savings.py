"""
Module 6 — Savings Engine

Evaluates savings behaviour and financial buffer using outputs from
Income, Expense, and Balance engines.

Formulas from bank_statement_parsing_reference.md §7:
    - Monthly Savings = Total Credits − Total Debits (per month)
    - Savings Rate = Monthly Savings / Total Income
    - Positive Savings Months = count(Monthly Savings > 0)
    - Savings Growth = MoM % change in Monthly Savings
    - Average Savings = mean(Monthly Savings)
    - Savings Consistency = std.dev/coefficient of variation
    - Emergency Fund Estimate = Avg Monthly Needs × 3–6 vs current balance
"""

import logging
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or np.isnan(denominator):
        return default
    return numerator / denominator


def _mom_changes(monthly_dict: Dict[str, float]) -> list:
    sorted_months = sorted(monthly_dict.keys())
    changes = []
    for i in range(1, len(sorted_months)):
        prev = monthly_dict[sorted_months[i - 1]]
        curr = monthly_dict[sorted_months[i]]
        pct = _safe_divide(curr - prev, abs(prev), 0.0) * 100
        changes.append(round(pct, 2))
    return changes


def process(transactions: pd.DataFrame, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze savings behaviour using outputs from other engines.

    Args:
        transactions: Classified DataFrame
        context: Dict with keys:
            - 'income': output from Income Engine
            - 'expense': output from Expense Engine
            - 'balance': output from Balance Engine

    Returns:
        Dictionary of savings features
    """
    logger.info("Savings Engine: processing")

    context = context or {}
    income_features = context.get("income", {})
    expense_features = context.get("expense", {})
    balance_features = context.get("balance", {})

    features: Dict[str, Any] = {}

    monthly_income = income_features.get("monthly_income", {})
    monthly_expenses = expense_features.get("monthly_expenses", {})

    if not monthly_income and not monthly_expenses:
        logger.warning("Savings Engine: no income/expense data in context")
        return {
            "monthly_savings": {},
            "savings_rate": {},
            "positive_savings_months": 0,
            "savings_growth": [],
            "average_savings": 0.0,
            "savings_consistency": 0.0,
            "emergency_fund_estimate": {},
        }

    # --- Monthly Savings ---
    # Savings is the actual month-on-month change in the account: every credit
    # minus every debit. Deriving it from the income and expense engines instead
    # (income - expense) double-counted the gap between them: transfers,
    # investments and cash withdrawals belong to neither bucket, so the figure
    # drifted away from reality. On one statement that produced a reported
    # +Rs 52,120/month while the balance was falling Rs 2,79,478 over the year.
    #
    # Computed straight off the transaction frame, this reconciles with the
    # balance movement by construction (see utils/reconciliation.py).
    monthly_savings: Dict[str, float] = {}

    if transactions is not None and not transactions.empty and "year_month" in transactions.columns:
        grouped = transactions.groupby("year_month")[["credit", "debit"]].sum()
        monthly_savings = {
            str(m): round(float(r["credit"] - r["debit"]), 2)
            for m, r in grouped.iterrows()
        }
        all_months = sorted(monthly_savings.keys())
    else:
        # Fallback for callers that pass no frame (kept for unit tests).
        all_months = sorted(set(list(monthly_income.keys()) + list(monthly_expenses.keys())))
        for month in all_months:
            monthly_savings[month] = round(
                monthly_income.get(month, 0.0) - monthly_expenses.get(month, 0.0), 2
            )

    features["monthly_savings"] = monthly_savings

    # Money moved into investments is saved, not spent. Reported separately so
    # the cash view and the wealth view are both available and neither is
    # silently conflated with the other.
    monthly_investment: Dict[str, float] = {}
    if (transactions is not None and not transactions.empty
            and {"year_month", "category"}.issubset(transactions.columns)):
        inv = transactions[transactions["category"] == "Investment"]
        if not inv.empty:
            monthly_investment = {
                str(m): round(float(v), 2)
                for m, v in inv.groupby("year_month")["debit"].sum().items()
            }
    features["monthly_savings_incl_investment"] = {
        m: round(monthly_savings.get(m, 0.0) + monthly_investment.get(m, 0.0), 2)
        for m in all_months
    }

    # --- Savings Rate ---
    savings_rate: Dict[str, float] = {}
    for month in all_months:
        income = monthly_income.get(month, 0.0)
        savings = monthly_savings.get(month, 0.0)
        savings_rate[month] = round(_safe_divide(savings, income), 4)

    features["savings_rate"] = savings_rate

    # --- Positive Savings Months ---
    features["positive_savings_months"] = sum(
        1 for v in monthly_savings.values() if v > 0
    )

    # --- Savings Growth ---
    features["savings_growth"] = _mom_changes(monthly_savings)

    # --- Average Savings ---
    savings_values = list(monthly_savings.values())
    if savings_values:
        features["average_savings"] = round(float(np.mean(savings_values)), 2)
    else:
        features["average_savings"] = 0.0

    # --- Savings Consistency ---
    # Lower CV = more consistent. We report CV directly.
    # Reported as 1 - CV, clamped to [0, 1]: higher means more consistent.
    # This previously returned the raw coefficient of variation, i.e. higher
    # meant *less* consistent -- the opposite polarity to the identically-named
    # income.salary_consistency, and unbounded (one statement reported 29.68).
    if len(savings_values) >= 2 and np.mean(savings_values) != 0:
        std = float(np.std(savings_values))
        mean_val = abs(float(np.mean(savings_values)))
        cv = _safe_divide(std, mean_val, default=1.0)
        features["savings_consistency"] = round(min(max(1.0 - cv, 0.0), 1.0), 4)
    else:
        features["savings_consistency"] = 0.0

    # --- Emergency Fund Estimate ---
    # Avg Monthly Needs × 3 and × 6, compared to current balance.
    #
    # "Needs" only covers the debits that matched an essential keyword, so
    # basing the runway on it alone ignored most of what the account actually
    # spends each month and overstated coverage badly -- one statement
    # published 11.1 months against a true 0.28. The floor is the account's
    # real average monthly outflow.
    total_months = len(all_months) if all_months else 1
    needs_spending = expense_features.get("needs_spending", 0.0)
    avg_needs_only = _safe_divide(needs_spending, total_months)

    avg_monthly_outflow = 0.0
    if transactions is not None and not transactions.empty and "year_month" in transactions.columns:
        monthly_out = transactions.groupby("year_month")["debit"].sum()
        if len(monthly_out):
            avg_monthly_outflow = float(monthly_out.mean())

    avg_monthly_needs = max(avg_needs_only, avg_monthly_outflow)

    closing_balance = balance_features.get("closing_balance", 0.0)

    fund_3_months = round(avg_monthly_needs * 3, 2)
    fund_6_months = round(avg_monthly_needs * 6, 2)

    features["emergency_fund_estimate"] = {
        "avg_monthly_needs": round(avg_monthly_needs, 2),
        "fund_3_months": fund_3_months,
        "fund_6_months": fund_6_months,
        "current_balance": closing_balance,
        "coverage_months": round(
            _safe_divide(closing_balance, avg_monthly_needs), 1
        ) if avg_monthly_needs > 0 else None,
    }

    logger.info(
        f"Savings Engine: avg_savings={features['average_savings']}, "
        f"positive_months={features['positive_savings_months']}/{len(all_months)}, "
        f"emergency_fund_coverage="
        f"{features['emergency_fund_estimate'].get('coverage_months', 'N/A')} months"
    )

    return features
