"""
Tests for Module 6 — Savings Engine
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.savings import process


@pytest.fixture
def savings_context():
    """Context with income, expense, and balance features."""
    return {
        "income": {
            "monthly_income": {
                "2025-04": 100000,
                "2025-05": 100000,
                "2025-06": 100000,
            },
            "total_income": 300000,
        },
        "expense": {
            "monthly_expenses": {
                "2025-04": 60000,
                "2025-05": 70000,
                "2025-06": 50000,
            },
            "needs_spending": 120000,
        },
        "balance": {
            "closing_balance": 150000,
        },
    }


@pytest.fixture
def dummy_transactions():
    return pd.DataFrame(columns=[
        "date", "description", "debit", "credit", "balance",
        "bank_name", "year_month",
    ])


class TestSavingsEngine:
    def test_monthly_savings(self, dummy_transactions, savings_context):
        result = process(dummy_transactions, savings_context)
        assert result["monthly_savings"]["2025-04"] == 40000
        assert result["monthly_savings"]["2025-05"] == 30000
        assert result["monthly_savings"]["2025-06"] == 50000

    def test_savings_rate(self, dummy_transactions, savings_context):
        result = process(dummy_transactions, savings_context)
        assert result["savings_rate"]["2025-04"] == 0.4

    def test_positive_savings_months(self, dummy_transactions, savings_context):
        result = process(dummy_transactions, savings_context)
        assert result["positive_savings_months"] == 3

    def test_average_savings(self, dummy_transactions, savings_context):
        result = process(dummy_transactions, savings_context)
        assert result["average_savings"] == 40000.0

    def test_emergency_fund_estimate(self, dummy_transactions, savings_context):
        result = process(dummy_transactions, savings_context)
        ef = result["emergency_fund_estimate"]
        # avg_monthly_needs = 120000/3 = 40000
        assert ef["avg_monthly_needs"] == 40000.0
        assert ef["fund_3_months"] == 120000.0
        assert ef["fund_6_months"] == 240000.0
        assert ef["current_balance"] == 150000
        # 150000 / 40000 = 3.8 months coverage
        assert ef["coverage_months"] == 3.8

    def test_empty_context(self, dummy_transactions):
        result = process(dummy_transactions, {})
        assert result["monthly_savings"] == {}
        assert result["positive_savings_months"] == 0
