"""
Password-protected statements.

Indian bank e-statements are routinely encrypted. Before this work an encrypted
upload returned HTTP 200 "pending", failed silently seconds later, and told the
user "No transactions extracted using 'Auto-Detect' template" -- sending them to
fix an imagined template problem. The word "password" never reached them.

The trap these tests guard: `fitz.open()` does NOT raise on an encrypted file.
It returns a Document whose page count reads fine, and only the first *page
access* fails, several frames away, as a bare ValueError. Any guard wrapped
around the open call misses it entirely.
"""

import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = REPO_ROOT / "Real_Data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

fitz = pytest.importorskip("fitz", reason="PyMuPDF is required")

USER_PW = "secret123"
OWNER_PW = "owner123"


@pytest.fixture(scope="module")
def locked_axis(tmp_path_factory):
    """A genuinely encrypted copy of the real Axis statement, UUID-named.

    UUID-named on purpose: the web app renames every upload, so the filename
    shortcut in detect_bank must not be what answers here.
    """
    source = REAL_DATA / "AXIS.pdf"
    if not source.exists():
        pytest.skip("AXIS.pdf not present in Real_Data/")
    target = tmp_path_factory.mktemp("locked") / f"{uuid.uuid4()}.pdf"
    doc = fitz.open(source)
    doc.save(str(target), encryption=fitz.PDF_ENCRYPT_AES_256,
             user_pw=USER_PW, owner_pw=OWNER_PW)
    doc.close()
    return target


def test_fitz_open_does_not_raise_on_an_encrypted_file(locked_axis):
    """Pins the library behaviour the whole design rests on."""
    doc = fitz.open(locked_axis)
    assert doc.needs_pass, "expected an encrypted fixture"
    assert len(doc) > 0, "page count is readable while locked -- this is the trap"
    with pytest.raises(Exception):
        _ = doc[0].get_text()
    doc.close()


def test_authenticate_return_value_is_the_success_test(locked_axis):
    """`needs_pass` stays truthy after a successful authenticate; the return value doesn't."""
    doc = fitz.open(locked_axis)
    assert doc.authenticate("wrong") == 0
    assert doc.authenticate(USER_PW) > 0
    assert doc.needs_pass, "needs_pass remains set even once unlocked"
    doc.close()


def test_probe_reports_locked_then_unlocked(locked_axis):
    from extractor import probe_pdf

    assert probe_pdf(locked_axis) == pytest.approx(
        probe_pdf(locked_axis), abs=0
    )  # deterministic

    locked = probe_pdf(locked_axis)
    assert locked["encrypted"] is True and locked["unlocked"] is False

    wrong = probe_pdf(locked_axis, "nope")
    assert wrong["encrypted"] is True and wrong["unlocked"] is False

    ok = probe_pdf(locked_axis, USER_PW)
    assert ok["encrypted"] is True and ok["unlocked"] is True
    assert ok["pages"] == 14 and ok["has_text_layer"] is True


def test_probe_reports_a_plain_pdf_as_readable():
    from extractor import probe_pdf

    source = REAL_DATA / "AXIS.pdf"
    if not source.exists():
        pytest.skip("AXIS.pdf not present in Real_Data/")
    p = probe_pdf(source)
    assert p["encrypted"] is False and p["unlocked"] is True
    assert p["has_text_layer"] is True


@pytest.mark.parametrize("password,supplied", [(None, False), ("wrong", True)])
def test_every_read_path_raises_a_typed_error(locked_axis, password, supplied):
    """
    detect_bank in particular must NOT degrade to "Other" -- reporting an
    encrypted file as an unrecognised bank sends the user to calibrate a
    template that was never the problem.
    """
    from extractor import StandalonePDFExtractor, PdfPasswordError

    ex = StandalonePDFExtractor()
    for call in (
        lambda: ex.detect_bank(locked_axis, password),
        lambda: ex.extract_account_holder(locked_axis, password),
        lambda: ex.extract_with_template(locked_axis, "Axis", password),
    ):
        with pytest.raises(PdfPasswordError) as exc:
            call()
        assert exc.value.password_supplied is supplied


def test_correct_password_yields_the_same_result_as_the_unlocked_file(locked_axis):
    from extractor import StandalonePDFExtractor

    ex = StandalonePDFExtractor()
    assert ex.detect_bank(locked_axis, USER_PW) == "Axis"
    assert ex.extract_account_holder(locked_axis, USER_PW)["account_holder"] == "MILIND SURESH WALANJU"

    unlocked_rows = len(ex.extract_with_template(REAL_DATA / "AXIS.pdf", "Axis"))
    locked_rows = len(ex.extract_with_template(locked_axis, "Axis", USER_PW))
    assert locked_rows == unlocked_rows == 422
