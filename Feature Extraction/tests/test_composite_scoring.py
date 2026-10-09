"""
Tests for Composite scoring, volatility, FOIR and fraud irregularity features
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.classifier import TransactionClassifier
from src.engines import balance, cashflow, debt_engine, fraud_engine
from src.feature_aggregator import aggregate


@pytest.fixture
def sample_transactions():
    """Create a realistic bank statement DataFrame with 6 months of data."""
    dates = pd.date_range(start="2025-01-01", periods=180, freq="D")
    df_list = []
    bal = 100000.0

    for i, d in enumerate(dates):
        # Monthly Salary
        if d.day == 1:
            df_list.append({
                "date": d,
                "description": "BY TRANSFER-NEFT/INFOSYS LTD/SALARY JAN",
                "debit": 0.0,
                "credit": 150000.0,
                "balance": bal + 150000.0,
                "bank_name": "HDFC",
                "year_month": d.strftime("%Y-%m")
            })
            bal += 150000.0

        # Monthly EMI
        if d.day == 5:
            df_list.append({
                "date": d,
                "description": "ACH DEBIT/HDFC BANK LTD/LOAN EMI 99823",
                "debit": 30000.0,
                "credit": 0.0,
                "balance": bal - 30000.0,
                "bank_name": "HDFC",
                "year_month": d.strftime("%Y-%m")
            })
            bal -= 30000.0

        # Routine Expenses
        if d.day in [10, 15, 20]:
            df_list.append({
                "date": d,
                "description": "UPI/DR/123/SWIGGY/swiggy@icici",
                "debit": 1200.0,
                "credit": 0.0,
                "balance": bal - 1200.0,
                "bank_name": "HDFC",
                "year_month": d.strftime("%Y-%m")
            })
            bal -= 1200.0

    return pd.DataFrame(df_list)


class TestCompositeScoring:
    def test_volatility_score(self, sample_transactions):
        """Verify the reference model volatility score (CV) is computed correctly."""
        res = balance.process(sample_transactions)
        assert "volatility_score" in res
        assert "volatility_band" in res
        assert 0.0 <= res["volatility_score"] <= 1.0
        assert res["volatility_band"] in ["LOW", "MODERATE", "HIGH", "VERY_HIGH"]
        assert "available_balance_distribution" in res

    def test_credit_score_true_turnover_and_trajectory(self, sample_transactions):
        """Verify True Net Turnover and Trajectory flag."""
        # Classify first
        classifier = TransactionClassifier()
        classified = classifier.classify_dataframe(sample_transactions, "HDFC")
        
        res = cashflow.process(classified)
        assert "net_turnover_credit" in res
        assert res["net_turnover_credit"] > 0
        assert "trajectory_flag" in res
        assert res["trajectory_flag"] in ["POSITIVE", "STABLE", "NEGATIVE"]

    def test_computed_foir_and_emi_discipline(self, sample_transactions):
        """Verify FOIR score calculation and EMI discipline."""
        classifier = TransactionClassifier()
        classified = classifier.classify_dataframe(sample_transactions, "HDFC")
        
        res = debt_engine.process(classified)
        assert "foir" in res
        assert "foir_risk_band" in res
        assert res["foir_risk_band"] in ["LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "VERY_HIGH_RISK"]
        assert "emi_discipline_score" in res
        assert res["emi_discipline_score"] >= 90.0
        assert res["emi_discipline_band"] == "GOOD"

    def test_credit_score_16_irregularity_checks(self):
        """Verify FraudEngine detects RTGS below 2L, structuring, and round tax."""
        df_fraud = pd.DataFrame([
            {
                "date": datetime(2025, 3, 1),
                "description": "RTGS/DR/AXIS/SMALL PAYMENT",
                "debit": 50000.0,
                "credit": 0.0,
                "balance": 200000.0,
                "tags": "RTGS"
            },
            {
                "date": datetime(2025, 3, 2),
                "description": "INTERNET TAX PAYMENT Q4",
                "debit": 40000.0,
                "credit": 0.0,
                "balance": 160000.0,
                "tags": "Tax"
            },
            {
                "date": datetime(2025, 3, 3),
                "description": "INTERNET TAX PAYMENT Q4 PART 2",
                "debit": 60000.0,
                "credit": 0.0,
                "balance": 100000.0,
                "tags": "Tax"
            },
            {
                "date": datetime(2025, 3, 4),
                "description": "CASH DEPOSIT MACHINE",
                "debit": 0.0,
                "credit": 950000.0,
                "balance": 1050000.0,
                "tags": "Cash"
            }
        ])

        res = fraud_engine.process(df_fraud)
        assert "aml_risk_score" in res
        assert "irregularity_penalty_points" in res
        assert res["total_fraud_flags"] >= 2
        assert res["irregularity_penalty_points"] > 0

    def test_composite_credit_score_aggregation(self, sample_transactions):
        """Verify end-to-end composite Credit Score (0-1000) and recommendation."""
        classifier = TransactionClassifier()
        classified = classifier.classify_dataframe(sample_transactions, "HDFC")

        context = {}
        inc = {"average_income": 150000.0}
        bal = balance.process(classified)
        cf = cashflow.process(classified)
        dbt = debt_engine.process(classified, context={"income": inc})
        frd = fraud_engine.process(classified)
        beh = {"cheque_bounce_rate": 0.0}

        engine_outputs = {
            "income": inc,
            "balance": bal,
            "cash_flow": cf,
            "debt": dbt,
            "fraud": frd,
            "behaviour": beh,
        }

        period = {"start": "2025-01-01", "end": "2025-06-30"}
        combined = aggregate(engine_outputs, "HDFC", period)

        summary = combined.get("underwriting_summary", {})
        assert "credit_score" in summary
        assert 600 <= summary["credit_score"] <= 1000
        assert summary["risk_band"] in ["VERY_LOW_RISK", "LOW_RISK", "MODERATE_RISK"]
        assert summary["underwriting_decision"] in ["APPROVE_FAST_TRACK", "APPROVE_STANDARD", "MANUAL_REVIEW"]
        assert summary["data_sufficiency"] == "OPTIMAL_DATA"

    def test_high_anomaly_density_causes_rejection_and_low_score(self):
        """Verify that an account with multiple HIGH anomalies, volatility, and negative balance is rejected with low credit score."""
        engine_outputs = {
            "income": {"average_income": 100000.0},
            "balance": {
                "volatility_score": 1.00,
                "negative_balance_count": 2,
            },
            "cash_flow": {
                "trajectory_flag": "NEGATIVE",
                "net_turnover_credit": 50000.0,
            },
            "debt": {
                "foir": 0.0,
                "emi_discipline_score": 100.0,
            },
            "fraud": {
                "aml_risk_score": 85.0,
                "aml_risk_band": "HIGH",
                "irregularity_penalty_points": 530,
                "high_severity_flag_count": 5,
                "total_fraud_flags": 10,
                "total_fraud_flags_triggered": 10,
                "fraud_score": 35.0,
            },
            "behaviour": {
                "cheque_bounce_rate": 0.0,
            }
        }

        period = {"start": "2025-01-01", "end": "2025-03-31"}
        combined = aggregate(engine_outputs, "Canara Bank", period)
        summary = combined["underwriting_summary"]

        assert summary["credit_score"] is not None
        assert summary["credit_score"] <= 450, f"Expected score <= 450 with 5 HIGH anomalies, got {summary['credit_score']}"
        assert summary["risk_band"] == "HIGH_RISK"
        assert "REJECT" in summary["underwriting_decision"]
        assert summary["decision_coherence_note"] is not None

    def test_insufficient_data_caps_credit_score(self):
        """Verify statements < 90 days are capped at max 720 score."""
        engine_outputs = {
            "income": {"average_income": 100000.0},
            "balance": {"volatility_score": 0.05, "negative_balance_count": 0},
            "cash_flow": {"trajectory_flag": "POSITIVE"},
            "debt": {"foir": 0.1, "emi_discipline_score": 100.0},
            "fraud": {"aml_risk_band": "LOW", "irregularity_penalty_points": 0, "high_severity_flag_count": 0},
            "behaviour": {"cheque_bounce_rate": 0.0}
        }

        # 45-day period (< 90 days)
        period = {"start": "2025-01-01", "end": "2025-02-15"}
        combined = aggregate(engine_outputs, "HDFC", period)
        summary = combined["underwriting_summary"]

        assert summary["data_sufficiency"] == "INSUFFICIENT_DATA_WARNING"
        assert summary["credit_score"] <= 720, f"Expected max 720 score for insufficient data, got {summary['credit_score']}"
