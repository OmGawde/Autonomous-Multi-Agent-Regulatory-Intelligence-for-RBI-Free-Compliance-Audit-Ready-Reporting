import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'Feature Extraction')
from pathlib import Path
from extractor import StandalonePDFExtractor
from src.utils.anchors import extract_anchors
from src.utils import extraction_fidelity as ef
from src.utils.validation import validate_and_clean

path = Path('Website/backend/uploads/82fc056a-1b95-4f91-8657-42780d50a8d9.pdf')
if not path.exists():
    print("HDFC file not found, skipping")
    sys.exit(0)

raw = StandalonePDFExtractor().extract_with_template(path, 'HDFC')
diag = raw.attrs.get('extraction_diagnostics', {})
RENAME = {"Date": "date", "Description": "description", "Withdrawal Amt.": "debit",
          "Deposit Amt.": "credit", "Closing Balance": "balance"}
df, stats = validate_and_clean(raw.rename(columns=RENAME), 'HDFC')
anchors = extract_anchors(path)
res = ef.check(df, anchors, {**stats, **diag})

print(f"Status: {res['status']}")
print(f"Failed count: {res['failed_count']}")
for c in res['checks']:
    status = "PASS" if c['passed'] else "FAIL"
    print(f"  {c['check']}: {status} (expected={c['expected']}, actual={c['actual']})")

print(f"\nAnchors found: {res['anchors_found']}")
print(f"Opening: {anchors.opening_balance}")
print(f"Closing: {anchors.closing_balance}")
print(f"Total Debits: {anchors.total_debits}")
print(f"Total Credits: {anchors.total_credits}")
print(f"Debit Count: {anchors.debit_count}")
print(f"Credit Count: {anchors.credit_count}")
