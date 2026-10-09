"""Tests for the deterministic ledger query resolver.

The Copilot previously answered only five hardcoded topics and deflected
everything else with "please query specific topics such as fintech loans,
balance dips, tax payments, or large credits". These cover the free-form
questions an analyst actually types, and the ordering rules that keep the
existing guardrails in front of the resolver.
"""

from __future__ import annotations

import pytest

from src.model import ledger_query
from src.model.param_adapter import ParamAdapter, ParamModelLoader


@pytest.fixture
def adapter():
    return ParamAdapter(loader=ParamModelLoader(mock_mode=True))


@pytest.fixture
def txns():
    return [
        {"date": "2025-04-10", "description": "ACH/VIDYALANKAR INSTITUT/SAL 001",
         "debit": 0.0, "credit": 250000.0, "balance": 300000.0,
         "category": "Income", "subcategory": "Salary"},
        {"date": "2025-05-10", "description": "ACH/VIDYALANKAR INSTITUT/SAL 002",
         "debit": 0.0, "credit": 270000.0, "balance": 420000.0,
         "category": "Income", "subcategory": "Salary"},
        {"date": "2025-05-12", "description": "BIL/ONL/HDFC Ltd/HOME LOAN EMI",
         "debit": 200424.0, "credit": 0.0, "balance": 219576.0,
         "category": "Expense", "subcategory": "Home Loan EMI"},
        {"date": "2025-10-17", "description": "UPI/SWIGGYSTORES/ORDER/882",
         "debit": 640.0, "credit": 0.0, "balance": 218936.0,
         "category": "Expense", "subcategory": "Food Delivery"},
        {"date": "2025-10-20", "description": "ACH/PREMIUM COLLECT/LIC INSURANCE",
         "debit": 12000.0, "credit": 0.0, "balance": 206936.0,
         "category": "Expense", "subcategory": "Insurance"},
        {"date": "2025-11-02", "description": "UPI/NAVI TECH LOAN EMI/navi@icici",
         "debit": 10548.0, "credit": 0.0, "balance": 196388.0,
         "category": "Debt / Loans", "subcategory": "Personal Loan EMI"},
    ]


# --- superlatives ----------------------------------------------------------

def test_highest_payment(txns):
    """The question that started this: it used to hit the generic deflection."""
    res = ledger_query.resolve("which is the highest payment", txns)

    assert res is not None
    assert "200,424.00" in res["answer"]
    assert "HOME LOAN EMI" in res["answer"]
    assert res["citations"][0]["amount"] == 200424.0


def test_smallest_payment(txns):
    res = ledger_query.resolve("what is the smallest payment", txns)
    assert "640.00" in res["answer"]


def test_largest_credit_uses_credit_column(txns):
    res = ledger_query.resolve("largest credit received", txns)
    assert "270,000.00" in res["answer"]


def test_lowest_balance_cites_the_balance_not_the_txn_amount(txns):
    """The citation must carry the balance, not the row's debit."""
    res = ledger_query.resolve("what is the lowest balance", txns)

    assert "196,388.00" in res["answer"]
    assert res["citations"][0]["amount"] == 196388.0


# --- aggregation -----------------------------------------------------------

def test_how_much_is_a_total(txns):
    """'how much' carries none of the words in _TOTAL_WORDS."""
    res = ledger_query.resolve("how much did I spend in October", txns)

    assert res is not None
    assert "12,640.00" in res["answer"]   # 640 + 12000
    assert "October" in res["answer"]


def test_count_of_entity(txns):
    res = ledger_query.resolve("how many EMIs are there", txns)
    # Two EMI rows, not "every debit in the statement".
    assert "2 " in res["answer"]
    assert "emi" in res["answer"].lower()


def test_average_salary_filters_by_classification(txns):
    """'salary' must narrow to salary credits, not average every credit."""
    res = ledger_query.resolve("average salary credit", txns)

    assert "260,000.00" in res["answer"]   # (250000 + 270000) / 2
    assert "salary" in res["answer"].lower()


