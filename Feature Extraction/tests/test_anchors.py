"""
Reading the facts a statement prints about itself.

These are the only reference values in the whole pipeline that do not come from
our own extraction, which is what makes them able to catch a parse that is
self-consistent but wrong.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = REPO_ROOT / "Real_Data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fitz", reason="PyMuPDF is required to read the statements")

from src.utils.anchors import extract_anchors, parse_amount  # noqa: E402

# What each statement actually prints. None means "this bank prints no such
# figure" -- a real answer, not a gap to paper over.
EXPECTED = {
    "AXIS.pdf": dict(opening=29155.31, closing=17707.93,
                     debits=774966.38, credits=763519.00, rows=None),
    "SBI_BANK.pdf": dict(opening=17875.01, closing=25279.37,
                         debits=398141.64, credits=405546.00, rows=71),
    "UNION.pdf": dict(opening=2367.34, closing=64026.54,
                      debits=0.30, credits=61659.50, rows=7 - 1),
    "BOB.pdf": dict(opening=427662.57, closing=None,
                    debits=None, credits=None, rows=44 - 1),
    "ICICI.pdf": dict(opening=None, closing=None,
                      debits=None, credits=None, rows=358),
    "BOI.PDF": dict(opening=None, closing=None,
                    debits=None, credits=None, rows=137),
}


def _anchors(name):
    path = REAL_DATA / name
    if not path.exists():
        pytest.skip(f"{name} not present in Real_Data/")
    return extract_anchors(path)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_anchor_values(name):
    a = _anchors(name)
    e = EXPECTED[name]
    assert a.opening_balance == e["opening"], a.sources.get("opening_balance")
    assert a.closing_balance == e["closing"], a.sources.get("closing_balance")
    assert a.total_debits == e["debits"], a.sources.get("total_debits")
    assert a.total_credits == e["credits"], a.sources.get("total_credits")
    assert a.expected_row_count == e["rows"], a.sources.get("expected_row_count")


def test_bob_opening_balance_is_read_by_coordinate_not_reading_order():
    """
    The reason anchors are read from word coordinates rather than page text.

    Flat `get_text()` on BOB page 1 returns the rows interleaved, and the value
    that *appears* to follow "Opening Balance" is 4,27,661.57 -- the next row's
    balance. The words at y=471.3 say the opening balance is 4,27,662.57. A
    verifier built on reading order would validate against a number that is one
    rupee wrong, which is exactly the class of silent error it exists to catch.
    """
    import fitz

    path = REAL_DATA / "BOB.pdf"
    if not path.exists():
        pytest.skip("BOB.pdf not present in Real_Data/")

    flat = fitz.open(path)[0].get_text()
    assert "4,27,661.57" in flat, "fixture no longer reproduces the reading-order trap"

    assert _anchors("BOB.pdf").opening_balance == 427662.57


@pytest.mark.parametrize("name", ["AXIS.pdf", "SBI_BANK.pdf", "UNION.pdf"])
def test_printed_figures_close_arithmetically(name):
    """opening - total debits + total credits == closing, to the rupee."""
    a = _anchors(name)
    implied = a.opening_balance - a.total_debits + a.total_credits
    assert abs(implied - a.closing_balance) < 0.01


def test_sbi_row_count_comes_from_its_printed_dr_and_cr_counts():
    a = _anchors("SBI_BANK.pdf")
    assert (a.debit_count, a.credit_count) == (50, 21)
    assert a.expected_row_count == 71


def test_serial_runs_are_unbroken():
    for name in ("ICICI.pdf", "BOI.PDF", "BOB.pdf", "UNION.pdf"):
        a = _anchors(name)
        assert a.serial_first == 1, name
        assert a.serial_gaps == [], f"{name} has gaps at {a.serial_gaps}"


def test_numbered_opening_balance_row_is_not_counted_as_a_transaction():
    """Union and BOB number their Opening Balance line as serial 1."""
    for name, serial_last in (("UNION.pdf", 7), ("BOB.pdf", 44)):
        a = _anchors(name)
        assert a.serial_last == serial_last
        assert a.serial_non_transaction_rows == 1
        assert a.expected_row_count == serial_last - 1


@pytest.mark.parametrize("name,start,end", [
    ("AXIS.pdf", "2023-04-24", "2024-03-31"),
    ("SBI_BANK.pdf", "2024-04-01", "2025-03-31"),
    ("ICICI.pdf", "2025-04-01", "2026-03-31"),   # long-form English dates
    ("BOI.PDF", "2010-04-01", "2011-03-31"),     # split across from:/to: lines
])
def test_statement_period(name, start, end):
    a = _anchors(name)
    assert (a.period_start, a.period_end) == (start, end)


@pytest.mark.parametrize("token,value", [
    ("29155.31", 29155.31),
    ("4,27,662.57", 427662.57),          # Indian lakh grouping
    ("17,875.01CR", 17875.01),           # suffix with no space
    ("2,367.34 Cr", 2367.34),            # suffix separated by a space
    ("1,234.00DR", -1234.00),
    ("(500)", -500.0),
    ("₹\xa018,608.65", 18608.65),   # rupee sign + non-breaking space
    ("-", None),
    ("", None),
    ("Balance", None),
])
def test_amount_parsing(token, value):
    assert parse_amount(token) == value


def test_missing_anchors_are_reported_as_none_not_zero():
    """ICICI prints no balances at all. Zero would be a lie; None is the truth."""
    a = _anchors("ICICI.pdf")
    assert a.opening_balance is None and a.closing_balance is None
    assert a.total_debits is None and a.total_credits is None
    assert a.any_money_anchor() is False
    assert a.any_count_anchor() is True
