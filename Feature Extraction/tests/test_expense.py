"""
Tests for Module 3 — Expense Engine
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.expense import process


@pytest.fixture
def classified_expense_transactions():
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2025-04-01", "2025-04-04", "2025-05-03",
            "2025-05-14", "2025-06-20",
        ]),
        "description": [
            "SWIGGY ORDER", "HPCL FUEL", "NETFLIX",
            "BIGBASKET GROCERY", "Bajaj Allianz Insurance",
        ],
        "debit": [500, 3000, 649, 2500, 34807],
        "credit": [0, 0, 0, 0, 0],
        "balance": [10000, 7000, 6351, 3851, 0],
        "bank_name": ["ICICI"] * 5,
        "year_month": ["2025-04", "2025-04", "2025-05", "2025-05", "2025-06"],
        "category": ["Expense"] * 5,
        "subcategory": [
            "Food Delivery", "Fuel", "Entertainment",
            "Grocery / Supermarket", "Insurance",
        ],
        "needs_wants": ["Want", "Need", "Want", "Need", "Need"],
        "merchant_entity": ["Swiggy", "HPCL", "Netflix", "BigBasket", "Bajaj Allianz"],
        "transaction_type": ["Debit"] * 5,
        "confidence": [0.90] * 5,
        "classification_method": ["keyword"] * 5,
    })


class TestExpenseEngine:
    def test_total_expenses(self, classified_expense_transactions):
        result = process(classified_expense_transactions)
        assert result["total_expenses"] == 500 + 3000 + 649 + 2500 + 34807

    def test_needs_spending(self, classified_expense_transactions):
        result = process(classified_expense_transactions)
        assert result["needs_spending"] == 3000 + 2500 + 34807

    def test_wants_spending(self, classified_expense_transactions):
        result = process(classified_expense_transactions)
        assert result["wants_spending"] == 500 + 649

    def test_needs_ratio(self, classified_expense_transactions):
        result = process(classified_expense_transactions)
        total = 500 + 3000 + 649 + 2500 + 34807
        expected = (3000 + 2500 + 34807) / total
        assert abs(result["needs_ratio"] - expected) < 0.01

    def test_category_spending(self, classified_expense_transactions):
        result = process(classified_expense_transactions)
        assert "Fuel" in result["category_spending"]
        assert result["category_spending"]["Fuel"] == 3000

    def test_expense_ratio_with_income_context(self, classified_expense_transactions):
        context = {"income": {"total_income": 100000.0}}
        result = process(classified_expense_transactions, context)
        assert result["expense_ratio"] > 0

    def test_empty_transactions(self):
        empty_df = pd.DataFrame(columns=[
            "date", "description", "debit", "credit", "balance",
            "bank_name", "year_month", "category", "subcategory",
            "needs_wants", "merchant_entity", "transaction_type",
            "confidence", "classification_method",
        ])
        result = process(empty_df)
        assert result["total_expenses"] == 0.0
