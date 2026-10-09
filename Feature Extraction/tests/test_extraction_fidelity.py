"""
Catching a statement that parsed cleanly but wrongly.

Every corruption below produces a DataFrame that looks entirely healthy on its
own terms -- the balance chain reconciles, the engines run, a credit score comes
out. Only comparison against the figures the bank printed exposes them.

The truncation case is not hypothetical: a PyMuPDF thread-safety bug cut the
Axis statement from 422 rows to 23 under concurrent uploads, and the result was
scored and reported to the user as "success".
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = REPO_ROOT / "Real_Data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fitz", reason="PyMuPDF is required to read the statements")

from src.utils import extraction_fidelity as ef  # noqa: E402
from src.utils.anchors import extract_anchors  # noqa: E402
from src.utils.validation import validate_and_clean  # noqa: E402

RENAME = {"Date": "date", "Description": "description", "Withdrawal Amt.": "debit",
          "Deposit Amt.": "credit", "Closing Balance": "balance"}

ALL_BANKS = [("AXIS.pdf", "Axis"), ("SBI_BANK.pdf", "SBI"), ("UNION.pdf", "Union"),
             ("BOB.pdf", "BOB"), ("ICICI.pdf", "ICICI"), ("BOI.PDF", "Bank Of India")]


def _load(name, bank):
    from extractor import StandalonePDFExtractor

    path = REAL_DATA / name
    if not path.exists():
        pytest.skip(f"{name} not present in Real_Data/")
    raw = StandalonePDFExtractor().extract_with_template(path, bank)
    diagnostics = raw.attrs.get("extraction_diagnostics", {})
    df, stats = validate_and_clean(raw.rename(columns=RENAME), bank)
    return df, extract_anchors(path), {**stats, **diagnostics}


@pytest.fixture(scope="module")
def axis():
    return _load("AXIS.pdf", "Axis")


@pytest.mark.parametrize("name,bank", ALL_BANKS)
def test_a_correct_parse_verifies(name, bank):
    df, anchors, stats = _load(name, bank)
    result = ef.check(df, anchors, stats)
    failed = [c["check"] for c in result["checks"] if not c["passed"]]
    assert result["status"] == "VERIFIED", f"{name} failed: {failed}"


def test_debit_credit_swap_is_caught(axis):
    """
    The case the balance chain provably cannot catch: swapping the columns
    leaves the net movement identical, so the running balance still reconciles.
    """
    df, anchors, stats = axis
    swapped = df.copy()
    swapped["debit"], swapped["credit"] = df["credit"].copy(), df["debit"].copy()

    assert abs(swapped["credit"].sum() - swapped["debit"].sum()
               + df["credit"].sum() - df["debit"].sum()) < 0.01, "net is unchanged by the swap"

    result = ef.check(swapped, anchors, stats)
    assert result["status"] == "FAILED"
    caught = {c["check"] for c in result["checks"] if not c["passed"]}
    assert "debits_match_printed_total" in caught
    assert "credits_match_printed_total" in caught


def test_truncated_statement_is_caught(axis):
    """The exact shape of the concurrency bug: 422 rows silently became 23."""
    df, anchors, stats = axis
    result = ef.check(df.iloc[:23].copy(), anchors, stats)
    assert result["status"] == "FAILED"
    caught = {c["check"] for c in result["checks"] if not c["passed"]}
    assert "closing_matches_printed" in caught


def test_dropped_page_is_caught(axis):
    df, anchors, stats = axis
    result = ef.check(df.drop(df.index[100:160]), anchors, stats)
    assert result["status"] == "FAILED"


def test_count_only_bank_still_catches_truncation():
    """
    ICICI prints no opening balance, no closing balance and no totals. Its
    serial column alone must still catch a short read.
    """
    df, anchors, stats = _load("ICICI.pdf", "ICICI")
    assert anchors.any_money_anchor() is False

    result = ef.check(df.iloc[:300].copy(), anchors, stats)
    assert result["status"] == "FAILED"
    caught = {c["check"] for c in result["checks"] if not c["passed"]}
    assert "row_count_matches_statement" in caught


def test_a_statement_with_no_anchors_is_unverified_not_verified():
    """UNVERIFIED must never be dressed up as a pass."""
    import pandas as pd

    from src.utils.anchors import StatementAnchors

    df = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        "description": ["a", "b"],
        "debit": [100.0, 0.0],
        "credit": [0.0, 50.0],
        "balance": [900.0, 950.0],
    })
    result = ef.check(df, StatementAnchors(), {})
    assert result["status"] == "UNVERIFIED"
    assert result["anchors_found"] == 0
    assert result["reason"]


def test_empty_frame_is_unverified():
    import pandas as pd

    from src.utils.anchors import StatementAnchors

    result = ef.check(pd.DataFrame(), StatementAnchors(), {})
    assert result["status"] == "UNVERIFIED"


def test_a_benign_trailing_blank_page_does_not_fail(axis):
    """
    Axis page 14 is literally "++++ End of Statement ++++". A single trailing
    page with no table is ordinary; several missing pages are not.
    """
    df, anchors, stats = axis
    assert stats.get("pages_without_tables_index") == [13], "fixture changed"
    assert ef.check(df, anchors, stats)["status"] == "VERIFIED"


def test_result_shape_matches_reconciliation():
    """The UI renders both with one component, so the shapes must agree."""
    import pandas as pd

    from src.utils.anchors import StatementAnchors

    result = ef.check(pd.DataFrame(), StatementAnchors(), {})
    assert set(["status", "checks", "failed_count"]).issubset(result)
