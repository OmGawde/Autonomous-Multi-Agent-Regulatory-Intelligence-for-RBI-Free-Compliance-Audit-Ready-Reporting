"""
Tests for Module 2 — Income Engine
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.income import process


@pytest.fixture
def classified_transactions():
    """Sample classified transactions with income entries."""
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2025-04-16", "2025-05-14", "2025-06-13",
            "2025-06-30", "2025-07-15", "2025-08-25",
            "2025-04-01", "2025-05-03",
        ]),
        "description": [
            "ACH/VIDYALANKAR", "ACH/VIDYALANKAR", "ACH/VIDYALANKAR",
            "Interest Credit", "ACH/VIDYALANKAR", "ACH/COAL INDIA",
            "EBA/MFP-SIP", "UPI/bajajfinance",
        ],
        "debit": [0, 0, 0, 0, 0, 0, 2000, 6075],
        "credit": [19052, 221987, 256987, 1260, 256987, 1634, 0, 0],
        "balance": [316746, 350353, 277883, 36476, 299580, 158719, 336577, 162366],
        "bank_name": ["ICICI"] * 8,
        "year_month": ["2025-04", "2025-05", "2025-06", "2025-06",
                        "2025-07", "2025-08", "2025-04", "2025-05"],
        "category": ["Income", "Income", "Income", "Income", "Income", "Income",
                      "Investment", "Expense"],
        "subcategory": ["Salary", "Salary", "Salary", "Interest", "Salary", "Dividend",
                        "Mutual Funds / SIP", "Loan / EMI"],
        "merchant_entity": ["Vidyalankar", "Vidyalankar", "Vidyalankar", "",
                            "Vidyalankar", "Coal India", "ICICI Direct", "Bajaj Finance"],
        "transaction_type": ["Credit", "Credit", "Credit", "Credit", "Credit", "Credit",
                             "Debit", "Debit"],
        "needs_wants": ["N/A"] * 8,
        "confidence": [0.95] * 8,
        "classification_method": ["bank_rule"] * 8,
    })


class TestIncomeEngine:
    def test_monthly_income(self, classified_transactions):
        result = process(classified_transactions)
        assert "2025-04" in result["monthly_income"]
        assert result["monthly_income"]["2025-04"] == 19052.0

    def test_total_income(self, classified_transactions):
        result = process(classified_transactions)
        expected = 19052 + 221987 + 256987 + 1260 + 256987 + 1634
        assert result["total_income"] == expected

    def test_salary_income(self, classified_transactions):
        result = process(classified_transactions)
        expected_salary = 19052 + 221987 + 256987 + 256987
        assert result["salary_income"] == expected_salary

    def test_other_income(self, classified_transactions):
        result = process(classified_transactions)
        assert result["other_income"] == 1260 + 1634

    def test_income_sources(self, classified_transactions):
        result = process(classified_transactions)
        # Vidyalankar + Coal India = 2 (Interest has empty entity)
        assert result["income_sources"] >= 2

    def test_income_stability_range(self, classified_transactions):
        result = process(classified_transactions)
        assert 0.0 <= result["income_stability"] <= 1.0

    def test_salary_consistency_range(self, classified_transactions):
        result = process(classified_transactions)
        assert 0.0 <= result["salary_consistency"] <= 1.0

    def test_empty_transactions(self):
        empty_df = pd.DataFrame(columns=[
            "date", "description", "debit", "credit", "balance",
            "bank_name", "year_month", "category", "subcategory",
            "merchant_entity", "transaction_type", "needs_wants",
            "confidence", "classification_method",
        ])
        result = process(empty_df)
        assert result["total_income"] == 0.0
        assert result["monthly_income"] == {}
