"""
Tests for Module 1 — Transaction Classifier

Tests across multiple bank formats: SBI, ICICI, Axis, BOI, generic.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.classifier import TransactionClassifier
from src.rules.bank_rules import (
    get_description_parser,
    icici_parse_description,
    sbi_parse_description,
    axis_parse_description,
    boi_parse_description,
)


@pytest.fixture
def classifier():
    """Create a classifier with default settings (no SLM)."""
    settings = {
        "model": {"name": "models/distilbert-mnli", "confidence_threshold": 0.5},
        "fuzzy": {"default_threshold": 80, "finacle_threshold": 70},
        "banks": {},
    }
    return TransactionClassifier(settings=settings)


@pytest.fixture
def sample_icici_transactions():
    """Sample ICICI transactions from real data."""
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2025-04-01", "2025-04-04", "2025-04-16",
            "2025-04-17", "2025-06-20", "2025-06-27",
            "2025-06-30", "2025-08-25", "2025-09-24",
        ]),
        "description": [
            "EBA/MFP-8509197518-175255653-S-1136903-193654647",
            "CAM/09571HRY/CASH WDL/04-04-25",
            "ACH/VIDYALANKAR INSTITUT/VIDYAINSTTECH 16 049",
            "BIL/NEFT/ICICN12025041777628777/PPF SBI/STATE BANK OF I",
            "BIL/ONL/001030804865/Bajaj Alli/BajajAllianzGen/MEDICLAIM",
            "BIL/ONL/001033127064/Acko Gener/wwwackocom24049",
            "087401502352:Int.Pd:29-03-2025 to 29-06-2025",
            "ACH/COAL INDIA LTD/2230874",
            "CLG/VEENA PATIL HOSPITALITY P/HDF - Cheque No: 7964",
        ],
        "debit": [2000, 25000, 0, 5000, 34807, 7951, 0, 0, 145530],
        "credit": [0, 0, 19052, 0, 0, 0, 1260, 1634, 0],
        "balance": [336577, 301694, 316746, 311746, 99480, 19216, 36476, 158719, 153637],
        "bank_name": ["ICICI"] * 9,
        "year_month": [
            "2025-04", "2025-04", "2025-04", "2025-04",
            "2025-06", "2025-06", "2025-06", "2025-08", "2025-09",
        ],
    })


class TestDescriptionParsers:
    """Test bank-specific description parsers."""

    def test_icici_eba_mf(self):
        result = icici_parse_description("EBA/MFP-8509197518-175255653-S-1136903-193654647")
        assert result["rail"] == "EBA_MF"

    def test_icici_eba_eq(self):
        result = icici_parse_description("EBA/EQ Trade 17MAR/20260317163854")
        assert result["rail"] == "EBA_EQ"

    def test_icici_upi(self):
        result = icici_parse_description("UPI/bajajfinanceltd/UPI Mandate/INDUSIND BANK L/100097771667/ref")
        assert result["rail"] == "UPI"
        assert "bajajfinanceltd" in result["payee"]

    def test_icici_ach(self):
        result = icici_parse_description("ACH/VIDYALANKAR INSTITUT/VIDYAINSTTECH 16 049")
        assert result["rail"] == "ACH"
        assert "VIDYALANKAR" in result["payee"]

    def test_icici_bil_neft(self):
        result = icici_parse_description("BIL/NEFT/ICICN12025041777628777/PPF SBI/STATE BANK OF I")
        assert result["rail"] == "NEFT"
        assert "PPF SBI" in result["payee"]

    def test_icici_cam_atm(self):
        result = icici_parse_description("CAM/09571HRY/CASH WDL/04-04-25")
        assert result["rail"] == "ATM"

    def test_icici_interest(self):
        result = icici_parse_description("087401502352:Int.Pd:29-03-2025 to 29-06-2025")
        assert result["rail"] == "INTEREST"

    def test_sbi_upi_debit(self):
        result = sbi_parse_description("TO TRANSFER-UPI/DR/123456/AMAZON/SBI/amazon@ybl/SHOPPING")
        assert result["rail"] == "UPI"
        assert result["payee"] == "AMAZON"

    def test_axis_p2m(self):
        result = axis_parse_description("UPI/P2M/REF123/SWIGGY/swiggy@ybl")
        assert result["rail"] == "UPI"
        assert result["is_p2m"] is True
        assert result["payee"] == "SWIGGY"

    def test_axis_p2a(self):
        result = axis_parse_description("UPI/REF123/JOHN DOE/john@upi")
        assert result["rail"] == "UPI"
        assert result.get("is_p2m") is not True

    def test_boi_upi_dash(self):
        result = boi_parse_description("UPI-SWIGGY-swiggy@ybl-REF123")
        assert result["rail"] == "UPI"
        assert result["payee"] == "SWIGGY"


class TestClassifier:
    """Test the full classification pipeline."""

    def test_icici_sip_classification(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        # EBA/MFP should be classified as Investment/MF SIP
        sip_row = df[df["description"].str.startswith("EBA/MFP-")].iloc[0]
        assert sip_row["category"] == "Investment"
        assert "Mutual Funds" in sip_row["subcategory"] or "SIP" in sip_row["subcategory"]
        assert sip_row["classification_method"] == "bank_rule"

    def test_icici_atm_classification(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        atm_row = df[df["description"].str.contains("CASH WDL")].iloc[0]
        assert atm_row["category"] == "Banking"
        assert atm_row["subcategory"] == "ATM Withdrawal"

    def test_icici_ppf_classification(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        ppf_row = df[df["description"].str.contains("PPF SBI")].iloc[0]
        assert ppf_row["category"] == "Investment"
        assert "PPF" in ppf_row["subcategory"]

    def test_icici_interest_classification(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        int_row = df[df["description"].str.contains("Int.Pd")].iloc[0]
        assert int_row["category"] == "Income"
        assert int_row["subcategory"] == "Interest"

    def test_icici_insurance_acko(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        acko_row = df[df["description"].str.contains("Acko")].iloc[0]
        assert acko_row["category"] == "Expense"
        assert acko_row["subcategory"] == "Insurance"

    def test_icici_cheque(self, classifier, sample_icici_transactions):
        """
        A cheque is a payment instrument, not a spending category.

        The fixture pays "VEENA PATIL HOSPITALITY" -- a tour operator -- so the
        row must be categorised by payee and carry Cheque only as a tag.
        Labelling it "Cheque" hid Rs 3,30,750 of travel spend on a real
        statement and left the Travel subcategory empty on every bank.
        """
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        clg_row = df[df["description"].str.contains("CLG/")].iloc[0]
        assert clg_row["subcategory"] == "Travel"
        assert "Cheque" in str(clg_row["tags"])

    def test_cheque_without_identifiable_payee_stays_cheque(self, classifier):
        """With no recognisable payee there is nothing better to say."""
        df = pd.DataFrame([{
            "date": pd.Timestamp("2025-06-15"),
            "description": "CLG/RAMESH KUMAR/SBI - Cheque No: 4412",
            "debit": 15000.0, "credit": 0.0, "balance": 50000.0,
            "year_month": "2025-06",
        }])
        out = classifier.classify_dataframe(df, "ICICI")
        assert out.iloc[0]["subcategory"] == "Cheque"

    def test_transaction_type_debit(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        debit_row = df[df["debit"] > 0].iloc[0]
        assert debit_row["transaction_type"] == "Debit"

    def test_transaction_type_credit(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        credit_row = df[df["credit"] > 0].iloc[0]
        assert credit_row["transaction_type"] == "Credit"

    def test_all_rows_classified(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        # Every row should have a category
        assert (df["category"] != "").all()

    def test_confidence_in_range(self, classifier, sample_icici_transactions):
        df = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")

        assert (df["confidence"] >= 0).all()
        assert (df["confidence"] <= 1).all()


class TestKeywordMatching:
    """Test Tier 2 keyword matching across bank-agnostic keywords."""

    def test_swiggy_wants(self, classifier):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-01"]),
            "description": ["UPI/SWIGGY/ORDER123/ybl"],
            "debit": [500],
            "credit": [0],
            "balance": [10000],
            "bank_name": ["Other"],
            "year_month": ["2025-01"],
        })
        result = classifier.classify_dataframe(df, "Other")
        assert result.iloc[0]["needs_wants"] == "Want"
        assert result.iloc[0]["subcategory"] == "Food Delivery"

    def test_bigbasket_needs(self, classifier):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-01"]),
            "description": ["UPI/BIGBASKET/ORDER456/sbi"],
            "debit": [2000],
            "credit": [0],
            "balance": [8000],
            "bank_name": ["Other"],
            "year_month": ["2025-01"],
        })
        result = classifier.classify_dataframe(df, "Other")
        assert result.iloc[0]["needs_wants"] == "Need"

    def test_netflix_entertainment(self, classifier):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-01"]),
            "description": ["NETFLIX SUBSCRIPTION"],
            "debit": [649],
            "credit": [0],
            "balance": [5000],
            "bank_name": ["Other"],
            "year_month": ["2025-01"],
        })
        result = classifier.classify_dataframe(df, "Other")
        assert result.iloc[0]["subcategory"] == "Entertainment"
        assert result.iloc[0]["needs_wants"] == "Want"

    def test_icici_mmt_imps_not_makemytrip(self, classifier):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-04-17"]),
            "description": ["MMT/IMPS/510711619275/PPF SBI/SBIN0010725"],
            "debit": [5000.0],
            "credit": [0.0],
            "balance": [311746.85],
            "bank_name": ["ICICI"],
            "year_month": ["2025-04"]
        })
        result = classifier.classify_dataframe(df, "ICICI")
        row = result.iloc[0]
        assert row["category"] == "Investment"
        assert row["subcategory"] == "PPF"
        assert row["merchant_entity"] == ""

    def test_warm_model_reuse(self, classifier, sample_icici_transactions):
        # Classify first dataframe
        df1 = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")
        # Classify second dataframe using same warm instance
        df2 = classifier.classify_dataframe(sample_icici_transactions.copy(), "ICICI")
        assert len(df1) == len(df2)
        assert (df1["category"] == df2["category"]).all()

    def test_expanded_deterministic_rules(self, classifier):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            "description": [
                "UPI/BLUSMART/CAB RIDE",
                "COUNTRY DELIGHT MILK SUB",
                "DHAN SECURITIES INVESTMENT",
            ],
            "debit": [350, 120, 5000],
            "credit": [0, 0, 0],
            "balance": [10000, 9880, 4880],
            "bank_name": ["Other", "Other", "Other"],
            "year_month": ["2025-01", "2025-01", "2025-01"],
        })
        result = classifier.classify_dataframe(df, "Other")
        assert result.iloc[0]["subcategory"] == "Taxi"
        assert result.iloc[0]["needs_wants"] == "Need"
        assert result.iloc[1]["subcategory"] == "Grocery / Supermarket"
        assert result.iloc[2]["category"] == "Investment"

