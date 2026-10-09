"""
Tests for Module 4 — Balance Engine
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.balance import process


@pytest.fixture
def balance_transactions():
    """Transactions with known balance progression."""
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2025-04-01", "2025-04-02", "2025-04-03",
            "2025-04-04", "2025-04-05",
        ]),
        "description": ["TXN1", "TXN2", "TXN3", "TXN4", "TXN5"],
        "debit": [1000, 500, 0, 2000, 0],
        "credit": [0, 0, 5000, 0, 1000],
        "balance": [9000, 8500, 13500, 11500, 12500],
        "bank_name": ["ICICI"] * 5,
        "year_month": ["2025-04"] * 5,
    })


class TestBalanceEngine:
    def test_opening_balance(self, balance_transactions):
        result = process(balance_transactions)
        # Opening = first balance + first debit - first credit = 9000 + 1000 - 0 = 10000
        assert result["opening_balance"] == 10000.0

    def test_closing_balance(self, balance_transactions):
        result = process(balance_transactions)
        assert result["closing_balance"] == 12500.0

    def test_lowest_balance(self, balance_transactions):
        result = process(balance_transactions)
        assert result["lowest_balance"] == 8500.0

    def test_highest_balance(self, balance_transactions):
        result = process(balance_transactions)
        assert result["highest_balance"] == 13500.0

    def test_average_daily_balance(self, balance_transactions):
        result = process(balance_transactions)
        # 5 days: (9000+8500+13500+11500+12500)/5 = 11000
        assert abs(result["average_daily_balance"] - 11000.0) < 1.0

    def test_negative_balance_count(self, balance_transactions):
        result = process(balance_transactions)
        assert result["negative_balance_count"] == 0

    def test_low_balance_count_default_threshold(self, balance_transactions):
        # Default threshold is 10000
        result = process(balance_transactions)
        # 8500 and 9000 are below 10000
        assert result["low_balance_count"] >= 1

    def test_balance_volatility(self, balance_transactions):
        result = process(balance_transactions)
        assert result["balance_volatility"] > 0

    def test_forward_fill_for_finacle_bank(self):
        """Test that forward-fill works for EOD-only balance banks."""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-04-01", "2025-04-05"]),
            "description": ["TXN1", "TXN2"],
            "debit": [1000, 500],
            "credit": [0, 0],
            "balance": [9000, 8500],
            "bank_name": ["Bank Of India"] * 2,
            "year_month": ["2025-04"] * 2,
        })
        context = {"bank_config": {"balance_forward_fill": True}}
        result = process(df, context)
        # Should have ADB computed over 5 days (forward-filled)
        assert result["average_daily_balance"] > 0

    def test_empty_transactions(self):
        empty_df = pd.DataFrame(columns=[
            "date", "description", "debit", "credit", "balance",
            "bank_name", "year_month",
        ])
        result = process(empty_df)
        assert result["opening_balance"] == 0.0
        assert result["closing_balance"] == 0.0
