"""
Tests for recurrence detection, counterparty identity, learned overrides and
self-transfer detection.

These cover the transactions whose purpose the narration never states. The bank
truncates the payee before the PDF is written -- ICICI at 10 characters, SBI's
UPI field at 8 -- so the identifying token is gone at source. What remains is
shape (a fixed amount arriving monthly), identity (the same counterparty across
statements), and what a human tells us once.
"""

import pandas as pd
import pytest

from src.classifier import TransactionClassifier
from src.engines.recurrence import (
    IRREGULAR,
    MONTHLY,
    detect_recurring_groups,
    summarise,
)
from src.rules import counterparty as cp


def _frame(rows):
    df = pd.DataFrame(rows, columns=["date", "description", "debit", "credit", "balance"])
    df["date"] = pd.to_datetime(df["date"])
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    return df


def _monthly(payee, amounts, start="2025-01-15", skip=()):
    """A payment on roughly the 15th of each month, optionally skipping months."""
    rows, bal = [], 100000.0
    month = pd.Timestamp(start)
    for i, amt in enumerate(amounts):
        if i in skip:
            month += pd.DateOffset(months=1)
            continue
        bal -= amt
        rows.append((month.strftime("%Y-%m-%d"),
                     f"BIL/NEFT/REF{i:05d}/{payee}/SOME BANK", amt, 0.0, bal))
        month += pd.DateOffset(months=1)
    return _frame(rows)


class TestRecurrenceDetection:
    def test_fixed_monthly_obligation_is_found(self):
        df = _monthly("SURYODAYA ", [1300.0] * 12)
        df["key"] = "SURYODAYA"
        groups = detect_recurring_groups(df, key_col="key", amount_col="debit")
        assert len(groups) == 1
        g = groups[0]
        assert g.cadence == MONTHLY
        assert g.is_fixed
        assert g.occurrences == 12
        assert g.median_amount == pytest.approx(1300.0)
        assert g.missed == 0

    def test_annual_rate_revision_stays_fixed(self):
        """
        A revised standing charge is still a standing charge.

        Society maintenance and subscriptions get re-rated -- 1300 to 1325 is a
        +1.9% revision, not noise. A single tolerance band (or a coefficient of
        variation) treats the step as variance and demotes the group, which is
        backwards: the step is evidence of an administered price.
        """
        df = _monthly("SURYODAYA ", [1300.0] * 9 + [1325.0] * 3)
        df["key"] = "SURYODAYA"
        g = detect_recurring_groups(df, key_col="key", amount_col="debit")[0]
        assert g.is_fixed
        assert g.cadence == MONTHLY
        assert g.has_revision
        assert g.amount_steps == [1300.0, 1325.0]

    def test_missed_payments_are_counted(self):
        """
        The risk-relevant case: a monthly obligation that was not always paid.

        The reference implementation gates on the *mean* gap, so two skipped
        months drag the average outside the monthly window, the group is
        rejected, and the misses it exists to find are never counted. Median gap
        survives the skips.
        """
        df = _monthly("GAUTAMI", [50000.0] * 12, skip=(2, 3, 7, 8))
        df["key"] = "GAUTAMI"
        g = detect_recurring_groups(df, key_col="key", amount_col="debit")[0]
        assert g.cadence == MONTHLY, "mean-gap gating would have rejected this group"
        assert g.occurrences == 8
        assert g.missed == 4
        assert g.regularity_pct < 100

    def test_many_distinct_amounts_are_not_one_revised_obligation(self):
        """181 mutual-fund SIPs of assorted sizes are not a 42-step revision."""
        amounts = [1000.0, 5000.0, 2000.0, 2500.0, 4000.0, 1500.0,
                   3000.0, 2000.0, 5000.0, 1000.0, 2500.0, 4000.0]
        df = _monthly("ICICI Direct", amounts)
        df["key"] = "ICICI Direct"
        g = detect_recurring_groups(df, key_col="key", amount_col="debit")[0]
        assert not g.is_fixed
        assert g.amount_steps == []

    def test_one_off_payments_are_not_recurring(self):
        df = _monthly("SOMEONE", [5000.0, 5000.0])
        df["key"] = "SOMEONE"
        assert detect_recurring_groups(df, key_col="key", amount_col="debit") == []

    def test_summary_reports_monthly_commitment(self):
        df = _monthly("RASMECCC", [10548.0] * 12)
        df["key"] = "RASMECCC"
        s = summarise(detect_recurring_groups(df, key_col="key", amount_col="debit"))
        assert s["monthly_obligation_count"] == 1
        assert s["monthly_obligation_total"] == pytest.approx(10548.0)


class TestCounterpartyIdentity:
    def test_truncated_spellings_match(self):
        """Banks cut the payee at differing widths, so one person appears
        several ways. Exact matching finds none of the known cross-bank pairs."""
        assert cp.keys_match("GIRISH BAB", "GIRISH BABAJI G")
        assert cp.keys_match("FAIZ AQEE", "FAIZ AQEEL QURESHI")
        assert not cp.keys_match("GAUTAMI", "GIRISH BAB")

    def test_injected_whitespace_does_not_split_a_group(self):
        """ICICI's text layer emits both 'ST ATE BANK OF I' and 'STATE BANK OF I'."""
        a = cp.build_counterparty_key(payee="GAUTAMI", counterparty_bank="ST ATE BANK OF I")
        b = cp.build_counterparty_key(payee="GAUTAMI", counterparty_bank="STATE BANK OF I")
        assert a == b

    def test_cooperative_marker_survives_normalisation(self):
        key = cp.build_counterparty_key(payee="SURYODAYA ", counterparty_bank="ABHYUDAYA CO-OP")
        assert "COOP" in key

    def test_vpa_bridges_two_banks(self):
        """The UPI handle survives truncation better than the payee name."""
        icici = cp.build_counterparty_key(
            payee="GIRISH BAB",
            description="UPI/GIRISH BAB/ggidaye-1@oksb/UPI/BANK OF BA/517860587311")
        sbi = cp.build_counterparty_key(
            payee="GIRISH B",
            description="WDL TFR UPI/DR/417772689498/GIRISH B/ICIC/ggidaye@ok/UPI")
        assert cp.keys_match(icici, sbi)

    def test_canonicalisation_collapses_variants(self):
        canonical = cp.canonicalise_keys(["FAIZ AQEE", "FAIZ AQEEL QURESHI"])
        assert len(set(canonical.values())) == 1


