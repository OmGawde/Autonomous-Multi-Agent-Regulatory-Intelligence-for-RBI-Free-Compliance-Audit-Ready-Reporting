"""
Bank detection and account-holder extraction, against the real statements.

Both of these are read off the PDF itself now, so both are pinned here against
`Real_Data/`. The tests copy each statement to a UUID filename first, because
that is exactly what the web app does on upload (`main.py` stores the file as
`{file_id}{extension}`) -- and it was the filename check masking a broken
detector that let an Axis upload be parsed with the ICICI template.
"""

import shutil
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = REPO_ROOT / "Real_Data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fitz", reason="PyMuPDF is required to read the statements")

# statement file -> (expected bank, expected account holder)
STATEMENTS = {
    "AXIS.pdf": ("Axis", "MILIND SURESH WALANJU"),
    "ICICI.pdf": ("ICICI", "GIRISH BABAJI GIDAYE"),
    "SBI_BANK.pdf": ("SBI", "GIRISH BABAJI GIDAYE"),
    "UNION.pdf": ("Union", "ANIRUDH GHANSHYAM SARVE"),
    "BOB.pdf": ("BOB", "OM SANTOSH GAWDE"),
    "BOI.PDF": ("Bank Of India", "MILIND SURESH WALANJU"),
}


@pytest.fixture(scope="module")
def extractor():
    from extractor import StandalonePDFExtractor

    return StandalonePDFExtractor()


def _anonymised_copy(name, tmp_path):
    source = REAL_DATA / name
    if not source.exists():
        pytest.skip(f"{name} not present in Real_Data/")
    target = tmp_path / f"{uuid.uuid4()}.pdf"
    shutil.copy(source, target)
    return target


@pytest.mark.parametrize("name,expected", [(n, v[0]) for n, v in STATEMENTS.items()])
def test_bank_detected_without_filename_hint(extractor, tmp_path, name, expected):
    """The bank must be read from the statement's own content, not its name."""
    assert extractor.detect_bank(_anonymised_copy(name, tmp_path)) == expected


@pytest.mark.parametrize("name,expected", [(n, v[1]) for n, v in STATEMENTS.items()])
def test_account_holder_read_from_statement(extractor, tmp_path, name, expected):
    """The holder is never an operator input -- every statement prints it."""
    result = extractor.extract_account_holder(_anonymised_copy(name, tmp_path))
    assert result["account_holder"] == expected


def test_counterparty_banks_do_not_win_detection(extractor, tmp_path):
    """
    The regression that started this: the Axis statement names ICICI and Kotak
    in its transaction table, and first-match-wins scoring picked ICICI.
    """
    import fitz

    axis = _anonymised_copy("AXIS.pdf", tmp_path)
    page_one = fitz.open(axis)[0].get_text().lower()

    assert "icici" in page_one and "kotak" in page_one, (
        "fixture no longer exercises the bug -- the Axis statement is expected "
        "to name other banks as counterparties"
    )
    assert extractor.detect_bank(axis) == "Axis"


def test_unknown_bank_is_not_guessed(extractor, tmp_path):
    """
    A statement with no issuing-bank signal must come back "Other". Guessing
    picks a column template at random and mis-parses the whole file, which is
    strictly worse than admitting the bank is unknown.
    """
    import fitz

    blank = fitz.open()
    page = blank.new_page()
    page.insert_text((72, 72), "Transaction Date  Narration  Debit  Credit  Balance")
    path = tmp_path / f"{uuid.uuid4()}.pdf"
    blank.save(path)
    blank.close()

    assert extractor.detect_bank(path) == "Other"


def test_missing_holder_returns_none_rather_than_guessing(extractor, tmp_path):
    """Self-transfer detection stands down on None; it must not get a stray line."""
    import fitz

    blank = fitz.open()
    page = blank.new_page()
    page.insert_text((72, 72), "Cheque Number   Transaction Remarks   Balance (INR)")
    path = tmp_path / f"{uuid.uuid4()}.pdf"
    blank.save(path)
    blank.close()

    assert extractor.extract_account_holder(path)["account_holder"] is None
