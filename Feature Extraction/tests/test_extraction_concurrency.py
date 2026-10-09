"""
Extraction must be correct when several statements are processed at once.

The web app runs each upload through `asyncio.to_thread`, so concurrent uploads
put several threads inside PyMuPDF simultaneously. MuPDF keeps per-context state
and is not thread-safe: rather than raising, it silently returned PARTIAL tables.
Measured on this corpus before the fix, six concurrent extractions cut Axis from
422 rows to 273 and SBI from 71 to 54 -- and both were then scored and reported
to the user as "success".

Row loss happened *within* pages, so page-level diagnostics did not catch it.
Only a row-count check does, which is why this test asserts exact counts.
"""

import concurrent.futures
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = REPO_ROOT / "Real_Data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fitz", reason="PyMuPDF is required to read the statements")

# statement -> (template, exact row count when extracted alone)
CORPUS = {
    "AXIS.pdf": ("Axis", 422),
    "ICICI.pdf": ("ICICI", 358),
    "SBI_BANK.pdf": ("SBI", 71),
    "UNION.pdf": ("Union", 6),
    "BOB.pdf": ("BOB", 43),
    "BOI.PDF": ("Bank Of India", 137),
}


def _available():
    return {n: v for n, v in CORPUS.items() if (REAL_DATA / n).exists()}


def _extract(name, bank):
    from extractor import StandalonePDFExtractor

    return name, len(StandalonePDFExtractor().extract_with_template(REAL_DATA / name, bank))


def test_row_counts_are_stable_under_concurrency():
    corpus = _available()
    if len(corpus) < 2:
        pytest.skip("need at least two sample statements to exercise concurrency")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(corpus)) as pool:
        results = dict(
            pool.map(lambda item: _extract(item[0], item[1][0]), corpus.items())
        )

    wrong = {
        name: (results[name], expected)
        for name, (_bank, expected) in corpus.items()
        if results[name] != expected
    }
    assert not wrong, (
        "concurrent extraction lost rows (name: got, expected) -- PyMuPDF is not "
        f"thread-safe and fails silently: {wrong}"
    )


@pytest.mark.parametrize("name", list(CORPUS))
def test_row_counts_alone(name):
    """The sequential baseline the concurrency test compares against."""
    if not (REAL_DATA / name).exists():
        pytest.skip(f"{name} not present in Real_Data/")
    bank, expected = CORPUS[name]
    assert _extract(name, bank)[1] == expected


def test_sbi_row_count_matches_the_count_printed_on_the_statement():
    """
    SBI prints `Dr Count 50` and `Cr Count 21` in its summary block. The parsed
    row count must equal 71 -- an independent oracle that needs no labels, and
    the strongest single anchor in the corpus.
    """
    if not (REAL_DATA / "SBI_BANK.pdf").exists():
        pytest.skip("SBI_BANK.pdf not present in Real_Data/")
    assert _extract("SBI_BANK.pdf", "SBI")[1] == 50 + 21


def test_extraction_reports_diagnostics():
    """Callers need to know how the statement was read, not just what came out."""
    from extractor import StandalonePDFExtractor

    if not (REAL_DATA / "AXIS.pdf").exists():
        pytest.skip("AXIS.pdf not present in Real_Data/")

    df = StandalonePDFExtractor().extract_with_template(REAL_DATA / "AXIS.pdf", "Axis")
    diag = df.attrs.get("extraction_diagnostics")
    assert diag, "extract_with_template must attach extraction diagnostics"
    assert diag["template_fallback"] is False
    assert diag["template_used"] == "Axis"
    assert diag["pages_total"] == 14
    assert diag["rows_extracted"] == len(df)


def test_unknown_bank_is_flagged_as_a_template_fallback():
    """
    Parsing with the generic template is the highest-risk misalignment path --
    it produces rows that parse but may map amounts to the wrong columns. It
    must never happen silently.
    """
    from extractor import StandalonePDFExtractor

    if not (REAL_DATA / "AXIS.pdf").exists():
        pytest.skip("AXIS.pdf not present in Real_Data/")

    df = StandalonePDFExtractor().extract_with_template(REAL_DATA / "AXIS.pdf", "Canara")
    diag = df.attrs.get("extraction_diagnostics")
    assert diag["template_fallback"] is True
    assert diag["requested_bank"] == "Canara"
    assert diag["template_used"] == "Other"
