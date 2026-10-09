import sys
sys.path.insert(0, 'Feature Extraction')
from pathlib import Path
import re
import fitz
from src.utils.anchors import _page_rows, _row_text, _values_in_row, StatementAnchors, _collect_labelled

# Updated regex
_LABELS = {
    "opening_balance": re.compile(r"^(opening\s*bal(ance)?|balance\s*b/?f|brought\s*forward|b/?f)$", re.I),
    "closing_balance": re.compile(r"^(closing\s*bal(ance)?|balance\s*c/?f|carried\s*forward)$", re.I),
    "total_debits": re.compile(r"^(total\s*debits?|total\s*withdrawals?|debit\s*total|debits?)$", re.I),
    "total_credits": re.compile(r"^(total\s*credits?|total\s*deposits?|credit\s*total|credits?)$", re.I),
    "debit_count": re.compile(r"^(dr\s*count|debit\s*count|no\.?\s*of\s*debits?)$", re.I),
    "credit_count": re.compile(r"^(cr\s*count|credit\s*count|no\.?\s*of\s*credits?)$", re.I),
}

_TXN_HEADER_WORDS = re.compile(r"\b(narration|particulars|chq|value\s*dt|txn\s*date|withdrawal\s*amt|deposit\s*amt)\b", re.I)

def custom_label_spans(words):
    txt = _row_text(words)
    # If this row is a transaction table header, skip
    if _TXN_HEADER_WORDS.search(txt):
        return []
    found = []
    seen = set()
    n = len(words)
    for i in range(n):
        if not any(ch.isalnum() for ch in words[i][4]):
            continue
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

# Let's test on the HDFC PDF
doc = fitz.open('Website/backend/uploads/82fc056a-1b95-4f91-8657-42780d50a8d9.pdf')
anchors = StatementAnchors()
for pno, page in enumerate(doc):
    rows = _page_rows(page)
    for idx, (y, words) in enumerate(rows):
        labels = [lab for lab in custom_label_spans(words) if getattr(anchors, lab[0]) is None]
        for name, lx0, lx1, after in labels:
            if getattr(anchors, name) is not None:
                continue
            if len(labels) == 1:
                same_row = _values_in_row(words, after)
                if same_row:
                    setattr(anchors, name, same_row[0][0])
                    anchors.sources[name] = f"p{pno} same-row: {_row_text(words)[:90]}"
                    continue
            best = None
            for look in range(1, 5):
                if idx + look >= len(rows):
                    break
                _below_y, below_words = rows[idx + look]
                for v, vx0, vx1 in _values_in_row(below_words):
                    overlap = min(lx1, vx1) - max(lx0, vx0)
                    if overlap > 0:
                        score = (2, overlap)
                    else:
                        score = (1, -abs((lx0 + lx1) / 2 - (vx0 + vx1) / 2))
                    if best is None or score > best[0]:
                        best = (score, v, f"p{pno} column: '{_row_text(words)[:50]}' -> '{_row_text(below_words)[:50]}'")
                if best is not None:
                    break
            if best is not None:
                setattr(anchors, name, best[1])
                anchors.sources[name] = best[2]

print('Parsed anchors:')
for k, v in vars(anchors).items():
    print(f'  {k}: {v}')
