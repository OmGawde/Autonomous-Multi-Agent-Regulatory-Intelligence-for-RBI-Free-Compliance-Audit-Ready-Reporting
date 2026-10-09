"""
Unit tests for Module 11 — Loan Eligibility & Sizing Agent.
"""

import pytest
from src.engines.loan_eligibility_agent import calculate_loan_eligibility, _present_value


def test_present_value_calculation():
    # 10,000 EMI for 12 months at 0% should be 120,000
    assert _present_value(10000.0, 0.0, 12) == 120000.0
    
    # 25,000 EMI for 48 months at 12% p.a.
    pv = _present_value(25000.0, 12.0, 48)
    assert 900000.0 < pv < 1000000.0


def test_salaried_sizing_foir_pv():
    features = {
        "income": {
            "average_monthly_income": 90000.0,
            "salary_income": 90000.0,
            "total_income": 90000.0,
            "income_sources": ["Salary"],
        },
        "debt": {
            "total_emi_amount": 15000.0,
            "foir": 0.166,
        },
        "balance": {
            "average_monthly_balance": 35000.0,
            "volatility_band": "LOW",
        },
        "cash_flow": {
            "net_turnover_credit": 90000.0,
        },
        "fraud": {
            "inward_bounce_count": 0,
        },
        "investment": {
            "total_investment": 50000.0,
        },
        "savings": {
            "total_savings": 20000.0,
        },
        "underwriting_summary": {
            "credit_score": 780.0,
            "foir_score": 0.166,
            "inward_bounce_count": 0,
        }
    }

    res = calculate_loan_eligibility(features)

    assert res["borrower_classification"] == "Salaried"
    assert res["recommended_product"] == "Unsecured Personal Loan"
    assert res["recommended_loan_amount"] > 0
    assert res["recommended_tenure_months"] == 48
    assert res["estimated_monthly_emi"] > 0
    assert res["risk_haircut_pct"] == 0.0
    assert "Salaried professional" in res["policy_decision_rationale"]


def test_msme_turnover_and_adb_sizing():
    features = {
        "income": {
            "average_monthly_income": 200000.0,
            "salary_income": 0.0,
            "total_income": 2400000.0,
            "income_sources": ["Business Receipts", "Client Payments"],
        },
        "debt": {
            "total_emi_amount": 20000.0,
            "foir": 0.10,
        },
        "balance": {
            "average_monthly_balance": 150000.0,
            "volatility_band": "LOW",
        },
        "cash_flow": {
            "net_turnover_credit": 2400000.0,
        },
        "fraud": {
            "inward_bounce_count": 0,
        },
        "investment": {},
        "savings": {},
        "underwriting_summary": {
            "true_turnover": 2400000.0,
            "credit_score": 740.0,
            "volatility_band": "LOW",
            "inward_bounce_count": 0,
        }
    }

    res = calculate_loan_eligibility(features)

    assert res["borrower_classification"] == "MSME_Self_Employed"
    assert "MSME" in res["recommended_product"]
    # Turnover capacity = 2,400,000 * 0.18 = 432,000; ADB capacity = 150,000 * 3 = 450,000
    assert res["recommended_loan_amount"] >= 430000.0


def test_liquid_asset_cushion_bonus():
    features = {
        "income": {
            "average_monthly_income": 60000.0,
            "salary_income": 60000.0,
            "total_income": 60000.0,
            "income_sources": ["Salary"],
        },
        "debt": {
            "total_emi_amount": 10000.0,
        },
        "balance": {
            "average_monthly_balance": 50000.0,
        },
        "cash_flow": {},
        "fraud": {},
        "investment": {
            "total_investment": 1500000.0,  # 15 Lakhs in Mutual Funds
            "monthly_sip_amount": 15000.0,
        },
        "savings": {
            "total_savings": 200000.0,
        },
        "underwriting_summary": {
            "credit_score": 800.0,
        }
    }

    res = calculate_loan_eligibility(features)

    assert res["liquid_asset_cushion_score"] == "STRONG"
    assert res["enhancement_bonus_pct"] == 15.0
    # Base rate was 12.0%, with 50 bps discount it should be 11.5%
    assert res["benchmark_interest_rate"] == 11.5


def test_risk_haircut_for_inward_bounces():
    features = {
        "income": {
            "average_monthly_income": 100000.0,
            "salary_income": 100000.0,
            "total_income": 100000.0,
        },
        "debt": {
            "total_emi_amount": 10000.0,
        },
        "balance": {
            "average_monthly_balance": 50000.0,
        },
        "cash_flow": {},
        "fraud": {
            "inward_bounce_count": 2,
        },
        "underwriting_summary": {
            "credit_score": 450.0,
            "inward_bounce_count": 2,
        }
    }

    res = calculate_loan_eligibility(features)

    assert res["risk_haircut_pct"] >= 80.0
    assert res["recommended_loan_amount"] <= 50000.0


# ---------------------------------------------------------------------------
# Regression tests against the shapes the engines ACTUALLY publish.
#
# Every fixture above was written against key names no engine emits
# (`average_monthly_income`, `total_emi_amount`, `total_savings`) and a scalar
# `average_monthly_balance`. The balance engine publishes that key as a
# {month: value} series, so in production `float()` raised TypeError, the
# aggregator's blanket except swallowed it, and a hardcoded zero term sheet was
# presented as a real sanction offer. The suite stayed green throughout.
#
# These tests use the real key names and the real value shapes.
# ---------------------------------------------------------------------------