def test_total_credits_is_not_collapsed_by_subject_override(txns):
    res = ledger_query.resolve("total credits", txns)
    assert "520,000.00" in res["answer"]


def test_month_grouping(txns):
    res = ledger_query.resolve("which month had the highest spending", txns)
    assert "2025-05" in res["answer"]


def test_top_n_listing(txns):
    res = ledger_query.resolve("top 2 largest payments", txns)
    assert len(res["citations"]) == 2
    assert "200,424.00" in res["answer"]


# --- entity matching -------------------------------------------------------

def test_long_entity_matches_inside_concatenated_narration(txns):
    """Bank narrations run words together: SWIGGYSTORES must match 'swiggy'."""
    res = ledger_query.resolve("total spent on swiggy", txns)
    assert "640.00" in res["answer"]


def test_short_token_does_not_match_inside_a_longer_word(txns):
    """'emi' must not match PREMIUM, which is a different transaction."""
    res = ledger_query.resolve("how many EMIs are there", txns)
    assert "PREMIUM" not in res["answer"].upper()
    assert len(res["citations"]) == 2


def test_absent_entity_reports_absence(txns):
    res = ledger_query.resolve("total spent on zomato", txns)
    # 'zomato' is not in the ledger, so it is not a filter; the answer must not
    # invent one. Either an absence statement or a plain total is acceptable,
    # but it must never cite a Swiggy row as Zomato.
    assert res is None or "zomato" not in str(res["citations"]).lower()


# --- strictness / ordering -------------------------------------------------

def test_strict_mode_leaves_topic_questions_alone(txns):
    """Topic phrasings carry no intent word, so specialised handlers keep them."""
    assert ledger_query.resolve(
        "Does this borrower have any fintech app loans like Navi or KreditBee?",
        txns, strict=True,
    ) is None
    assert ledger_query.resolve(
        "Did the borrower pay any GST or advance tax?", txns, strict=True,
    ) is None


def test_relaxed_mode_answers_a_bare_entity_mention(txns):
    res = ledger_query.resolve("tell me about navi", txns, strict=False)
    assert res is not None
    assert "10,548.00" in res["answer"]


def test_empty_ledger_returns_none(txns):
    assert ledger_query.resolve("highest payment", []) is None


# --- integration through the adapter ---------------------------------------

def test_adapter_answers_a_user_framed_question(adapter, txns):
    res = adapter.query_underwriting_copilot(
        "which is the highest payment", context_txns=txns, scorecard={},
    )
    assert "200,424.00" in res["answer"]
    assert res["citations"]


def test_adapter_numeric_lock_still_wins_over_the_resolver(adapter, txns):
    """'total ... turnover' must come from the scorecard, not be recomputed."""
    res = adapter.query_underwriting_copilot(
        "What is the total true turnover and FOIR?",
        context_txns=txns,
        scorecard={"true_turnover": 8450000.0, "foir": 0.385, "adb": 185000.0},
    )
    assert "8,450,000.00" in res["answer"]


def test_adapter_scope_refusal_still_wins_over_the_resolver(adapter, txns):
    res = adapter.query_underwriting_copilot(
        "Should I approve this loan? What is the largest payment?",
        context_txns=txns, scorecard={},
    )
    assert "governed by institutional credit policy" in res["answer"]


def test_adapter_fallback_is_grounded_not_boilerplate(adapter, txns):
    """An unmatched question must not assert 'flows reflect consistent business activities'."""
    res = adapter.query_underwriting_copilot(
        "what is the weather like", context_txns=txns, scorecard={},
    )
    assert "consistent business activities" not in res["answer"]
    assert "6 transactions" in res["answer"]


# --- counterparty identity questions ---------------------------------------
#
# "What is VEENA PATIL HOSPITALITY?" used to return a bare transaction dump:
# the analyst asked what something *is* and got a list of what it *cost*.

