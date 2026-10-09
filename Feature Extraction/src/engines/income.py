"""
Module 2 — Income Engine

Analyzes all identified income sources from classified transactions.
Pure deterministic engine — no ML model required.

Consumes classified credit transactions and computes income features:
    - Monthly Income
    - Average Income
    - Salary Income / Other Income
    - Income Sources count
    - Salary Consistency
    - Income Stability
    - Income Growth (linear regression slope)
    - Monthly Income Trend (MoM % changes)
"""

import re
import logging
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide-by-zero safe division."""
    if denominator == 0 or np.isnan(denominator):
        return default
    return numerator / denominator


def _linear_slope(values: list) -> float:
    """Compute linear regression slope on a value series."""
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    # Handle all-zero or all-NaN cases
    if np.all(np.isnan(y)) or np.std(y) == 0:
        return 0.0
    # Simple OLS slope: (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)
    n = len(x)
    denom = n * np.sum(x ** 2) - np.sum(x) ** 2
    if denom == 0:
        return 0.0
    slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / denom
    return round(float(slope), 2)


def _mom_changes(monthly_dict: Dict[str, float]) -> list:
    """Calculate month-over-month % changes."""
    sorted_months = sorted(monthly_dict.keys())
    changes = []
    for i in range(1, len(sorted_months)):
        prev = monthly_dict[sorted_months[i - 1]]
        curr = monthly_dict[sorted_months[i]]
        pct = _safe_divide(curr - prev, abs(prev), 0.0) * 100
        changes.append(round(pct, 2))
    return changes


def _resolve_credit_entity(row) -> str:
    """Resolve counterparty identity with multi-tier fallback for SME payrolls."""
    for col in ["merchant_entity", "counterparty_key", "parsed_payee"]:
        val = str(row.get(col, "") or "").strip()
        if val and val.lower() not in ("none", "nan", "null", ""):
            return val
    desc = str(row.get("description", "") or "").strip()
    if not desc:
        return ""
    # Strip common payment rail prefixes like NEFT, RTGS, IMPS, UPI, CMS, CLG, ACH
    cleaned = re.sub(r'^(?:NEFT|RTGS|IMPS|UPI|CMS|CLG|ACH|NACH|WDL TFR|DEP TFR)[*\-/\s]+', '', desc, flags=re.IGNORECASE)
    parts = [p.strip() for p in re.split(r'[*_/\-\s]+', cleaned) if len(p.strip()) >= 3 and not p.strip().isdigit()]
    return parts[0].upper() if parts else ""


def _detect_recurring_salary(credits: pd.DataFrame):
    """
    Find the counterparty whose credits look like a recurring salary.

    Requires all three recurring-income signals:
      * same counterparty (resolved via merchant_entity, counterparty_key, parsed_payee, or description)
      * consistent amount (coefficient of variation <= 0.25)
      * roughly monthly arrival (median gap 24-36 days)

    Among qualifying counterparties the largest by total value wins.
    Returns (entity, total_amount, rows) or None.
    """
    if credits.empty:
        return None

    work = credits.copy()
    work["_entity"] = work.apply(_resolve_credit_entity, axis=1)
    work = work[work["_entity"] != ""]
    if work.empty:
        return None

    # Exclude self-transfers, internal sweep deposits, interest, refunds, and tax credits
    excluded = {"SELF", "INTERNAL", "INTEREST", "SWEEP", "MOD", "REFUND", "REVERSAL", "TAX", "PPF", "FD", "RD"}
    work = work[~work["_entity"].str.upper().apply(lambda x: any(k in x for k in excluded))]
    if work.empty:
        return None

    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["_date"])

    candidates = []
    for entity, grp in work.groupby("_entity"):
        if len(grp) < 3:
            continue

        amounts = grp["credit"].astype(float)
        mean_amt = float(amounts.mean())
        if mean_amt < 5000.0:
            continue
        cv = float(amounts.std(ddof=0)) / mean_amt
        if cv > 0.25:
            continue

        gaps = grp["_date"].sort_values().diff().dt.days.dropna()
        if gaps.empty:
            continue
        median_gap = float(gaps.median())
        if not (24.0 <= median_gap <= 36.0):
            continue

        candidates.append((float(amounts.sum()), entity, grp))

    if not candidates:
        return None

    candidates.sort(key=lambda c: -c[0])
    total, entity, rows = candidates[0]
    return entity, total, rows


def process(transactions: pd.DataFrame, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze income from classified transactions.

    Args:
        transactions: Classified DataFrame with columns including
            date, credit, category, subcategory, merchant_entity, year_month
        context: Optional context from other engines (not needed for income)

    Returns:
        Dictionary of income features
    """
    logger.info("Income Engine: processing")

    features: Dict[str, Any] = {}

    # Filter to credit transactions that are actually income.
    #
    # This used to be every row with credit > 0, discarding the classifier's
    # work entirely. Refunds, ATM reversals, investment redemptions and
    # incoming transfers were all counted as earnings -- on one statement that
    # inflated income by Rs 80,000 of ATM reversals plus a Rs 10,000 PPF
    # redemption, and on another by Rs 6,55,838 of salary that had been
    # misfiled as an expense (so it was counted on both sides of the ledger).
    all_credits = transactions[transactions["credit"] > 0].copy()

    if "category" in all_credits.columns:
        credits = all_credits[all_credits["category"] == "Income"].copy()

        # Reversals and refunds are returned money, not earnings.
        if "subcategory" in credits.columns:
            credits = credits[~credits["subcategory"].fillna("").str.contains(
                "Refund|Reversal", case=False, na=False
            )]
        if "tags" in credits.columns:
            credits = credits[~credits["tags"].fillna("").str.contains(
                "Return", case=False, na=False
            )]

        # Promote recurring transfer-ins to income.
        #
        # Not all earnings arrive labelled. Rental income, freelance retainers
        # and family support reach the account as plain NEFT/UPI credits from a
        # single counterparty. Treating those purely as "transfers" understates
        # income to near zero for self-employed and rental profiles -- one real
        # statement's only income was twelve monthly NEFT credits from one
        # individual. A transfer-in only qualifies if it passes the same
        # recurrence test as a salary (same payer, stable amount, monthly).
        non_income = all_credits[all_credits["category"] != "Income"]
        # Never promote a transfer between the holder's own accounts. Moving
        # money in from your own savings account looks exactly like a recurring
        # salary -- same payer, same amount, monthly -- and counting it would
        # inflate income by the full amount cycled.
        if "is_self_transfer" in non_income.columns:
            self_rows = non_income["is_self_transfer"].fillna(False).astype(bool)
            if self_rows.any():
                logger.info(
                    f"Income Engine: excluded {int(self_rows.sum())} self-transfer credits "
                    f"worth {float(non_income.loc[self_rows, 'credit'].sum()):,.2f} from "
                    f"income promotion"
                )
            non_income = non_income[~self_rows]
        if not non_income.empty:
            promoted = _detect_recurring_salary(non_income)
            if promoted:
                entity, amount, rows = promoted
                credits = pd.concat([credits, rows], ignore_index=False)
                logger.info(
                    f"Income Engine: promoted recurring transfer-in from '{entity}' "
                    f"to income ({len(rows)} credits, {amount:,.2f})"
                )

        excluded = len(all_credits) - len(credits)
        if excluded:
            excluded_amt = float(all_credits["credit"].sum() - credits["credit"].sum())
            logger.info(
                f"Income Engine: excluded {excluded} non-income credits "
                f"(transfers/refunds/redemptions) worth {excluded_amt:,.2f}"
            )
        features["non_income_credits_total"] = round(
            float(all_credits["credit"].sum() - credits["credit"].sum()), 2
        )
    else:
        logger.warning("Income Engine: no category column; falling back to all credits")
        credits = all_credits
        features["non_income_credits_total"] = 0.0

    if credits.empty:
        logger.warning("Income Engine: no credit transactions found")
        return {
            "monthly_income": {},
            "average_income": 0.0,
            "total_income": 0.0,
            "salary_income": 0.0,
            "other_income": 0.0,
            "income_sources": 0,
            "salary_consistency": 0.0,
            "income_stability": 0.0,
            "income_growth": 0.0,
            "monthly_income_trend": [],
        }

    # --- Monthly Income ---
    monthly_income = credits.groupby("year_month")["credit"].sum()
    features["monthly_income"] = {k: round(v, 2) for k, v in monthly_income.to_dict().items()}

    # --- Total & Average Income ---
    features["total_income"] = round(float(credits["credit"].sum()), 2)
    features["average_income"] = round(float(monthly_income.mean()), 2)

    # --- Salary Income ---
    salary_keywords_pattern = "salary|sal cr|sal credit|payroll|stipend|remuneration|compensation"
    subcat_salary = credits["subcategory"].str.lower().str.contains("salary", na=False)
    desc_salary = credits["description"].str.lower().str.contains(salary_keywords_pattern, na=False)
    salary_mask = subcat_salary | desc_salary
    salary_credits = credits[salary_mask]
    features["salary_income"] = round(float(salary_credits["credit"].sum()), 2)

    # If no explicit salary tag, detect a recurring salary by its shape.
    #
    # The previous fallback only tested "this counterparty appears in >=50% of
    # months" and then iterated the groupby index -- i.e. alphabetical order --
    # taking the first hit, despite the comment claiming it picked the largest.
    # A small recurring UPI payment could therefore be reported as the salary.
    # Per the recurring-income specification, salary is recurring, consistently sized, and from a
    # single counterparty.
    if features["salary_income"] == 0.0 and not credits.empty:
        detected = _detect_recurring_salary(credits)
        if detected:
            entity, amount, rows = detected
            features["salary_income"] = round(amount, 2)
            salary_credits = rows
            logger.info(
                f"Income Engine: inferred recurring salary source = '{entity}' "
                f"({len(rows)} credits, {amount:,.2f} total)"
            )

    features["other_income"] = round(
        max(features["total_income"] - features["salary_income"], 0.0), 2
    )

    # --- Income Sources ---
    # Count distinct non-empty merchant entities that contributed credits
    if "merchant_entity" in credits.columns:
        income_entities = credits["merchant_entity"].apply(lambda x: str(x).strip() if pd.notnull(x) else "").replace("", np.nan).dropna().nunique()
    else:
        income_entities = credits.apply(_resolve_credit_entity, axis=1).replace("", np.nan).dropna().nunique()
    features["income_sources"] = max(1, int(income_entities)) if not credits.empty else 0

    # --- Salary Consistency ---
    # 1 - CV(salary_amounts); higher = more consistent
    salary_amounts = salary_credits.groupby("year_month")["credit"].sum()
    if len(salary_amounts) >= 2:
        cv = _safe_divide(float(salary_amounts.std()), float(salary_amounts.mean()), 1.0)
        features["salary_consistency"] = round(max(1.0 - cv, 0.0), 4)
    else:
        features["salary_consistency"] = 1.0 if len(salary_amounts) == 1 else 0.0

    # --- Income Stability ---
    # Ratio of months with income >= 80% of average
    avg = features["average_income"]
    if avg > 0:
        stable_months = sum(1 for v in monthly_income.values if v >= avg * 0.80)
        features["income_stability"] = round(
            _safe_divide(stable_months, len(monthly_income)), 4
        )
    else:
        features["income_stability"] = 0.0

    # --- Income Growth ---
    sorted_values = [
        features["monthly_income"][m]
        for m in sorted(features["monthly_income"].keys())
    ]
    features["income_growth"] = _linear_slope(sorted_values)

    # --- Monthly Income Trend ---
    features["monthly_income_trend"] = _mom_changes(features["monthly_income"])

    logger.info(
        f"Income Engine: total={features['total_income']}, "
        f"salary={features['salary_income']}, "
        f"sources={features['income_sources']}"
    )

    return features
