import sys
sys.path.insert(0, '.')
import fitz
import re
import pandas as pd
from pathlib import Path

def test_single_pdf(file_path_str):
    doc = fitz.open(file_path_str)
    all_tables = []
    for page in doc:
        tabs = page.find_tables()
        grids = []
        if tabs and tabs.tables:
            for t in tabs.tables:
                g = t.extract()
                if g and len(g) > 1:
                    grids.append(g)
        
        # Check degenerate
        is_degenerate = False
        if not grids:
            is_degenerate = True
        else:
            for g in grids:
                for r in g[1:min(5, len(g))]:
                    if any(isinstance(c, str) and c.count('\n') >= 3 for c in r if c):
                        is_degenerate = True
                        break
                if is_degenerate:
                    break
        
        if is_degenerate:
            tabs_ht = page.find_tables(horizontal_strategy="text")
            g_ht = [t.extract() for t in tabs_ht.tables if t.extract() and len(t.extract()) > 2]
            if g_ht and max(len(g) for g in g_ht) > (max(len(g) for g in grids) if grids else 0):
                grids = g_ht
            else:
                tabs_vh = page.find_tables(vertical_strategy="text", horizontal_strategy="text")
                g_vh = [t.extract() for t in tabs_vh.tables if t.extract() and len(t.extract()) > 2]
                if g_vh and max(len(g) for g in g_vh) > (max(len(g) for g in grids) if grids else 0):
                    grids = g_vh
                    
        for g in grids:
            all_tables.append(g)
    doc.close()
    return len(all_tables), sum(len(g) for g in all_tables)

targets = [
    "New_Data/HDFC_BANK/HDFC_BANK.pdf",
    "New_Data/HDFC_BANK/HDFC_BANK_2.pdf",
    "New_Data/IDBI_BANK/IDBI_BANK.pdf",
    "New_Data/IDBI_BANK/IDBI_BANK_3.pdf",
    "New_Data/KOTAK_BANK/KOTAK_BANK.pdf",
    "New_Data/KOTAK_BANK/KOTAK_BANK_2.pdf",
    "New_Data/KOTAK_BANK/KOTAK_BANK_3.pdf",
    "New_Data/ICICI_BANK_wrong.pdf"
]

for t in targets:
    t_cnt, r_cnt = test_single_pdf(t)
    print(f"{t:<40} | Tables: {t_cnt} | Total Raw Rows: {r_cnt}")
