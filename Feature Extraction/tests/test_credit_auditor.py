"""
Unit tests for Module 12 — Param-Finance L2 Credit Auditor Engine.
"""

import pandas as pd
import pytest
from src.engines.credit_auditor import CreditAuditor, audit_statement


def test_false_positive_bounce_clearance():
    auditor = CreditAuditor()
    df = pd.DataFrame([
        {
            "date": "2025-02-10",
            "description": "RETURN OF UNUTILIZED ADVANCE TO CLIENT",
            "debit": 15000.0,
            "credit": 0.0,
            "balance": 85000.0,
        },
        {
            "date": "2025-02-15",
            "description": "SWIGGY BANGALORE",
            "debit": 450.0,
            "credit": 0.0,
            "balance": 84550.0,
        }
    ])
    engine_outputs = {
        "fraud": {
            "inward_bounce_count": 1,
            "bounce_events": ["RETURN OF UNUTILIZED ADVANCE"],
        },
        "income": {
            "salary_income": 50000.0,
        }
    }

    res = auditor.audit(df, engine_outputs)

    assert res["cleared_false_bounces"] == 1
    assert res["verified_inward_bounces"] == 0
    assert res["audit_status"] == "ADJUSTED_FOR_ACCURACY"
    assert len(res["adjustments"]) == 1
    assert res["adjustments"][0]["type"] == "BOUNCE_PENALTY_REVOCATION"


def test_true_dishonour_confirmation():
    auditor = CreditAuditor()
    df = pd.DataFrame([
        {
            "date": "2025-01-20",
            "description": "INW RET CHQ NO 109281 FUNDS INSUFFICIENT",
            "debit": 500.0,
            "credit": 0.0,
            "balance": 250.0,
        }
    ])
    engine_outputs = {
        "fraud": {
            "inward_bounce_count": 1,
            "bounce_events": ["INW RET CHQ NO 109281 FUNDS INSUFFICIENT"],
        },
        "income": {
            "salary_income": 40000.0,
        }
    }

    res = auditor.audit(df, engine_outputs)

    assert res["cleared_false_bounces"] == 0
    assert res["verified_inward_bounces"] == 1
    assert res["audit_status"] == "PASSED_WITH_CONFIRMATION"


def test_hidden_corporate_salary_unmasking():
    auditor = CreditAuditor()
    df = pd.DataFrame([
        {
            "date": "2025-03-01",
            "description": "NEFT CMS/TATA CONSULTANCY SERVICES/TRTR99182/PAYROLL",
            "debit": 0.0,
            "credit": 95000.0,
            "balance": 110000.0,
        }
    ])
    engine_outputs = {
        "fraud": {
            "inward_bounce_count": 0,
        },
        "income": {
            "salary_income": 0.0,  # Rule missed it
        }
    }

    res = auditor.audit(df, engine_outputs)

    assert res["corporate_salary_unmasked"] is True
    assert res["audit_status"] == "ADJUSTED_FOR_ACCURACY"
    assert any(a["type"] == "CORPORATE_SALARY_UNMASKED" for a in res["adjustments"])


def test_clean_statement_audit_concordance():
    auditor = CreditAuditor()
    df = pd.DataFrame([
        {
            "date": "2025-01-01",
            "description": "SALARY CREDIT TECH",
            "debit": 0.0,
            "credit": 60000.0,
            "balance": 60000.0,
        }
    ])
    engine_outputs = {
        "fraud": {
            "inward_bounce_count": 0,
        },
        "income": {
            "salary_income": 60000.0,
        }
    }

    res = auditor.audit(df, engine_outputs)

    assert res["audit_status"] == "PASSED_WITH_CONFIRMATION"
    assert res["adjustments_count"] == 0
    assert "100% concordance" in res["auditor_executive_notes"]
