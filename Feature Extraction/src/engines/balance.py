"""
Module 4 — Balance Engine

Analyzes account balance health from the running balance column.
Bank-aware: handles per-transaction balances (SBI/ICICI/Axis) and
EOD-only balances (BOI/Union/BOB) with forward-fill.

Computes:
    - Opening / Closing Balance
    - Average Daily Balance (ADB)
    - Average Monthly Balance (AMB)
    - Median / Lowest / Highest Balance
    - Low Balance Count (bank-specific threshold)
    - Negative Balance Count
    - Days Below ₹1,000
    - Balance Volatility (std dev)
    - Balance Recovery Time
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


def _build_daily_balances(
    transactions: pd.DataFrame,
    forward_fill: bool = False,
) -> pd.Series:
    """
    Build a daily balance series from transaction data.

    For banks with per-transaction granularity, takes the last balance of each day.
    For EOD-only banks (Finacle), forward-fills across no-transaction days.
    """
    df = transactions[["date", "balance"]].copy()
    df["date_only"] = df["date"].dt.normalize()

    # Take the last balance entry per day (end-of-day balance)
    daily = df.groupby("date_only")["balance"].last()

    # Create complete date range and fill
    if len(daily) >= 2:
        date_range = pd.date_range(start=daily.index.min(), end=daily.index.max(), freq="D")
        daily = daily.reindex(date_range)

        if forward_fill:
            daily = daily.ffill()
        else:
            # Even for per-transaction banks, fill weekends/holidays
            daily = daily.ffill()

    return daily


def process(transactions: pd.DataFrame, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze balance health from transaction data.

    Args:
        transactions: Classified DataFrame with date, balance columns
        context: Optional context containing bank_config with thresholds

    Returns:
        Dictionary of balance features
    """
    logger.info("Balance Engine: processing")

    context = context or {}
    bank_config = context.get("bank_config", {})
    low_balance_threshold = bank_config.get("low_balance_threshold", 10000)
    forward_fill = bank_config.get("balance_forward_fill", False)

    features: Dict[str, Any] = {}

    if transactions.empty or "balance" not in transactions.columns:
        logger.warning("Balance Engine: no balance data found")
        return {
            "opening_balance": 0.0,
            "closing_balance": 0.0,
            "average_daily_balance": 0.0,
            "average_monthly_balance": {},
            "median_balance": 0.0,
            "lowest_balance": 0.0,
            "highest_balance": 0.0,
            "low_balance_count": 0,
            "negative_balance_count": 0,
            "days_below_1000": 0,
            "balance_volatility": 0.0,
            "balance_recovery_time": 0.0,
        }

    # Ensure sorted by date
    df = transactions.sort_values("date").copy()

    # --- Opening Balance ---
    # Opening balance = balance before the first transaction
    first_row = df.iloc[0]
    opening = float(first_row["balance"]) + float(first_row["debit"]) - float(first_row["credit"])
    features["opening_balance"] = round(opening, 2)

    # --- Closing Balance ---
    features["closing_balance"] = round(float(df.iloc[-1]["balance"]), 2)

    # --- Build daily balance series ---
    daily_balances = _build_daily_balances(df, forward_fill=forward_fill)

    if daily_balances.empty:
        logger.warning("Balance Engine: could not build daily balance series")
        features.update({
            "average_daily_balance": 0.0,
            "average_monthly_balance": {},
            "median_balance": 0.0,
            "lowest_balance": 0.0,
            "highest_balance": 0.0,
            "low_balance_count": 0,
            "negative_balance_count": 0,
            "days_below_1000": 0,
            "balance_volatility": 0.0,
            "balance_recovery_time": 0.0,
        })
        return features

    # Drop any remaining NaN values for calculations
    valid_balances = daily_balances.dropna()

    # --- Average Daily Balance ---
    features["average_daily_balance"] = round(float(valid_balances.mean()), 2)

    # --- Average Monthly Balance ---
    monthly_groups = valid_balances.groupby(valid_balances.index.to_period("M"))
    features["average_monthly_balance"] = {
        str(k): round(float(v), 2) for k, v in monthly_groups.mean().to_dict().items()
    }

    # --- Median Balance ---
    features["median_balance"] = round(float(valid_balances.median()), 2)

    # --- Lowest / Highest Balance ---
    features["lowest_balance"] = round(float(valid_balances.min()), 2)
    features["highest_balance"] = round(float(valid_balances.max()), 2)

    # --- Low Balance Count ---
    features["low_balance_count"] = int((valid_balances < low_balance_threshold).sum())

    # --- Negative Balance Count ---
    features["negative_balance_count"] = int((valid_balances < 0).sum())

    # --- Days Below ₹1,000 ---
    features["days_below_1000"] = int((valid_balances < 1000).sum())

    # --- Balance Volatility (StdDev) ---
    features["balance_volatility"] = round(float(valid_balances.std()), 2)

    # --- Volatility Score (coefficient of variation: StdDev / Mean, 0 to 1) ---
    mean_val = float(valid_balances.mean())
    std_val = float(valid_balances.std())
    if mean_val > 0 and not np.isnan(std_val):
        vol_score = min(max(round(std_val / mean_val, 4), 0.0), 1.0)
    else:
        vol_score = 1.0 if mean_val <= 0 else 0.0
    features["volatility_score"] = vol_score
    
    if vol_score <= 0.15:
        features["volatility_band"] = "LOW"
    elif vol_score <= 0.40:
        features["volatility_band"] = "MODERATE"
    elif vol_score <= 0.70:
        features["volatility_band"] = "HIGH"
    else:
        features["volatility_band"] = "VERY_HIGH"

    features["balance_stability_score"] = round(max(0.0, 1.0 - vol_score), 4)

    # --- Daily Balance Change % ---
    balance_diffs = valid_balances.diff().dropna()
    prev_balances = valid_balances.shift(1).dropna()
    pct_changes = np.where(prev_balances != 0, (balance_diffs / prev_balances.abs()) * 100.0, 0.0)
    features["avg_daily_balance_change_pct"] = round(float(np.mean(np.abs(pct_changes))), 2) if len(pct_changes) > 0 else 0.0
    features["max_daily_balance_change_pct"] = round(float(np.max(np.abs(pct_changes))), 2) if len(pct_changes) > 0 else 0.0

    # --- Available Balance Distribution (% of days above thresholds) ---
    total_valid_days = len(valid_balances)
    thresholds = [50000, 100000, 200000, 500000, 1000000]
    balance_dist = {}
    for th in thresholds:
        days_above = int((valid_balances >= th).sum())
        balance_dist[f"days_above_{th}"] = days_above
        balance_dist[f"pct_days_above_{th}"] = round((days_above / total_valid_days) * 100.0, 2) if total_valid_days > 0 else 0.0
    features["available_balance_distribution"] = balance_dist

    # --- ABB (Average Balance on 1st, 14th, and end of month) ---
    abb_dates_mask = valid_balances.index.day.isin([1, 14, 28, 29, 30, 31])
    abb_balances = valid_balances[abb_dates_mask]
    features["abb_score"] = round(float(abb_balances.mean()), 2) if len(abb_balances) > 0 else features["average_daily_balance"]

    # --- Balance Recovery Time ---
    # Average number of days to return to ADB after dipping below it
    adb = features["average_daily_balance"]
    below_mask = valid_balances < adb
    recovery_times = []
    below_start = None

    for i, (date, is_below) in enumerate(below_mask.items()):
        if is_below and below_start is None:
            below_start = date
        elif not is_below and below_start is not None:
            recovery_days = (date - below_start).days
            recovery_times.append(recovery_days)
            below_start = None

    if recovery_times:
        features["balance_recovery_time"] = round(float(np.mean(recovery_times)), 2)
    else:
        features["balance_recovery_time"] = 0.0

    logger.info(
        f"Balance Engine: ADB={features['average_daily_balance']}, "
        f"Volatility={features['volatility_score']} ({features['volatility_band']}), "
        f"low_count={features['low_balance_count']}"
    )

    return features
