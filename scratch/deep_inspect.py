import sys
import fitz
import re
from pathlib import Path

def inspect_all():
    targets = [
        "New_Data/BOM_BANK.pdf",
        "New_Data/FEDERAL_BANK.pdf",
        "New_Data/INDIAN_OVERSEAS_BANK.pdf",
        "New_Data/INDUSIND_BANK.pdf",
        "New_Data/ICICI_BANK_wrong.pdf",
        "New_Data/IDBI_BANK/IDBI_BANK.pdf",
        "New_Data/IDBI_BANK/IDBI_BANK_2.pdf",
        "New_Data/IDBI_BANK/IDBI_BANK_3.pdf",
        "New_Data/YES_BANK/YES_BANK.pdf",
        "New_Data/YES_BANK/YES_BANK_2.pdf",
        "New_Data/KOTAK_BANK/KOTAK_BANK.pdf",
        "New_Data/KOTAK_BANK/KOTAK_BANK_2.pdf",
        "New_Data/KOTAK_BANK/KOTAK_BANK_3.pdf",
        "New_Data/HDFC_BANK/HDFC_BANK.pdf",
        "New_Data/HDFC_BANK/HDFC_BANK_2.pdf",
        "New_Data/HDFC_BANK/HDFC_BANK_3.pdf",
        "New_Data/HDFC_BANK/HDFC_BANK_4.pdf",
        "New_Data/HDFC_BANK/HDFC_BANK_5.pdf",
        "New_Data/PNB_BANK/PNB_BANK.pdf",
        "New_Data/PNB_BANK/PNB_BANK_2.pdf",
        "New_Data/PNB_BANK/PNB_BANK_3.pdf",
        "New_Data/PNB_BANK/PNB_BANK_4.pdf",
        "New_Data/PNB_BANK/PNB_BANK_5.pdf",
        "New_Data/CANARA_BANK/CANARA_BANK.pdf",
        "New_Data/CANARA_BANK/CANARA_BANK_2.pdf",
        "New_Data/CANARA_BANK/CANARA_BANK_3.pdf",
        "New_Data/AXIS_BANK/AXIS_BANK.pdf",
        "New_Data/AXIS_BANK/AXIS_BANK_2.pdf",
        "New_Data/AXIS_BANK/AXIS_BANK_3.pdf"
    ]
    
    with open("scratch/deep_inspect.txt", "w", encoding="utf-8") as out:
        for filepath in targets:
            out.write("=" * 70 + "\n")
            out.write(f"FILE: {filepath}\n")
            doc = fitz.open(filepath)
            out.write(f"Total pages: {len(doc)}\n")
            if len(doc) == 0:
                out.write("EMPTY DOC\n")
                doc.close()
                continue
            p0_text = doc[0].get_text()
            out.write("--- Page 0 text preview ---\n")
            lines = [l.strip() for l in p0_text.splitlines() if l.strip()]
            for l in lines[:25]:
                out.write(f"  {l}\n")
            
            # IFSC
            ifscs = re.findall(r'[A-Za-z]{4}0[A-Za-z0-9]{6}', p0_text)
            out.write(f"All IFSCs on p0: {ifscs}\n")
            
            # Check for tables across pages
            for pno in range(min(3, len(doc))):
                page = doc[pno]
                tabs = page.find_tables()
                if tabs and tabs.tables:
                    for tidx, t in enumerate(tabs.tables):
                        grid = t.extract()
                        header = grid[0] if grid else []
                        out.write(f"  P{pno} Table {tidx}: {len(grid)} rows x {len(header)} cols | Header: {header[:8]}\n")
                        if len(grid) > 1:
                            out.write(f"    Row 1: {grid[1][:8]}\n")
                        if len(grid) > 2:
                            out.write(f"    Row 2: {grid[2][:8]}\n")
                else:
                    out.write(f"  P{pno}: No fitz tables\n")
            doc.close()
    print("Done writing scratch/deep_inspect.txt")

if __name__ == "__main__":
    inspect_all()
