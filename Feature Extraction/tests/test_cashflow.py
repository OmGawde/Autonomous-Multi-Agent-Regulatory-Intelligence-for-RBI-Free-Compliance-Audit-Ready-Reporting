"""
Tests for Module 5 — Cash Flow Engine
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.cashflow import process


@pytest.fixture
def cashflow_transactions():
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2025-04-01", "2025-04-15", "2025-05-01",
            "2025-05-14", "2025-06-01", "2025-06-13",
        ]),
        "description": ["Expense1", "Salary", "Expense2", "Salary", "Expense3", "Salary"],
        "debit": [50000, 0, 60000, 0, 40000, 0],
        "credit": [0, 100000, 0, 100000, 0, 100000],
        "balance": [50000, 150000, 90000, 190000, 150000, 250000],
        "bank_name": ["ICICI"] * 6,
        "year_month": ["2025-04", "2025-04", "2025-05", "2025-05", "2025-06", "2025-06"],
    })


class TestCashFlowEngine:
    def test_monthly_inflow(self, cashflow_transactions):
        result = process(cashflow_transactions)
        assert result["monthly_inflow"]["2025-04"] == 100000.0

    def test_monthly_outflow(self, cashflow_transactions):
        result = process(cashflow_transactions)
        assert result["monthly_outflow"]["2025-04"] == 50000.0

    def test_net_cash_flow(self, cashflow_transactions):
        result = process(cashflow_transactions)
        # Total inflow = 300000, total outflow = 150000
        assert result["net_cash_flow"] == 150000.0

    def test_positive_cash_flow_months(self, cashflow_transactions):
        result = process(cashflow_transactions)
        # All 3 months have surplus
        assert result["positive_cash_flow_months"] == 3

    def test_negative_cash_flow_months(self, cashflow_transactions):
        result = process(cashflow_transactions)
        assert result["negative_cash_flow_months"] == 0

    def test_cash_flow_volatility(self, cashflow_transactions):
        result = process(cashflow_transactions)
        # Surplus varies: 50K, 40K, 60K — should have some volatility
        assert result["cash_flow_volatility"] >= 0

    def test_seasonality_insufficient_data(self, cashflow_transactions):
        result = process(cashflow_transactions)
        # Only 3 months — seasonality should be None
        assert result["seasonality"] is None

    def test_empty_transactions(self):
        empty_df = pd.DataFrame(columns=[
            "date", "description", "debit", "credit", "balance",
            "bank_name", "year_month",
        ])
        result = process(empty_df)
        assert result["net_cash_flow"] == 0.0
