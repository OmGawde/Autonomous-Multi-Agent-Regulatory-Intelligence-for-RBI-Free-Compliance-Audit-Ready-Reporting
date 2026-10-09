"""
A bank with no template must become parseable through calibration alone.

This is the difference between "we support six banks" and "a user can add
theirs". The calibrator collected column positions for a long time, but nothing
consumed them: `column_x_positions` was accepted by the upload endpoint, passed
to the worker, and referenced nowhere -- a wire with both ends cut.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = REPO_ROOT / "Real_Data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("fitz", reason="PyMuPDF is required to read the statements")

# Measured from the real Union table: SI | Date | Particulars | Withdrawal |
# Deposit | Balance, as fractions of the 595pt page width.
UNION_EDGES = [30 / 595, 46 / 595, 101 / 595, 371 / 595, 421 / 595, 501 / 595, 580 / 595]
UNION_ROLES = ["serial", "date", "description", "debit", "credit", "balance"]
UNION_REGION = {"y0": 0.28, "y1": 0.82}


def _calibrated_extractor(name="TESTBANK", **overrides):
    from extractor import StandalonePDFExtractor

    ex = StandalonePDFExtractor()
    template = {
        "vertical_lines_norm": UNION_EDGES,
        "table_region_norm": UNION_REGION,
        "column_positions": {
            "expected_cols": len(UNION_ROLES),
            "mapping": {str(i): r for i, r in enumerate(UNION_ROLES) if r != "serial"},
        },
        "date_format": "%d-%m-%Y",
        "columns": {},
        "calibrated": True,
    }
    template.update(overrides)
    ex.templates[name] = template
    return ex


def _union():
    path = REAL_DATA / "UNION.pdf"
    if not path.exists():
        pytest.skip("UNION.pdf not present in Real_Data/")
    return path


def test_calibrated_template_extracts_rows():
    ex = _calibrated_extractor()
    df = ex.extract_with_template(_union(), "TESTBANK")
    assert len(df) == 6, "a calibrated template must parse the same rows as the built-in one"
    assert df.attrs["extraction_diagnostics"]["template_fallback"] is False


def test_calibrated_extraction_verifies_against_the_statement():
    """The whole point: the numbers must match what the bank printed."""
    from src.utils import extraction_fidelity as ef
    from src.utils.anchors import extract_anchors
    from src.utils.validation import validate_and_clean

    ex = _calibrated_extractor()
    raw = ex.extract_with_template(_union(), "TESTBANK")
    df, stats = validate_and_clean(raw.rename(columns={
        "Date": "date", "Description": "description", "Withdrawal Amt.": "debit",
        "Deposit Amt.": "credit", "Closing Balance": "balance"}), "Other")

    result = ef.check(df, extract_anchors(_union()),
                      {**stats, **raw.attrs["extraction_diagnostics"]})
    failed = [c["check"] for c in result["checks"] if not c["passed"]]
    assert result["status"] == "VERIFIED", f"failed: {failed}"

    assert abs(df["debit"].sum() - 0.30) < 0.01
    assert abs(df["credit"].sum() - 61659.50) < 0.01
    assert abs(df["balance"].iloc[-1] - 64026.54) < 0.01


def test_boundaries_are_authoritative_not_advisory():
    """
    find_tables(vertical_strategy="explicit") intersects supplied lines with a
    table bbox it infers itself, and drops any boundary outside it -- on this
    statement that turned 7 boundaries into 5 columns and lost the balance
    column. A calibration must not be silently overruled.
    """
    import fitz

    from extractor import _extract_page_table_by_geometry

    page = fitz.open(_union())[0]
    lines = [e * page.rect.width for e in UNION_EDGES]
    grid = _extract_page_table_by_geometry(page, lines, UNION_REGION)

    assert grid, "geometry extraction produced no table"
    assert len(grid[0][0]) == len(UNION_EDGES) - 1 == 6


@pytest.fixture
def anonymised_union(tmp_path):
    """A UUID-named copy, as the web app stores every upload.

    Detection checks the filename first, and `UNION.pdf` answers "Union" before
    any content is read -- which would make these tests pass for the wrong
    reason and hide a broken registry lookup.
    """
    import shutil
    import uuid

    target = tmp_path / f"{uuid.uuid4()}.pdf"
    shutil.copy(_union(), target)
    return target


def test_calibrated_bank_is_auto_detectable_by_ifsc_prefix(anonymised_union):
    """
    Without this a calibrated template is unreachable: detection only knew the
    eight hardcoded bank names, so the operator had to type the name exactly.
    """
    ex = _calibrated_extractor("Testbank Ltd", ifsc_prefix="UBIN")
    assert ex.detect_bank(anonymised_union) == "Testbank Ltd"


def test_calibrated_bank_is_auto_detectable_by_text_marker(tmp_path):
    """
    Uses ICICI rather than Union: Union's page 1 prints no bank name anywhere
    (it is detected purely by its IFSC), so there is no marker to match. ICICI
    prints "ICICI BANK LIMITED" in its branch block.
    """
    import shutil
    import uuid

    source = REAL_DATA / "ICICI.pdf"
    if not source.exists():
        pytest.skip("ICICI.pdf not present in Real_Data/")
    target = tmp_path / f"{uuid.uuid4()}.pdf"
    shutil.copy(source, target)

    ex = _calibrated_extractor("Testbank Ltd", detect_markers=["icici bank limited"])
    ex.templates["Testbank Ltd"].pop("ifsc_prefix", None)
    assert ex.detect_bank(target) == "Testbank Ltd"


def test_saving_a_template_does_not_destroy_an_existing_one():
    """
    `save_bank_template` used to assign a freshly built dict over the entry,
    wiping a hand-written column mapping to nulls. Website/backend/templates/
    banks.json still carries the damage for ICICI, Axis and PNB.
    """
    import json
    import shutil
    import tempfile

    sys.path.insert(0, str(REPO_ROOT / "Website" / "backend"))
    import services.template_service as ts

    original = ts.TEMPLATE_PATH
    tmp = Path(tempfile.mkdtemp()) / "banks.json"
    shutil.copy(original, tmp)
    try:
        ts.TEMPLATE_PATH = tmp
        service = ts.TemplateService()
        before = service.get_bank_config("ICICI")
        assert before.get("columns"), "fixture: ICICI should start with a column mapping"

        service.save_bank_template("ICICI", vertical_lines_norm=[0.1, 0.5, 0.9],
                                   column_roles=["date", "description"])

        after = json.loads(tmp.read_text(encoding="utf-8"))["ICICI"]
        assert after["columns"] == before["columns"], "existing column mapping was destroyed"
        assert after["vertical_lines_norm"] == [0.1, 0.5, 0.9]
    finally:
        ts.TEMPLATE_PATH = original
