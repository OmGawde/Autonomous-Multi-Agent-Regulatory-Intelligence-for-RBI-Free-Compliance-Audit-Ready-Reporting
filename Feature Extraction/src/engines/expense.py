"""
Module 3 — Expense Engine

Analyzes spending patterns and Needs/Wants classification from classified
transactions. Uses classification labels from Module 1 — does NOT re-run
NLP classification.

Computes:
    - Total / Monthly / Average Expenses
    - Needs / Wants Spending and Ratios
    - Category-wise Spending breakdown
    - Expense Ratio (vs income)
    - Expense Growth
    - Monthly Expense Trend
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


def _linear_slope(values: list) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    if np.all(np.isnan(y)) or np.std(y) == 0:
        return 0.0
    n = len(x)
    denom = n * np.sum(x ** 2) - np.sum(x) ** 2
    if denom == 0:
        return 0.0
    slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / denom
    return round(float(slope), 2)


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
    Analyze expenses from classified transactions.

    Args:
        transactions: Classified DataFrame
        context: Optional context containing income features for ratio computation

    Returns:
        Dictionary of expense features
    """
    logger.info("Expense Engine: processing")

    features: Dict[str, Any] = {}
    context = context or {}

    # Filter to debit transactions classified as expenses
    # Include both "Expense" and investment/banking debits for total calculation
    all_debits = transactions[transactions["debit"] > 0].copy()
    expense_debits = all_debits[
        all_debits["category"].isin(["Expense"])
    ].copy()
    # No fallback to "all debits". That fallback silently folded investments,
    # EMIs, transfers and cash withdrawals into consumer spending whenever the
    # classifier happened to emit no row with category exactly "Expense",
    # which made total_expenses depend on classifier coverage rather than on
    # what was actually spent.
    if expense_debits.empty:
        logger.warning(
            "Expense Engine: no debits classified as Expense; reporting zero "
            "rather than falling back to all debits"
        )

    if expense_debits.empty:
        logger.warning("Expense Engine: no expense transactions found")
        return {
            "total_expenses": 0.0,
            "monthly_expenses": {},
            "average_expenses": 0.0,
            "needs_spending": 0.0,
            "wants_spending": 0.0,
            "needs_ratio": 0.0,
            "wants_ratio": 0.0,
            "category_spending": {},
            "expense_ratio": 0.0,
            "expense_growth": 0.0,
            "monthly_expense_trend": [],
        }

    # --- Total Expenses ---
    features["total_expenses"] = round(float(expense_debits["debit"].sum()), 2)

    # --- Monthly Expenses ---
    monthly_expenses = expense_debits.groupby("year_month")["debit"].sum()
    features["monthly_expenses"] = {
        k: round(v, 2) for k, v in monthly_expenses.to_dict().items()
    }

    # --- Average Expenses ---
    features["average_expenses"] = round(float(monthly_expenses.mean()), 2)

    # --- Needs / Wants Spending ---
    need_keywords = ["rent", "grocery", "utility", "fuel", "taxi", "healthcare", "insurance", "education", "loan", "emi", "bill", "school", "college", "supermarket", "electricity", "water", "gas", "telecom", "mobile", "recharge"]
    
    subcat_lower = expense_debits["subcategory"].fillna("").astype(str).str.lower()
    desc_lower = expense_debits["description"].fillna("").astype(str).str.lower()
    needs_wants_col = expense_debits["needs_wants"].fillna("").astype(str)

    # Needs/Wants comes from the label the classifier already assigned. The
    # keyword regex is only a fallback for rows it left blank.
    #
    # Previously `wants_mask = ~needs_mask` booked every unmatched debit as
    # discretionary, so "Wants" was a residual rather than a measurement -- it
    # reported Rs 14.43L of discretionary spend on one statement while the
    # behaviour engine put the same figure at Rs 15,000.
    kw_pattern = "|".join(need_keywords)
    labelled_need = needs_wants_col == "Need"
    labelled_want = needs_wants_col == "Want"
    unlabelled = ~labelled_need & ~labelled_want

    keyword_need = subcat_lower.str.contains(kw_pattern) | desc_lower.str.contains(kw_pattern)

    needs_mask = labelled_need | (unlabelled & keyword_need)
    wants_mask = labelled_want | (unlabelled & ~keyword_need)

    features["needs_spending"] = round(float(expense_debits.loc[needs_mask, "debit"].sum()), 2)
    features["wants_spending"] = round(float(expense_debits.loc[wants_mask, "debit"].sum()), 2)

    # --- Needs / Wants Ratios ---
    features["needs_ratio"] = round(
        _safe_divide(features["needs_spending"], features["total_expenses"]), 4
    )
    features["wants_ratio"] = round(
        _safe_divide(features["wants_spending"], features["total_expenses"]), 4
    )

    # --- Category-wise Spending ---
    category_spending = expense_debits.groupby("subcategory")["debit"].sum()
    features["category_spending"] = {
        k: round(v, 2) for k, v in category_spending.to_dict().items()
    }

    # --- Expense Ratio ---
    total_income = context.get("income", {}).get("total_income", 0.0)
    features["expense_ratio"] = round(
        _safe_divide(features["total_expenses"], total_income), 4
    )

    # --- Expense Growth ---
    sorted_values = [
        features["monthly_expenses"][m]
        for m in sorted(features["monthly_expenses"].keys())
    ]
    features["expense_growth"] = _linear_slope(sorted_values)

    # --- Monthly Expense Trend ---
    features["monthly_expense_trend"] = _mom_changes(features["monthly_expenses"])

    logger.info(
        f"Expense Engine: total={features['total_expenses']}, "
        f"needs={features['needs_spending']}, wants={features['wants_spending']}"
    )

    return features