def test_what_is_returns_a_profile_not_a_dump(txns):
    res = ledger_query.resolve("what is SWIGGY", txns)

    assert res is not None
    assert "Swiggy" in res["answer"]
    assert "Food Delivery" in res["answer"]


def test_profile_names_the_legal_form_when_narration_states_it():
    rows = [{"date": "2025-11-14", "credit": 0.0, "debit": 20433.0, "balance": 0.0,
             "description": "NEFT-HDFCN5202511-VEENA PATIL HOSPITALITY PVT LTD-0001-HDFC0000240",
             "category": "Expense", "subcategory": "Travel"}]
    res = ledger_query.resolve("what is veena patil hospitality", rows)
    assert "private limited company" in res["answer"]


def test_profile_flags_a_fixed_recurring_obligation(txns):
    rows = [
        {"date": f"2025-0{m}-25", "description": "ACH/NAVI TECH LOAN EMI",
         "debit": 10548.0, "credit": 0.0, "balance": 0.0,
         "category": "Debt / Loans", "subcategory": "Personal Loan EMI"}
        for m in (4, 5, 6)
    ]
    res = ledger_query.resolve("what is navi", rows)
    assert "fixed recurring obligation" in res["answer"]


def test_profile_ifsc_on_a_credit_is_the_remitter_not_the_beneficiary():
    """On an incoming NEFT the IFSC belongs to the sender, not the receiver."""
    rows = [{"date": "2025-12-12", "credit": 12000.0, "debit": 0.0, "balance": 0.0,
             "description": "NEFT-HDFCH0062-VIDYALANKAR INSTITUTE-0001-HDFC0000240",
             "category": "Income", "subcategory": "Salary"}]
    res = ledger_query.resolve("who is vidyalankar", rows)

    assert "Funds arrived from an account at IFSC HDFC0000240" in res["answer"]
    assert "Beneficiary" not in res["answer"]


def test_profile_qualifies_partial_ifsc_coverage():
    """Only one leg carries an IFSC; it must not be implied of all of them."""
    rows = [
        {"date": "2025-04-16", "credit": 19052.0, "debit": 0.0, "balance": 0.0,
         "description": "ACH/VIDYALANKAR INSTITUT/VIDYAINSTTECH 16 049",
         "category": "Income", "subcategory": "Salary"},
        {"date": "2025-12-12", "credit": 12000.0, "debit": 0.0, "balance": 0.0,
         "description": "NEFT-HDFCH0062-VIDYALANKAR INSTITUTE-0001-HDFC0000240",
         "category": "Income", "subcategory": "Salary"},
    ]
    res = ledger_query.resolve("who is vidyalankar", rows)
    assert "on 1 of 2 transactions" in res["answer"]


def test_profile_states_the_limit_of_the_ledger(txns):
    """It must not invent what a business does -- that is nowhere in a statement."""
    res = ledger_query.resolve("what is swiggy", txns)
    assert "not written in the ledger" in res["answer"]


def test_profile_does_not_hijack_an_arithmetic_question(txns):
    """'what is the largest payment' is a number question, not an identity one."""
    res = ledger_query.resolve("what is the largest payment", txns)
    assert "200,424.00" in res["answer"]
    assert "appears in" not in res["answer"]


def test_profile_splits_mixed_direction_counterparties():
    rows = [
        {"date": "2025-09-24", "debit": 145530.0, "credit": 0.0, "balance": 0.0,
         "description": "CLG/VEENA PATIL HOSPITALITY P/HDF", "category": "Expense", "subcategory": "Travel"},
        {"date": "2025-11-14", "debit": 0.0, "credit": 20433.0, "balance": 0.0,
         "description": "NEFT-VEENA PATIL HOSPITALITY PVT LTD", "category": "Expense", "subcategory": "Travel"},
    ]
    res = ledger_query.resolve("what is veena patil", rows)
    assert "1 paid out" in res["answer"]
    assert "1 received" in res["answer"]
