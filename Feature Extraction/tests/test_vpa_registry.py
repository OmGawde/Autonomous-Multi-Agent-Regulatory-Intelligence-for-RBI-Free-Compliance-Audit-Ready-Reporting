"""
Tests for UPI VPA & Merchant Intelligence Registry (Tier 1.5 Classification).
"""

import pytest
from src.rules.vpa_registry import match_vpa_intelligence, extract_vpa_from_text


def test_extract_vpa_from_text():
    assert extract_vpa_from_text("UPI/DR/123456/user@zerodha/Payment") == "user@zerodha"
    assert extract_vpa_from_text("Paid to swiggy.order@icici on 12-05") == "swiggy.order@icici"
    assert extract_vpa_from_text("NO VPA IN THIS NARRATION") is None


def test_wealth_vpa_matching():
    # Capital markets & investments
    match_z = match_vpa_intelligence("UPI/DR/123/invest@zerodha/Fund", 5000.0, 0.0)
    assert match_z is not None
    assert match_z["category"] == "Investment"
    assert match_z["merchant_entity"] == "Zerodha"

    match_g = match_vpa_intelligence("UPI/GROWW@ICICI/SIP", 2000.0, 0.0)
    assert match_g is not None
    assert match_g["category"] == "Investment"
    assert match_g["merchant_entity"] == "Groww"


def test_debt_vpa_matching():
    # Loan EMI and Credit cards
    match_cred = match_vpa_intelligence("UPI/CRED.BILL@AXIS/CC_PAYMENT", 15000.0, 0.0)
    assert match_cred is not None
    assert match_cred["category"] == "Expense"
    assert match_cred["subcategory"] == "Credit Card Payment"
    assert match_cred["needs_wants"] == "Need"

    match_kredit = match_vpa_intelligence("UPI/DR/999/repay@kreditbee/EMI", 3500.0, 0.0)
    assert match_kredit is not None
    assert match_kredit["category"] == "Expense"
    assert match_kredit["subcategory"] == "Loan EMI"


def test_food_delivery_and_refunds():
    match_swiggy = match_vpa_intelligence("UPI/SWIGGY123@YBL/FOOD", 450.0, 0.0)
    assert match_swiggy is not None
    assert match_swiggy["category"] == "Expense"
    assert match_swiggy["subcategory"] == "Food Delivery"
    assert match_swiggy["needs_wants"] == "Want"

    # Credit (refund)
    match_refund = match_vpa_intelligence("UPI/SWIGGY123@YBL/REFUND", 0.0, 450.0)
    assert match_refund is not None
    assert match_refund["category"] == "Income"
    assert "Refund" in match_refund["subcategory"]
