"""
Module 7 — Investment Engine

Identifies and analyzes investment behaviour from classified transactions.
Uses investment keywords from bank_statement_parsing_reference.md §8.

Identifies:
    SIP, Mutual Funds, Zerodha, Groww, Upstox, other brokers,
    PPF, NPS, FD, RD, Bonds, SGB, Equity Trading, Dividend Income

Computes:
    - Monthly Investment
    - Investment Ratio (vs income)
    - Investment Frequency
    - SIP Count (recurring same-amount + same-date patterns)
    - Investment Growth
    - Long-Term Investment Score
    - Redemption Frequency
    - Dividend Income
"""

import logging
from collections import Counter, defaultdict
from typing import Dict, Any, Optional, List

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


# Long-term investment types get higher weight for scoring
LONG_TERM_WEIGHTS: Dict[str, float] = {
    "PPF": 1.0,
    "NPS": 1.0,
    "Bonds / SGB": 0.9,
    "FD / RD": 0.8,
    "Mutual Funds / SIP": 0.7,
    "Equity Trading": 0.4,
    "Zerodha": 0.5,
    "Groww": 0.5,
    "Upstox": 0.5,
    "INDmoney": 0.6,
    "ET Money": 0.6,
    "Dividend": 0.3,
}


def _detect_sips(investment_debits: pd.DataFrame) -> int:
    """
    Detect recurring SIP patterns: same amount debited on same (approx) day monthly.

    A SIP is detected when:
    - Same debit amount appears in >= 3 different months
    - On approximately the same day of month (± 3 days)
    """
    if investment_debits.empty:
        return 0

    sip_count = 0

    # Group by amount (rounded to avoid floating point issues)
    df = investment_debits.copy()
    df["amount_rounded"] = df["debit"].round(0)
    df["day_of_month"] = df["date"].dt.day

    for amount, group in df.groupby("amount_rounded"):
        if len(group) < 3:
            continue

        # Several distinct SIPs commonly share an amount while debiting on
        # different days of the month. Testing the whole amount-group's day
        # range rejected all of them: one real statement ran 173 SIP debits
        # across five amounts and reported sip_count = 1, because only a single
        # amount happened to land on a consistent day. Cluster the days within
        # each amount and count every cluster that recurs monthly.
        for day_cluster in _cluster_days(sorted(group["day_of_month"].unique())):
            cluster_rows = group[group["day_of_month"].isin(day_cluster)]
            if len(cluster_rows) < 3:
                continue
            if cluster_rows["year_month"].nunique() < 3:
                continue
            sip_count += 1

    return sip_count


def _cluster_days(days: list, tolerance: int = 3) -> list:
    """Group days-of-month that fall within `tolerance` of each other."""
    clusters: list = []
    for day in days:
        if clusters and day - clusters[-1][-1] <= tolerance:
            clusters[-1].append(day)
        else:
            clusters.append([day])
    return clusters


def process(transactions: pd.DataFrame, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze investment behaviour from classified transactions.

    Args:
        transactions: Classified DataFrame
        context: Dict with 'income' features for ratio computation

    Returns:
        Dictionary of investment features
    """
    logger.info("Investment Engine: processing")

    context = context or {}
    income_features = context.get("income", {})

    features: Dict[str, Any] = {}

    # Filter transactions classified as Investment
    investment_txns = transactions[
        transactions["category"] == "Investment"
    ].copy()

    # Investment debits (money going out to investments)
    inv_debits = investment_txns[investment_txns["debit"] > 0].copy()

    # Investment credits (redemptions, dividends)
    inv_credits = investment_txns[investment_txns["credit"] > 0].copy()

    if investment_txns.empty:
        logger.warning("Investment Engine: no investment transactions found")
        return {
            "investments_detected": {},
            "monthly_investment": {},
            "total_investment": 0.0,
            "investment_ratio": 0.0,
            "investment_frequency": 0.0,
            "sip_count": 0,
            "investment_growth": [],
            "long_term_investment_score": 0.0,
            "redemption_frequency": 0,
            "dividend_income": 0.0,
        }

    # --- Investments Detected by Type ---
    investments_detected: Dict[str, Dict[str, Any]] = {}
    for inv_type, group in investment_txns.groupby("subcategory"):
        investments_detected[inv_type] = {
            "count": int(len(group)),
            "total_debit": round(float(group["debit"].sum()), 2),
            "total_credit": round(float(group["credit"].sum()), 2),
            "entities": list(group["merchant_entity"].replace("", np.nan).dropna().unique()),
        }
    features["investments_detected"] = investments_detected

    # --- Total Investment ---
    features["total_investment"] = round(float(inv_debits["debit"].sum()), 2)

    # --- Monthly Investment ---
    if not inv_debits.empty:
        monthly_inv = inv_debits.groupby("year_month")["debit"].sum()
        features["monthly_investment"] = {
            k: round(v, 2) for k, v in monthly_inv.to_dict().items()
        }
    else:
        features["monthly_investment"] = {}

    # --- Investment Ratio ---
    total_income = income_features.get("total_income", 0.0)
    features["investment_ratio"] = round(
        _safe_divide(features["total_investment"], total_income), 4
    )

    # --- Investment Frequency ---
    # Average investment transactions per month
    if not inv_debits.empty:
        months_active = inv_debits["year_month"].nunique()
        features["investment_frequency"] = round(
            _safe_divide(len(inv_debits), months_active), 2
        )
    else:
        features["investment_frequency"] = 0.0

    # --- SIP Count ---
    features["sip_count"] = _detect_sips(inv_debits)

    # --- Investment Growth ---
    features["investment_growth"] = _mom_changes(features["monthly_investment"])

    # --- Long-Term Investment Score ---
    # Weighted score based on investment types (PPF/NPS/SGB/FD weighted higher)
    if investments_detected:
        weighted_sum = 0.0
        total_amount = 0.0
        for inv_type, info in investments_detected.items():
            amount = info["total_debit"]
            weight = LONG_TERM_WEIGHTS.get(inv_type, 0.3)
            weighted_sum += amount * weight
            total_amount += amount

        if total_amount > 0:
            features["long_term_investment_score"] = round(
                weighted_sum / total_amount, 4
            )
        else:
            features["long_term_investment_score"] = 0.0
    else:
        features["long_term_investment_score"] = 0.0

    # --- Redemption Frequency ---
    # Count of credits FROM broker/MF entities (money coming back)
    features["redemption_frequency"] = int(len(inv_credits))

    # --- Dividend Income ---
    dividend_mask = investment_txns["subcategory"].str.contains(
        "Dividend", case=False, na=False
    )
    features["dividend_income"] = round(
        float(investment_txns.loc[dividend_mask, "credit"].sum()), 2
    )

    logger.info(
        f"Investment Engine: total={features['total_investment']}, "
        f"types={list(investments_detected.keys())}, "
        f"sip_count={features['sip_count']}, "
        f"lt_score={features['long_term_investment_score']}"
    )

    return features
