"""
Tests for Institutional Inward Cheque & NACH Mandate Dishonour Detection & Penalties.
"""

import pandas as pd
import pytest
from src.engines.fraud_engine import FraudEngine, process as fraud_process
from src.feature_aggregator import aggregate


def test_inward_bounce_detection():
    engine = FraudEngine()
    df = pd.DataFrame([
        {
            "txn_id": "TXN_001",
            "date": pd.Timestamp("2025-01-10"),
            "description": "INW RET CHQ NO 455201 INSUFFICIENT FUNDS",
            "debit": 500.0,
            "credit": 0.0,
            "balance": 1200.0,
        },
        {
            "txn_id": "TXN_002",
            "date": pd.Timestamp("2025-01-25"),
            "description": "NACH RETURN CHARGES REJECT",
            "debit": 350.0,
            "credit": 0.0,
            "balance": 850.0,
        },
        {
            "txn_id": "TXN_003",
            "date": pd.Timestamp("2025-02-01"),
            "description": "GROCERIES D-MART",
            "debit": 1500.0,
            "credit": 0.0,
            "balance": 5000.0,
        }
    ])
    res = engine.process(df)
    features = res["features"]
    assert features["inward_bounce_count"]["value"] >= 2
    assert features["inward_bounce_amount"]["value"] > 0


def test_aggregator_bounce_underwriting_escalation():
    # When >= 2 inward bounces occur, aggregator must cap score at <= 450 and reject/escalate
    engine_outputs = {
        "balance": {"features": {"volatility_score": 0.1, "average_daily_balance": 150000.0}},
        "cash_flow": {"features": {"net_turnover_credit": 200000.0, "trajectory_flag": "STABLE"}},
        "debt": {"features": {"foir": 0.25, "emi_discipline_score": 95.0}},
        "fraud": {
            "features": {
                "inward_bounce_count": 2,
                "inward_bounce_amount": 850.0,
                "circular_turnover_amount": 0.0,
                "high_severity_flag_count": 1,
                "aml_risk_score": 15.0,
                "aml_risk_band": "LOW",
                "total_fraud_flags": 1,
            }
        },
        "behaviour": {"features": {"cheque_bounce_rate": 0.0}},
    }
    agg = aggregate(engine_outputs, "HDFC")
    summary = agg["underwriting_summary"]
    assert summary["inward_bounce_count"] == 2
    assert summary["credit_score"] <= 450
    assert summary["underwriting_decision"] == "REJECT_REPAYMENT_DEFAULT"
    assert summary["risk_band"] == "HIGH_RISK"
