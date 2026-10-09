"""
Cross-engine reconciliation tests.

These are the strongest oracle available without hand-labelled data: they do not
assert any particular value, only that the engines agree with each other and
with the account ledger. Every one of them failed on the pre-fix pipeline.
"""

import pandas as pd
import pytest

from src.engines import balance, cashflow, expense, income, savings
from src.utils import reconciliation
from src.utils.validation import (
    clean_numeric,
    reorder_intraday_by_balance_chain,
)


def _statement(rows):
    df = pd.DataFrame(rows, columns=["date", "description", "debit", "credit", "balance"])
    df["date"] = pd.to_datetime(df["date"])
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    return df


@pytest.fixture
def scrambled_day():
    """Three debits on one day, deliberately out of statement order."""
    return _statement([
        ("2025-04-01", "OPENING TXN", 1000.0, 0.0, 99000.0),
        ("2025-04-02", "DEBIT B", 2000.0, 0.0, 95000.0),   # actually 2nd
        ("2025-04-02", "DEBIT A", 2000.0, 0.0, 97000.0),   # actually 1st
        ("2025-04-02", "DEBIT C", 5000.0, 0.0, 90000.0),   # actually 3rd
        ("2025-04-03", "SALARY", 0.0, 50000.0, 140000.0),
    ])


class TestIntradayOrdering:
    def test_reorder_recovers_statement_order(self, scrambled_day):
        out, mismatches = reorder_intraday_by_balance_chain(scrambled_day)
        assert mismatches == 0
        assert list(out["description"]) == [
            "OPENING TXN", "DEBIT A", "DEBIT B", "DEBIT C", "SALARY",
        ]

    def test_chain_holds_after_reorder(self, scrambled_day):
        out, _ = reorder_intraday_by_balance_chain(scrambled_day)
        expected = out["balance"].shift(1) - out["debit"] + out["credit"]
        assert (out["balance"] - expected).abs().iloc[1:].max() < 0.01

    def test_end_of_day_balance_is_correct(self, scrambled_day):
        """The last row of a day must be that day's true closing balance."""
        out, _ = reorder_intraday_by_balance_chain(scrambled_day)
        eod = out.groupby(out["date"].dt.normalize())["balance"].last()
        assert eod.loc[pd.Timestamp("2025-04-02")] == 90000.0


class TestCleanNumeric:
    @pytest.mark.parametrize("raw,expected", [
        ("500 DR", 500.0),          # the character-class bug returned 0.0
        ("1,200 Cr", 1200.0),
        ("(500)", -500.0),          # accounting negative
        ("Rs 1,234.56", 1234.56),
        ("INR 2,000", 2000.0),
        ("-750", -750.0),
        ("", 0.0),
    ])
    def test_parses_indian_amount_formats(self, raw, expected):
        assert clean_numeric(raw) == pytest.approx(expected)

    def test_dr_marks_balance_negative_only_when_requested(self):
        assert clean_numeric("5,000 Dr", treat_dr_as_negative=True) == -5000.0
        assert clean_numeric("5,000 Dr") == 5000.0


class TestLedgerInvariants:
    """The whole-bundle checks, run against a small end-to-end statement."""

    @pytest.fixture
    def classified(self):
        df = _statement([
            ("2025-01-01", "NEFT SALARY ACME CORP", 0.0, 100000.0, 150000.0),
            ("2025-01-05", "ACH DEBIT HDFC BANK LOAN EMI", 20000.0, 0.0, 130000.0),
            ("2025-01-10", "SWIGGY ORDER", 500.0, 0.0, 129500.0),
            ("2025-02-01", "NEFT SALARY ACME CORP", 0.0, 100000.0, 229500.0),
            ("2025-02-05", "ACH DEBIT HDFC BANK LOAN EMI", 20000.0, 0.0, 209500.0),
            ("2025-02-20", "REFUND REVERSAL AMAZON", 0.0, 1000.0, 210500.0),
        ])
        df["category"] = ["Income", "Expense", "Expense", "Income", "Expense", "Income"]
        df["subcategory"] = [
            "Salary", "Home Loan EMI", "Food Delivery",
            "Salary", "Home Loan EMI", "Refund / Reversal",
        ]
        df["needs_wants"] = ["N/A", "Need", "Want", "N/A", "Need", "N/A"]
        df["merchant_entity"] = ["ACME CORP", "", "Swiggy", "ACME CORP", "", "Amazon"]
        return df

    def _features(self, df):
        ctx = {"bank_config": {}}
        inc = income.process(df.copy(), ctx)
        bal = balance.process(df.copy(), ctx)
        cf = cashflow.process(df.copy(), ctx)
        ctx.update({"income": inc, "balance": bal, "cash_flow": cf})
        exp = expense.process(df.copy(), ctx)
        ctx["expense"] = exp
        sav = savings.process(df.copy(), ctx)
        return {"income": inc, "expense": exp, "balance": bal,
                "cash_flow": cf, "savings": sav}

    def test_all_invariants_pass(self, classified):
        report = reconciliation.check(classified, self._features(classified))
        failed = [c["check"] for c in report["checks"] if not c["passed"]]
        assert report["status"] == "PASS", f"failed invariants: {failed}"

    def test_savings_equals_balance_movement(self, classified):
        """Savings previously reported a surplus while the balance fell."""
        feats = self._features(classified)
        total_savings = sum(feats["savings"]["monthly_savings"].values())
        ledger = float(classified["credit"].sum() - classified["debit"].sum())
        assert total_savings == pytest.approx(ledger, abs=1.0)

    def test_refunds_are_not_counted_as_income(self, classified):
        """The Rs 1,000 reversal must not appear in earnings."""
        feats = self._features(classified)
        assert feats["income"]["total_income"] == pytest.approx(200000.0)

    def test_reconciliation_detects_a_broken_bundle(self, classified):
        """The harness must actually fail when the numbers disagree."""
        feats = self._features(classified)
        feats["income"]["total_income"] += 50000.0
        report = reconciliation.check(classified, feats)
        assert report["status"] == "FAIL"
        assert report["failed_count"] >= 1


class TestRecurringIncomePromotion:
    """
    Earnings do not always arrive labelled. Rental income, freelance retainers
    and family support land as plain transfers from one counterparty; a
    self-employed applicant's entire income can look like "transfers in".
    """

    def _monthly_transfers(self, payer, amounts):
        rows = []
        bal = 50000.0
        for i, amt in enumerate(amounts):
            bal += amt
            rows.append((f"2025-{i + 1:02d}-05", f"NEFT CREDIT FROM {payer}", 0.0, amt, bal))
        df = _statement(rows)
        df["category"] = "Transfer"
        df["subcategory"] = "Bank Transfer In"
        df["merchant_entity"] = payer
        return df

    def test_recurring_transfer_is_promoted_to_income(self):
        df = self._monthly_transfers("GIRISH BABAJI G", [25000.0] * 6)
        out = income.process(df, {})
        assert out["total_income"] == pytest.approx(150000.0)

    def test_one_off_transfer_is_not_income(self):
        """A single large transfer must not be mistaken for earnings."""
        df = self._monthly_transfers("SOME PERSON", [250000.0])
        out = income.process(df, {})
        assert out["total_income"] == 0.0

    def test_erratic_transfers_are_not_income(self):
        """Varying amounts fail the consistency test even if monthly."""
        df = self._monthly_transfers("RANDOM PAYER", [5000.0, 90000.0, 12000.0, 60000.0])
        out = income.process(df, {})
        assert out["total_income"] == 0.0
