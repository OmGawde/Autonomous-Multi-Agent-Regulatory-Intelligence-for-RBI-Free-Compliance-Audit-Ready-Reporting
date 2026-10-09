"""
Tests for Algorithmic SME Payroll Clustering (No-Keyword Salary Detection).
"""

import pandas as pd
import pytest
from src.engines.income import process as income_process


def test_sme_payroll_clustering_without_salary_keyword():
    # 4 months of consistent NEFT credits from an employer without "SALARY" in narration
    df = pd.DataFrame([
        {
            "date": "2025-01-30",
            "description": "NEFT-KINETIC SOLUTIONS PVT LTD-EXP124",
            "credit": 65000.0,
            "debit": 0.0,
            "balance": 80000.0,
            "category": "Transfer",
            "subcategory": "Bank Transfer In",
            "year_month": "2025-01",
        },
        {
            "date": "2025-02-28",
            "description": "NEFT-KINETIC SOLUTIONS PVT LTD-EXP124",
            "credit": 65000.0,
            "debit": 0.0,
            "balance": 90000.0,
            "category": "Transfer",
            "subcategory": "Bank Transfer In",
            "year_month": "2025-02",
        },
        {
            "date": "2025-03-31",
            "description": "NEFT-KINETIC SOLUTIONS PVT LTD-EXP124",
            "credit": 65000.0,
            "debit": 0.0,
            "balance": 85000.0,
            "category": "Transfer",
            "subcategory": "Bank Transfer In",
            "year_month": "2025-03",
        },
        {
            "date": "2025-04-30",
            "description": "NEFT-KINETIC SOLUTIONS PVT LTD-EXP124",
            "credit": 65000.0,
            "debit": 0.0,
            "balance": 95000.0,
            "category": "Transfer",
            "subcategory": "Bank Transfer In",
            "year_month": "2025-04",
        }
    ])

    features = income_process(df)
    # The recurring transfer must be promoted and identified as salary income
    assert features["salary_income"] == 260000.0
    assert features["average_income"] == 65000.0
