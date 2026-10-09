import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'Feature Extraction')
from pathlib import Path
from extractor import StandalonePDFExtractor

path = Path('Real_Data/BOB.pdf')
raw = StandalonePDFExtractor().extract_with_template(path, 'BOB')
for i in range(len(raw)):
    r = raw.iloc[i]
    print(f"{i:2d} | {r['Date']} | {r['Description'][:35]} | Dr={r['Withdrawal Amt.']} | Cr={r['Deposit Amt.']} | Bal={r['Closing Balance']}")
