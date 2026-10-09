import os
import glob
import fitz
import re
from pathlib import Path

pdfs = sorted(glob.glob('New_Data/**/*.pdf', recursive=True))

for p in pdfs:
    doc = fitz.open(p)
    num_pages = len(doc)
    p0_text = doc[0].get_text() if num_pages > 0 else ""
    first_lines = [l.strip() for l in p0_text.splitlines() if l.strip()][:15]
    
    # Check ifsc
    ifscs = re.findall(r'[A-Za-z]{4}0[A-Za-z0-9]{6}', p0_text[:2000])
    
    # Check tables
    tabs = doc[0].find_tables()
    tab_info = ""
    if tabs and tabs.tables:
        t = tabs.tables[0]
        header = t.header.names if t.header else []
        tab_info = f"Table cols: {len(header)} Header: {header[:8]} Rows: {t.row_count}"
    else:
        tab_info = "No fitz table on p0"
        
    print(f"=== {p} ({num_pages} pages) ===")
    print(f"  IFSCs: {ifscs[:3]}")
    print(f"  Header lines: {first_lines[:4]}")
    print(f"  {tab_info}")
    doc.close()
