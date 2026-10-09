import sys
from pathlib import Path
import fitz
import re
import pandas as pd

from extractor import StandalonePDFExtractor

ext = StandalonePDFExtractor()

files = [
    "New_Data/BOM_BANK.pdf",
    "New_Data/FEDERAL_BANK.pdf",
    "New_Data/INDIAN_OVERSEAS_BANK.pdf",
    "New_Data/INDUSIND_BANK.pdf",
    "New_Data/ICICI_BANK_wrong.pdf",
    "New_Data/AXIS_BANK/AXIS_BANK.pdf",
    "New_Data/AXIS_BANK/AXIS_BANK_2.pdf",
    "New_Data/AXIS_BANK/AXIS_BANK_3.pdf",
    "New_Data/CANARA_BANK/CANARA_BANK.pdf",
    "New_Data/CANARA_BANK/CANARA_BANK_2.pdf",
    "New_Data/CANARA_BANK/CANARA_BANK_3.pdf",
    "New_Data/IDBI_BANK/IDBI_BANK.pdf",
    "New_Data/IDBI_BANK/IDBI_BANK_2.pdf",
    "New_Data/IDBI_BANK/IDBI_BANK_3.pdf",
    "New_Data/KOTAK_BANK/KOTAK_BANK.pdf",
    "New_Data/KOTAK_BANK/KOTAK_BANK_2.pdf",
    "New_Data/KOTAK_BANK/KOTAK_BANK_3.pdf",
    "New_Data/YES_BANK/YES_BANK.pdf",
    "New_Data/YES_BANK/YES_BANK_2.pdf",
]

for fp in files:
    p = Path(fp)
    det = ext.detect_bank(p)
    doc = fitz.open(p)
    # Search for transaction headers across pages 0 and 1
    found_table = False
    for pno in range(min(3, len(doc))):
        page = doc[pno]
        tabs = page.find_tables()
        if tabs and tabs.tables:
            for t in tabs.tables:
                hdr = [str(c).replace('\n', ' ') for c in (t.header.names if t.header else [])]
                text_peek = " | ".join(hdr[:8])
                if any(w in text_peek.lower() for w in ['date', 'debit', 'deposit', 'withdrawal', 'particular', 'narration', 'balance']):
                    print(f"[{fp}] Detected: {det} | p{pno} Table ({t.row_count} rows, {len(hdr)} cols): {hdr[:8]}")
                    found_table = True
                    break
        if found_table:
            break
    if not found_table:
        print(f"[{fp}] Detected: {det} | NO standard table found in first 3 pages")
    doc.close()