def _real_shape_bundle(**overrides):
    """A bundle keyed the way the engines really key their output."""
    bundle = {
        "income": {
            "total_income": 3031025.16,
            "average_income": 252585.43,
            "salary_income": 3021447.0,
            "other_income": 9578.16,
            "income_sources": 4,                      # a count, not a list
            "monthly_income": {"2025-04": 19052.0, "2025-05": 221987.0},
        },
        "debt": {
            "monthly_emi": 161694.0,
            "total_monthly_obligations": 161694.0,
            "total_fixed_obligations": 1207096.0,
            "foir": 0.3778,
            "dti": 0.6402,
        },
        "balance": {
            "average_daily_balance": 174569.82,
            # The shape that used to raise.
            "average_monthly_balance": {"2025-04": 278792.08, "2025-05": 150376.82},
            "volatility_band": "HIGH",
        },
        "cash_flow": {"net_turnover_credit": 3195058.16},
        "fraud": {"inward_bounce_count": 0},
        "investment": {"total_investment": 584207.84, "sip_count": 8},
        "savings": {"average_savings": -23289.87},     # a monthly flow, can be negative
        "underwriting_summary": {
            "credit_score": 880,
            "underwriting_decision": "APPROVE_FAST_TRACK",
            "foir_score": 0.3778,
            "true_turnover": 3195058.16,
            "volatility_band": "HIGH",
            "inward_bounce_count": 0,
        },
    }
    bundle.update(overrides)
    return bundle


def test_dict_valued_monthly_balance_does_not_raise():
    """`average_monthly_balance` as a {month: value} series must be accepted."""
    res = calculate_loan_eligibility(_real_shape_bundle())
    assert res["eligibility_status"] == "SIZED"
    assert res["recommended_loan_amount"] > 0


def test_real_engine_keys_produce_a_sized_facility():
    res = calculate_loan_eligibility(_real_shape_bundle())

    assert res["borrower_classification"] == "Salaried"
    assert res["recommended_product"] == "Unsecured Personal Loan"
    assert res["estimated_monthly_emi"] > 0
    assert res["max_eligible_limit"] >= res["recommended_loan_amount"]
    # Sized off the debt engine's published FOIR, not a recomputed one.
    assert res["current_foir"] == pytest.approx(0.3778)


def test_post_loan_foir_respects_policy_cap():
    """The proposal must not breach the cap printed beside it."""
    res = calculate_loan_eligibility(_real_shape_bundle())
    assert res["post_loan_projected_foir"] <= res["max_allowable_foir"] + 1e-6


def test_ui_foir_key_is_published():
    """The report reads `post_loan_projected_foir`; the legacy alias stays too."""
    res = calculate_loan_eligibility(_real_shape_bundle())
    assert res["post_loan_projected_foir"] is not None
    assert res["projected_post_foir"] == res["post_loan_projected_foir"]
    assert res["max_allowable_foir"] is not None


def test_no_headroom_when_foir_already_at_cap():
    bundle = _real_shape_bundle()
    bundle["debt"]["foir"] = 0.85
    bundle["underwriting_summary"]["foir_score"] = 0.85

    res = calculate_loan_eligibility(bundle)

    assert res["recommended_loan_amount"] == 0.0
    assert res["eligibility_status"] == "NO_HEADROOM"
    assert "no facility is sized" in res["policy_decision_rationale"]


def test_rejected_application_is_not_offered_a_facility():
    """A declined applicant must not get a sanction recommendation."""
    bundle = _real_shape_bundle()
    bundle["underwriting_summary"].update({
        "underwriting_decision": "REJECT_FRAUD_DETECTED",
        "credit_score": None,
        "decision_coherence_note": "Automatic rejection: critical fraud indicators.",
    })

    res = calculate_loan_eligibility(bundle)

    assert res["eligibility_status"] == "NO_FACILITY"
    assert res["recommended_loan_amount"] == 0.0
    assert res["estimated_monthly_emi"] == 0.0
    assert "declined at underwriting" in res["policy_decision_rationale"]


def test_low_credit_score_haircut_applies_from_summary():
    """The score comes from underwriting_summary; it must not default to 750."""
    bundle = _real_shape_bundle()
    bundle["underwriting_summary"]["credit_score"] = 520
    bundle["underwriting_summary"]["underwriting_decision"] = "MANUAL_REVIEW"

    res = calculate_loan_eligibility(bundle)

    assert res["risk_haircut_pct"] == 25.0
    assert "moderate risk band" in res["policy_decision_rationale"]


def test_requested_amount_caps_the_recommendation():
    res = calculate_loan_eligibility(_real_shape_bundle(), requested_amount=500000.0)
    assert res["recommended_loan_amount"] <= 500000.0


def test_num_coercion_handles_engine_value_shapes():
    from src.engines.loan_eligibility_agent import _num

    assert _num({"2025-04": 100.0, "2025-05": 200.0}) == 150.0   # monthly series
    assert _num({"value": 42.0, "confidence": 0.9}) == 42.0      # formatter envelope
    assert _num("1,23,456.78") == pytest.approx(123456.78)       # formatted string
    assert _num(None, default=0.0) == 0.0
    assert _num(True, default=0.0) == 0.0                        # bool is not 1.0
    assert _num({}, default=7.0) == 7.0
