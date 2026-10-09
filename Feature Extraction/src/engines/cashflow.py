"""
Module 5 — Cash Flow Engine

Analyzes movement and stability of money — inflows, outflows, net cash flow,
surplus/deficit patterns, volatility, and trend.

Computes:
    - Monthly Inflow / Outflow
    - Net Cash Flow
    - Monthly Surplus / Deficit
    - Positive / Negative Cash Flow Months count
    - Cash Flow Volatility
    - Cash Flow Trend (linear regression)
    - Seasonality (only when >= 12 months of data)
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


def process(transactions: pd.DataFrame, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyze cash flow from classified transactions.

    Args:
        transactions: Classified DataFrame with date, debit, credit, year_month
        context: Optional context (not needed for cash flow)

    Returns:
        Dictionary of cash flow features
    """
    logger.info("Cash Flow Engine: processing")

    features: Dict[str, Any] = {}

    if transactions.empty:
        logger.warning("Cash Flow Engine: no transactions found")
        return {
            "monthly_inflow": {},
            "monthly_outflow": {},
            "net_cash_flow": 0.0,
            "monthly_surplus": {},
            "monthly_deficit": {},
            "positive_cash_flow_months": 0,
            "negative_cash_flow_months": 0,
            "cash_flow_volatility": 0.0,
            "cash_flow_trend": 0.0,
            "seasonality": None,
        }

    # --- Monthly Inflow ---
    monthly_inflow = transactions.groupby("year_month")["credit"].sum()
    features["monthly_inflow"] = {k: round(v, 2) for k, v in monthly_inflow.to_dict().items()}

    # --- Monthly Outflow ---
    monthly_outflow = transactions.groupby("year_month")["debit"].sum()
    features["monthly_outflow"] = {k: round(v, 2) for k, v in monthly_outflow.to_dict().items()}

    # --- Net Cash Flow (overall) ---
    total_inflow = float(transactions["credit"].sum())
    total_outflow = float(transactions["debit"].sum())
    features["net_cash_flow"] = round(total_inflow - total_outflow, 2)

    # --- Monthly Net Cash Flow ---
    all_months = sorted(set(list(monthly_inflow.index) + list(monthly_outflow.index)))
    monthly_net: Dict[str, float] = {}
    for month in all_months:
        inflow = monthly_inflow.get(month, 0.0)
        outflow = monthly_outflow.get(month, 0.0)
        monthly_net[month] = round(float(inflow - outflow), 2)

    # --- Surplus / Deficit ---
    features["monthly_surplus"] = {m: v for m, v in monthly_net.items() if v > 0}
    features["monthly_deficit"] = {m: v for m, v in monthly_net.items() if v < 0}

    # --- Positive / Negative Cash Flow Months ---
    features["positive_cash_flow_months"] = len(features["monthly_surplus"])
    features["negative_cash_flow_months"] = len(features["monthly_deficit"])

    # --- Cash Flow Volatility ---
    net_values = list(monthly_net.values())
    if len(net_values) >= 2:
        features["cash_flow_volatility"] = round(float(np.std(net_values)), 2)
    else:
        features["cash_flow_volatility"] = 0.0

    # --- True Net Turnover & Net Expense ---
    # Exclude loans, internal transfers, and returns
    tags_col = transactions["tags"] if "tags" in transactions.columns else pd.Series([""] * len(transactions))
    category_col = transactions["category"] if "category" in transactions.columns else pd.Series([""] * len(transactions))
    subcat_col = transactions["subcategory"] if "subcategory" in transactions.columns else pd.Series([""] * len(transactions))

    is_loan = tags_col.str.contains("Loan", case=False, na=False) | subcat_col.str.contains("Loan", case=False, na=False)
    is_return = tags_col.str.contains("Return", case=False, na=False) | category_col.str.contains("Return", case=False, na=False)
    is_internal = category_col.str.contains("Internal", case=False, na=False) | subcat_col.str.contains("Internal", case=False, na=False)

    credit_mask = ~is_loan & ~is_return & ~is_internal
    debit_mask = ~is_loan & ~is_return & ~is_internal

    net_turnover_credit = float(transactions[credit_mask]["credit"].sum())
    net_expense_debit = float(transactions[debit_mask]["debit"].sum())

    features["net_turnover_credit"] = round(net_turnover_credit, 2)
    features["net_expense_debit"] = round(net_expense_debit, 2)
    features["operational_net_cash_flow"] = round(net_turnover_credit - net_expense_debit, 2)

    # --- Business vs Non-Business Breakdown ---
    biz_subcats = ["Sales & Marketing", "Office Expenses", "Business", "Vendor", "Supplier"]
    is_biz = subcat_col.isin(biz_subcats)
    biz_inflow = float(transactions[is_biz]["credit"].sum())
    biz_outflow = float(transactions[is_biz]["debit"].sum())

    features["biz_inflow"] = round(biz_inflow, 2)
    features["biz_outflow"] = round(biz_outflow, 2)
    features["pct_biz_inflow"] = round((biz_inflow / total_inflow * 100.0), 2) if total_inflow > 0 else 0.0
    features["pct_biz_outflow"] = round((biz_outflow / total_outflow * 100.0), 2) if total_outflow > 0 else 0.0

    # --- Counterparty Concentration Risk ---
    counterparty_col = transactions["merchant_entity"] if "merchant_entity" in transactions.columns else pd.Series([""] * len(transactions))
    valid_cp_credits = transactions[credit_mask & (counterparty_col != "")]
    if not valid_cp_credits.empty and net_turnover_credit > 0:
        cp_totals = valid_cp_credits.groupby(counterparty_col)["credit"].sum()
        max_cp = cp_totals.idxmax()
        max_cp_amt = float(cp_totals.max())
        max_cp_pct = round((max_cp_amt / net_turnover_credit) * 100.0, 2)
        features["top_counterparty_name"] = str(max_cp)
        features["top_counterparty_amount"] = round(max_cp_amt, 2)
        features["top_counterparty_concentration_pct"] = max_cp_pct

        # A salaried applicant receives nearly all inflow from one payer, and
        # that is the good case -- concentration on an employer was reporting
        # CRITICAL at 93.8% for a stable salary. Concentration risk is only
        # meaningful once salary is set aside.
        is_salary_top = False
        if "subcategory" in valid_cp_credits.columns:
            top_rows = valid_cp_credits[
                counterparty_col.reindex(valid_cp_credits.index) == max_cp
            ]
            is_salary_top = bool(
                top_rows["subcategory"].fillna("").str.contains("Salary", case=False, na=False).any()
            )

        if is_salary_top:
            features["concentration_risk_band"] = "NORMAL"
            features["concentration_note"] = "Top counterparty is the salary payer; not a risk signal."
        elif max_cp_pct >= 70.0:
            features["concentration_risk_band"] = "CRITICAL"
        elif max_cp_pct >= 50.0:
            features["concentration_risk_band"] = "HIGH"
        elif max_cp_pct >= 30.0:
            features["concentration_risk_band"] = "MODERATE"
        else:
            features["concentration_risk_band"] = "NORMAL"
    else:
        features["top_counterparty_name"] = "N/A"
        features["top_counterparty_amount"] = 0.0
        features["top_counterparty_concentration_pct"] = 0.0
        features["concentration_risk_band"] = "NORMAL"

    # --- Cash Flow Trend & Trajectory ---
    # In addition to raw net cash flow, evaluate operating cash flow excluding wealth-building investments
    is_inv = category_col.str.contains("Investment", case=False, na=False) | \
             subcat_col.str.contains("SIP|Mutual|NPS|PPF|Securities|Trading", case=False, na=False)
    monthly_inv_outflow = transactions[is_inv].groupby("year_month")["debit"].sum() if is_inv.any() else pd.Series(dtype=float)

    monthly_operating_net: Dict[str, float] = {}
    for month in all_months:
        inflow = monthly_inflow.get(month, 0.0)
        outflow = monthly_outflow.get(month, 0.0)
        inv_out = monthly_inv_outflow.get(month, 0.0)
        monthly_operating_net[month] = round(float(inflow - (outflow - inv_out)), 2)

    sorted_net = [monthly_net[m] for m in sorted(monthly_net.keys())]
    sorted_op_net = [monthly_operating_net[m] for m in sorted(monthly_operating_net.keys())]
    features["cash_flow_trend"] = _linear_slope(sorted_net)
    features["operating_cash_flow_trend"] = _linear_slope(sorted_op_net)

    # Trajectory Flag (Positive / Stable / Negative)
    # If raw cash flow is negative solely due to large investment allocations, operating trajectory takes precedence
    eval_net = sorted_op_net if sum(sorted_op_net) > sum(sorted_net) else sorted_net
    if len(eval_net) >= 2:
        slope = _linear_slope(eval_net)
        consecutive_neg = sum(1 for v in eval_net[-2:] if v < 0)
        if slope > 500 and consecutive_neg == 0:
            features["trajectory_flag"] = "POSITIVE"
        elif slope < -500 or consecutive_neg >= 2:
            features["trajectory_flag"] = "NEGATIVE"
        else:
            features["trajectory_flag"] = "STABLE"
    else:
        features["trajectory_flag"] = "STABLE"

    # --- Seasonality ---
    # Only compute if >= 12 months of data
    if len(all_months) >= 12:
        try:
            # Simple seasonality: average net cash flow by calendar month
            df_net = pd.DataFrame({
                "month": all_months,
                "net": [monthly_net[m] for m in all_months],
            })
            df_net["cal_month"] = df_net["month"].str.split("-").str[1].astype(int)
            seasonality = df_net.groupby("cal_month")["net"].mean()
            features["seasonality"] = {
                int(k): round(float(v), 2) for k, v in seasonality.to_dict().items()
            }
        except Exception as e:
            logger.warning(f"Cash Flow Engine: seasonality calculation failed: {e}")
            features["seasonality"] = None
    else:
        features["seasonality"] = None

    logger.info(
        f"Cash Flow Engine: net={features['net_cash_flow']}, "
        f"true_turnover={features['net_turnover_credit']}, "
        f"trajectory={features['trajectory_flag']}, "
        f"+months={features['positive_cash_flow_months']}, "
        f"-months={features['negative_cash_flow_months']}"
    )

    return features
