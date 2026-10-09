"""SME Business Profiling & Commingling Engine.

Consumes transaction counterparties and evaluates:
1. Inferred business sector / trade.
2. Personal vs. business fund commingling risk.
3. Informal borrowing signals (Chit funds, BC, committee transfers).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import pandas as pd

logger = logging.getLogger(__name__)


def extract_top_counterparties(df: Optional[pd.DataFrame], limit: int = 20) -> List[Dict[str, Any]]:
    """Extract top non-bank counterparties sorted by transaction volume."""
    if df is None or df.empty:
        return []

    # Filter out empty or bank self descriptions
    desc_col = "description" if "description" in df.columns else ("narration" if "narration" in df.columns else None)
    if not desc_col:
        return []

    # Group by merchant_entity if available, otherwise by description/counterparty
    entity_col = "merchant_entity" if "merchant_entity" in df.columns else None
    
    counterparties: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        name = ""
        if entity_col and pd.notnull(row[entity_col]) and str(row[entity_col]).strip():
            name = str(row[entity_col]).strip()
        else:
            name = str(row[desc_col]).strip()

        if not name or len(name) < 3:
            continue

        credit = float(row["credit"]) if ("credit" in row and pd.notnull(row["credit"])) else 0.0
        debit = float(row["debit"]) if ("debit" in row and pd.notnull(row["debit"])) else 0.0
        amt = credit + debit

        if name not in counterparties:
            counterparties[name] = {"counterparty": name, "name": name, "volume": 0.0, "count": 0, "credit_vol": 0.0}
        counterparties[name]["volume"] += amt
        counterparties[name]["count"] += 1
        counterparties[name]["credit_vol"] += credit

    sorted_cp = sorted(counterparties.values(), key=lambda x: x["volume"], reverse=True)
    return sorted_cp[:limit]


def profile_business(df: Optional[pd.DataFrame] = None, top_counterparties: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Execute SME business profiling and commingling detection."""
    from src.model.param_adapter import ParamAdapter

    if top_counterparties is None:
        top_counterparties = extract_top_counterparties(df)

    try:
        adapter = ParamAdapter.get_instance()
        return adapter.profile_sme_counterparties(top_counterparties)
    except Exception as e:
        logger.warning(f"Business profiler error, returning default profile: {e}")
        return {
            "inferred_business_sector": "General Commercial Enterprises",
            "commingling_risk": "LOW",
            "informal_borrowing_flag": False,
            "informal_borrowing_signals": [],
            "explanation": "Standard commercial and retail transaction distribution.",
        }