class TestSelfTransfer:
    HOLDER = "GIRISH BABAJI GIDAYE"

    def test_own_account_is_flagged(self):
        is_self, reason = cp.is_self_transfer(
            account_holder=self.HOLDER,
            payee="GIRISH BAB",
            description="BIL/NEFT/REF/GIRISH BAB/STATE BANK OF I")
        assert is_self and reason

    def test_upi_handle_matches_holder(self):
        is_self, _ = cp.is_self_transfer(
            account_holder=self.HOLDER, payee="",
            description="UPI/GIRISH BAB/ggidaye@oksbi/UPI/State Bank/523170")
        assert is_self

    def test_unrelated_payee_is_not_self(self):
        is_self, _ = cp.is_self_transfer(
            account_holder=self.HOLDER, payee="MANISH MO",
            description="UPI/P2A/311400428135/MANISH MO/Union Ban/Village")
        assert not is_self

    def test_no_holder_name_means_no_guessing(self):
        """A shared surname is a relative at least as often as a second account."""
        is_self, _ = cp.is_self_transfer(
            account_holder="", payee="GIRISH BAB",
            description="BIL/NEFT/REF/GIRISH BAB/STATE BANK")
        assert not is_self

    def test_label_carries_the_bracket_form(self):
        assert cp.annotate_self_transfer("P2P Transfer Out") == "P2P Transfer Out (Self Transfer)"
        # Idempotent -- re-labelling must not stack brackets.
        assert cp.annotate_self_transfer(
            "P2P Transfer Out (Self Transfer)") == "P2P Transfer Out (Self Transfer)"

    def test_classifier_marks_and_labels_self_transfers(self):
        df = _frame([
            ("2025-04-17", "BIL/NEFT/ICICN1/GIRISH BAB/STATE BANK OF I", 0.0, 50000.0, 150000.0),
            ("2025-05-17", "UPI/P2A/311400428135/MANISH MO/Union Ban/Village", 500.0, 0.0, 149500.0),
        ])
        clf = TransactionClassifier(settings={"account_holder_name": self.HOLDER})
        out = clf.classify_dataframe(df, "ICICI")
        assert bool(out.iloc[0]["is_self_transfer"])
        assert "(Self Transfer)" in out.iloc[0]["subcategory"]
        assert not bool(out.iloc[1]["is_self_transfer"])


class TestLearnedOverrides:
    @pytest.fixture
    def registry(self, tmp_path):
        original = cp._registry
        reg = cp.get_registry(tmp_path / "overrides.json")
        yield reg
        cp._registry = original

    def test_label_persists_and_reloads(self, registry, tmp_path):
        registry.set("SURYODAYA|ABHYUDAYACOOP", category="Expense",
                     subcategory="Society / Property Tax", needs_wants="Need")
        fresh = cp.CounterpartyRegistry(tmp_path / "overrides.json")
        found = fresh.lookup("SURYODAYA|ABHYUDAYACOOP")
        assert found["subcategory"] == "Society / Property Tax"

    def test_lookup_tolerates_truncation(self, registry):
        registry.set("GIRISH BABAJI G", category="Transfer", subcategory="Family Support")
        assert registry.lookup("GIRISH BAB") is not None

    def test_applicant_scope_beats_global(self, registry):
        registry.set("ACME", category="Expense", subcategory="Rent", scope="global")
        registry.set("ACME", category="Income", subcategory="Salary",
                     scope="applicant", applicant_id="app-1")
        assert registry.lookup("ACME")["subcategory"] == "Rent"
        assert registry.lookup("ACME", applicant_id="app-1")["subcategory"] == "Salary"
        # A different applicant still sees the global label.
        assert registry.lookup("ACME", applicant_id="app-2")["subcategory"] == "Rent"

    def test_override_applies_across_a_statement(self, registry):
        registry.set("SURYODAYA|SOMEBANK", category="Expense",
                     subcategory="Society / Property Tax", needs_wants="Need")
        df = _monthly("SURYODAYA ", [1300.0] * 6)
        out = TransactionClassifier().classify_dataframe(df, "ICICI")
        assert (out["subcategory"] == "Society / Property Tax").all()
        assert (out["needs_wants"] == "Need").all()

    def test_override_does_not_replace_a_confident_rule(self, registry):
        """A human label fills gaps; it must not silently overwrite a firm result."""
        registry.set("SWIGGY", category="Investment", subcategory="Mutual Funds / SIP")
        df = _frame([("2025-04-17", "SWIGGY ORDER 8829", 450.0, 0.0, 99550.0)])
        out = TransactionClassifier().classify_dataframe(df, "Other")
        assert out.iloc[0]["subcategory"] == "Food Delivery"

    def test_delete_removes_the_label(self, registry):
        registry.set("TEMP CO", category="Expense", subcategory="Rent")
        assert registry.delete("TEMP CO") is True
        assert registry.lookup("TEMP CO") is None
