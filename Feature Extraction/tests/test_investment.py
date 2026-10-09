"""
Tests for Module 7 — Investment Engine
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.investment import process


@pytest.fixture
def investment_transactions():
    """Classified transactions with investment entries including SIP pattern."""
    dates = (
        [f"2025-{m:02d}-25" for m in range(4, 10)]   # 6 months of SIP (same day, same amount)
        + ["2025-04-17", "2025-05-14", "2025-06-15"]  # PPF
        + ["2025-08-25"]                                # Dividend
    )
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "description": [
            "EBA/MFP-SIP1", "EBA/MFP-SIP1", "EBA/MFP-SIP1",
            "EBA/MFP-SIP1", "EBA/MFP-SIP1", "EBA/MFP-SIP1",
            "BIL/NEFT/PPF SBI", "BIL/NEFT/PPF SBI", "BIL/NEFT/PPF SBI",
            "ACH/COAL INDIA/DIVIDEND",
        ],
        "debit": [
            2000, 2000, 2000, 2000, 2000, 2000,
            5000, 5000, 5000,
            0,
        ],
        "credit": [0] * 9 + [1634],
        "balance": [10000] * 10,
        "bank_name": ["ICICI"] * 10,
        "year_month": [
            "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09",
            "2025-04", "2025-05", "2025-06",
            "2025-08",
        ],
        "category": ["Investment"] * 10,
        "subcategory": [
            "Mutual Funds / SIP"] * 6 + ["PPF"] * 3 + ["Dividend"],
        "merchant_entity": [
            "ICICI Direct"] * 6 + ["PPF SBI"] * 3 + ["Coal India"],
        "transaction_type": ["Debit"] * 9 + ["Credit"],
        "needs_wants": ["N/A"] * 10,
        "confidence": [0.98] * 10,
        "classification_method": ["bank_rule"] * 10,
    })


class TestInvestmentEngine:
    def test_total_investment(self, investment_transactions):
        result = process(investment_transactions)
        # 6 * 2000 (SIP) + 3 * 5000 (PPF) = 27000
        assert result["total_investment"] == 27000.0

    def test_investments_detected(self, investment_transactions):
        result = process(investment_transactions)
        assert "Mutual Funds / SIP" in result["investments_detected"]
        assert "PPF" in result["investments_detected"]
        assert "Dividend" in result["investments_detected"]

    def test_sip_count(self, investment_transactions):
        result = process(investment_transactions)
        # SIP: ₹2000 on 25th of each month for 6 months → 1 SIP
        # PPF: ₹5000 on varying dates for 3 months → not enough (< 3 months on same day)
        assert result["sip_count"] >= 1

    def test_investment_ratio_with_context(self, investment_transactions):
        context = {"income": {"total_income": 100000.0}}
        result = process(investment_transactions, context)
        assert result["investment_ratio"] == 0.27  # 27000/100000

    def test_dividend_income(self, investment_transactions):
        result = process(investment_transactions)
        assert result["dividend_income"] == 1634.0

    def test_redemption_frequency(self, investment_transactions):
        result = process(investment_transactions)
        # 1 credit (dividend)
        assert result["redemption_frequency"] == 1

    def test_long_term_score(self, investment_transactions):
        result = process(investment_transactions)
        # PPF (weight 1.0) and SIP (weight 0.7) contribute
        assert result["long_term_investment_score"] > 0

    def test_empty_transactions(self):
        empty_df = pd.DataFrame(columns=[
            "date", "description", "debit", "credit", "balance",
            "bank_name", "year_month", "category", "subcategory",
            "merchant_entity", "transaction_type", "needs_wants",
            "confidence", "classification_method",
        ])
        result = process(empty_df)
        assert result["total_investment"] == 0.0
        assert result["sip_count"] == 0
