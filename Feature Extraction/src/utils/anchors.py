"""
Read the facts a bank statement prints about itself.

A bank statement is a self-checking document. Independently of the transaction
rows, it prints an opening balance, a closing balance, totals, a transaction
count, a serial column, a period. Those numbers must agree with the rows we
parsed -- and because they are printed by the bank rather than derived by us,
they are an oracle that needs no labels. That is what makes it possible to
verify a stranger's statement without knowing what the right answer is.

Two things this module gets right that a naive implementation does not:

1. **It reads by coordinate, not reading order.** Bank of Baroda proves why.
   Flat `page.get_text()` on page 1 yields the opening balance as
   `4,27,661.57`; the words at y=471.3 say it is `4,27,662.57`. The flat read is
   off by one row and hands back a plausible wrong number -- the exact failure
   mode this whole layer exists to catch.

2. **It pairs labels to values by geometry.** Axis, Union and BOB print
   `LABEL  VALUE` on one row. SBI prints six labels across one row and their
   values in the row beneath, as a column table. Pairing by text adjacency gets
   SBI wrong; pairing by x-overlap gets both right.

Not every bank prints every anchor. ICICI prints no balances or totals at all --
its only completeness anchor is an unbroken `S No.` 1..358. Absent anchors are
reported as None and the verifier treats that as UNVERIFIED, never as a pass.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

logger = logging.getLogger("Anchors")

# Rows are grouped on a 3pt grid: tight enough to keep adjacent table rows
# apart, loose enough to hold a row whose cells sit a point or two off.
_ROW_GRID = 3.0

# A value is matched to a label when their x-spans overlap, or when the value
# starts within this many points of the label's span. Column values are often
# right-aligned under a left-aligned header.
_COLUMN_SLACK = 45.0

_AMOUNT = re.compile(r"^[\(\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+\.?\d*)\s*\)?\s*(cr|dr)?\.?$", re.I)

_LABELS = {
    "opening_balance": re.compile(r"^(opening\s*bal(ance)?|balance\s*b/?f|brought\s*forward|b/?f)$", re.I),
    "closing_balance": re.compile(r"^(closing\s*bal(ance)?|balance\s*c/?f|carried\s*forward)$", re.I),
    "total_debits": re.compile(r"^(total\s*debits?|total\s*withdrawals?|debit\s*total|debits)$", re.I),
    "total_credits": re.compile(r"^(total\s*credits?|total\s*deposits?|credit\s*total|credits)$", re.I),
    "debit_count": re.compile(r"^(dr\s*count|debit\s*count|no\.?\s*of\s*debits?)$", re.I),
    "credit_count": re.compile(r"^(cr\s*count|credit\s*count|no\.?\s*of\s*credits?)$", re.I),
}

_TXN_HEADER_MARKERS = re.compile(
    r"\b(narration|particulars|chq|value\s*dt|txn\s*date|withdrawal\s*amt|deposit\s*amt)\b",
    re.I,
)

# Axis prints one label over two amounts: debits then credits.
_PAIRED_TOTAL = re.compile(r"^transaction\s*total$", re.I)

_SERIAL_HEADER = re.compile(r"^(s\s*no\.?|sr\.?\s*no\.?|sl\.?\s*no\.?|si|serial)$", re.I)

_PERIOD_HINT = re.compile(
    r"for\s+the\s+period|statement\s+of\s+account\s+for|account\s+statement\s+from|"
    r"statement\s+from|statement\s+period|transaction\s+date",
    re.I,
)
_DATE_DMY = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b")
_DATE_LONG = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
_PAGE_OF = re.compile(r"\bpage\s*(?:no\.?\s*)?(\d+)\s*of\s*(\d+)\b|\b(\d+)\s+of\s+(\d+)\b", re.I)

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


@dataclass
class StatementAnchors:
    """What the statement says about itself. Every field may legitimately be None."""

    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    total_debits: Optional[float] = None
    total_credits: Optional[float] = None
    debit_count: Optional[int] = None
    credit_count: Optional[int] = None
    expected_row_count: Optional[int] = None
    serial_first: Optional[int] = None
    serial_last: Optional[int] = None
    serial_gaps: List[int] = field(default_factory=list)
    # Union and BOB number their "Opening Balance" line as serial 1, so the
    # serial run is one longer than the transaction count. Counted rather than
    # absorbed into a fuzzy tolerance, so the row check stays exact.
    serial_non_transaction_rows: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    pages_declared: Optional[int] = None
    pages_actual: Optional[int] = None
    # Which label produced which value, so a surprising number can be traced
    # back to the line it came from rather than argued about.
    sources: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def any_money_anchor(self) -> bool:
        return any(v is not None for v in (
            self.opening_balance, self.closing_balance,
            self.total_debits, self.total_credits))

    def any_count_anchor(self) -> bool:
        return self.expected_row_count is not None


def parse_amount(token: str) -> Optional[float]:
    """
    Parse an Indian-statement money token.

    Handles lakh grouping (4,27,662.57), a Cr/Dr suffix with or without a space,
    currency tokens, accounting parentheses, and the non-breaking space BOI puts
    between the rupee sign and the digits.
    """
    if token is None:
        return None
    text = str(token).replace("\xa0", " ").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    m = _AMOUNT.match(text)
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    if not digits or digits == ".":
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix == "dr" or negative or text.startswith("-"):
        value = -value
    return value


def _page_rows(page) -> List[Tuple[float, List[tuple]]]:
    """Words grouped into visual rows by y, each row ordered left to right."""
    rows: Dict[float, List[tuple]] = {}
    for w in page.get_text("words"):
        rows.setdefault(round(w[1] / _ROW_GRID) * _ROW_GRID, []).append(w)
    return [(y, sorted(rows[y], key=lambda w: w[0])) for y in sorted(rows)]


def _row_text(words: List[tuple]) -> str:
    return " ".join(w[4] for w in words)


def _label_spans(words: List[tuple]) -> List[Tuple[str, float, float, int]]:
    """
    Find anchor labels in a row, allowing multi-word labels.

    Returns (field_name, x0, x1, index_after_label) so a same-row value can be
    read to the right of the label and a column value matched by x-overlap.
    """
    if _TXN_HEADER_MARKERS.search(_row_text(words)):
        return []

    found = []
    seen = set()
    n = len(words)
    for i in range(n):
        # A label never starts on punctuation. Without this, Union's
        # "Summary : Closing Balance : 64,026.54 Cr" matches at both the colon
        # and the real start -- the row then looks like a multi-label column
        # header and the value is read from the row below instead of this one.
        if not any(ch.isalnum() for ch in words[i][4]):
            continue
        # Longest match first: "total debits" must beat a bare "total".
        for span in (3, 2, 1):
            if i + span > n:
                continue
            phrase = " ".join(w[4] for w in words[i:i + span]).strip(" :.-")
            for name, pattern in _LABELS.items():
                if pattern.match(phrase) and name not in seen:
                    found.append((name, words[i][0], words[i + span - 1][2], i + span))
                    seen.add(name)
                    break
            else:
                continue
            break
    return found


def _values_in_row(words: List[tuple], start_index: int = 0) -> List[Tuple[float, float, float]]:
    """Numeric tokens in a row as (value, x0, x1). Joins a trailing Cr/Dr word."""
    out = []
    i = start_index
    while i < len(words):
        token = words[i][4]
        nxt = words[i + 1][4] if i + 1 < len(words) else ""
        if nxt.lower().strip(".") in ("cr", "dr"):
            value = parse_amount(f"{token}{nxt}")
            if value is not None:
                out.append((value, words[i][0], words[i + 1][2]))
                i += 2
                continue
        value = parse_amount(token)
        if value is not None:
            out.append((value, words[i][0], words[i][2]))
        i += 1
    return out


def _overlaps(a0: float, a1: float, b0: float, b1: float, slack: float = _COLUMN_SLACK) -> bool:
    return not (b0 > a1 + slack or b1 < a0 - slack)


def _assign(anchors: StatementAnchors, name: str, value: float) -> None:
    """Counts are whole and unsigned; balances and totals keep their sign."""
    if name in ("debit_count", "credit_count"):
        setattr(anchors, name, int(abs(value)))
    else:
        setattr(anchors, name, value)


def _collect_labelled(rows: List[Tuple[float, List[tuple]]], anchors: StatementAnchors, page_no: int) -> None:
    """
    Match each anchor label to its value.

    Same row first (Axis: `OPENING BALANCE 29155.31`), then the rows below by
    x-overlap (SBI: six labels on one row, their values in the next). First
    match wins, so a summary block early in the document is not overwritten by a
    stray later mention.
    """
    for idx, (y, words) in enumerate(rows):
        labels = [lab for lab in _label_spans(words) if getattr(anchors, lab[0]) is None]

        for name, lx0, lx1, after in labels:
            if getattr(anchors, name) is not None:
                continue

            # Same row: `OPENING BALANCE 29155.31` (Axis, Union, BOB). Only when
            # this row carries a single label -- a row of several labels is a
            # column header, and any number on it belongs to a different column.
            if len(labels) == 1:
                if name in ("total_debits", "total_credits") and "total" not in _row_text(words).lower():
                    continue
                same_row = _values_in_row(words, after)
                if same_row:
                    _assign(anchors, name, same_row[0][0])
                    anchors.sources[name] = f"p{page_no} same-row: {_row_text(words)[:90]}"
                    continue

            # Column layout (SBI): six labels on one row, their values beneath.
            # Assign by *best* x-overlap, not the first overlap found -- with a
            # generous slack the leftmost value matches several labels and the
            # whole summary shifts by one column, silently swapping the opening
            # balance with a transaction count.
            best = None  # (score, value, description)
            for look in range(1, 5):
                if idx + look >= len(rows):
                    break
                _below_y, below_words = rows[idx + look]
                for v, vx0, vx1 in _values_in_row(below_words):
                    overlap = min(lx1, vx1) - max(lx0, vx0)
                    if overlap > 0:
                        score = (2, overlap)
                    elif _overlaps(lx0, lx1, vx0, vx1):
                        # No true overlap: fall back to proximity of centres.
                        score = (1, -abs((lx0 + lx1) / 2 - (vx0 + vx1) / 2))
                    else:
                        continue
                    if best is None or score > best[0]:
                        best = (score, v, (
                            f"p{page_no} column: '{_row_text(words)[:50]}' "
                            f"-> '{_row_text(below_words)[:50]}'"
                        ))
                if best is not None:
                    break

            if best is not None:
                _assign(anchors, name, best[1])
                anchors.sources[name] = best[2]

        # Axis: one label, two amounts -- debits then credits.
        for i, w in enumerate(words):
            phrase = " ".join(x[4] for x in words[i:i + 2])
            if _PAIRED_TOTAL.match(phrase.strip(" :.-")):
                vals = _values_in_row(words, i + 2)
                if len(vals) >= 2:
                    if anchors.total_debits is None:
                        anchors.total_debits = vals[0][0]
                        anchors.sources["total_debits"] = f"p{page_no} paired: {_row_text(words)[:90]}"
                    if anchors.total_credits is None:
                        anchors.total_credits = vals[1][0]
                        anchors.sources["total_credits"] = f"p{page_no} paired: {_row_text(words)[:90]}"
                break


def _collect_serial_run(doc, anchors: StatementAnchors) -> None:
    """
    Find a serial-number column and check it runs 1..N unbroken.

    Stronger than a printed total for detecting lost rows, because a gap
    localises the loss to a page. ICICI has no money anchors at all and 358
    serials; BOI has 137; BOB 44; Union 7.
    """
    header_span: Optional[Tuple[float, float]] = None
    for pno in range(len(doc)):
        for _y, words in _page_rows(doc[pno]):
            for i in range(len(words)):
                for span in (2, 1):
                    if i + span > len(words):
                        continue
                    phrase = " ".join(w[4] for w in words[i:i + span]).strip(" .:")
                    if _SERIAL_HEADER.match(phrase):
                        header_span = (words[i][0] - 6, words[i + span - 1][2] + 14)
                        break
                if header_span:
                    break
            if header_span:
                break
        if header_span:
            break

    if not header_span:
        return

    hx0, hx1 = header_span
    serials: List[int] = []
    non_transaction = 0
    balance_row = re.compile(r"opening\s*balance|closing\s*balance|brought\s*forward|carried\s*forward", re.I)
    for pno in range(len(doc)):
        for _y, words in _page_rows(doc[pno]):
            row_serials = [
                int(w[4].strip())
                for w in words
                if _overlaps(hx0, hx1, w[0], w[2], slack=0)
                and w[4].strip().isdigit() and len(w[4].strip()) <= 5
            ]
            if not row_serials:
                continue
            serials.extend(row_serials)
            # A numbered "Opening Balance" line occupies a serial but is not a
            # transaction, so it must not inflate the expected row count.
            if balance_row.search(_row_text(words)):
                non_transaction += len(row_serials)

    serials = sorted(set(serials))
    if len(serials) < 3 or serials[0] != 1:
        return

    anchors.serial_first = serials[0]
    anchors.serial_last = serials[-1]
    expected = set(range(serials[0], serials[-1] + 1))
    anchors.serial_gaps = sorted(expected - set(serials))
    anchors.serial_non_transaction_rows = non_transaction
    anchors.expected_row_count = serials[-1] - non_transaction
    anchors.sources["expected_row_count"] = (
        f"serial column {serials[0]}..{serials[-1]}"
        + (f" with {len(anchors.serial_gaps)} gap(s)" if anchors.serial_gaps else " unbroken")
        + (f", less {non_transaction} balance row(s)" if non_transaction else "")
    )


def _collect_period_and_pages(doc, anchors: StatementAnchors) -> None:
    for pno in range(min(3, len(doc))):
        text = doc[pno].get_text() or ""
        for line in text.split("\n"):
            if anchors.period_start is None and _PERIOD_HINT.search(line):
                dates = _extract_dates(line)
                if len(dates) >= 2:
                    anchors.period_start, anchors.period_end = dates[0], dates[1]
                    anchors.sources["period"] = f"p{pno}: {line.strip()[:90]}"
            if anchors.pages_declared is None:
                m = _PAGE_OF.search(line)
                if m:
                    total = m.group(2) or m.group(4)
                    if total and total.isdigit():
                        anchors.pages_declared = int(total)
                        anchors.sources["pages_declared"] = f"p{pno}: {line.strip()[:60]}"

    # BOI splits the period across two lines ("from: 01-04-2010" / "to: ...").
    if anchors.period_start is None:
        head = "\n".join((doc[p].get_text() or "") for p in range(min(2, len(doc))))
        frm = re.search(r"\bfrom\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", head, re.I)
        to = re.search(r"\bto\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", head, re.I)
        if frm and to:
            a, b = _extract_dates(frm.group(1)), _extract_dates(to.group(1))
            if a and b:
                anchors.period_start, anchors.period_end = a[0], b[0]
                anchors.sources["period"] = "from:/to: pair"

    anchors.pages_actual = len(doc)


def _extract_dates(text: str) -> List[str]:
    """ISO dates found in a line. Handles dd-mm-yyyy and 'April 1, 2025'."""
    out: List[str] = []
    for m in _DATE_LONG.finditer(text):
        month = _MONTHS.get(m.group(1).lower())
        if month:
            out.append(f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}")
    for m in _DATE_DMY.finditer(text):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            out.append(f"{year:04d}-{month:02d}-{day:02d}")
    return out


def extract_anchors(pdf_path, password: str = None) -> StatementAnchors:
    """Read every anchor this statement happens to print. Never raises."""
    anchors = StatementAnchors()
    try:
        from extractor import _open_fitz, _PDF_READ_LOCK
        with _PDF_READ_LOCK:
            doc = _open_fitz(str(pdf_path), password)
            try:
                for pno in range(len(doc)):
                    _collect_labelled(_page_rows(doc[pno]), anchors, pno)
                _collect_serial_run(doc, anchors)
                _collect_period_and_pages(doc, anchors)
            finally:
                doc.close()
    except Exception as e:
        # Verification is a safety net, not a gate on processing: failing to
        # read the anchors must never stop a statement from being analysed. It
        # just means the result comes back UNVERIFIED.
        logger.warning(f"Could not read statement anchors from {Path(str(pdf_path)).name}: {e}")

    # SBI prints Dr Count and Cr Count instead of a serial column.
    if anchors.expected_row_count is None and (
        anchors.debit_count is not None or anchors.credit_count is not None
    ):
        anchors.expected_row_count = (anchors.debit_count or 0) + (anchors.credit_count or 0)
        anchors.sources["expected_row_count"] = (
            f"Dr Count {anchors.debit_count} + Cr Count {anchors.credit_count}"
        )
    return anchors
