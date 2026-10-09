import fitz
import pdfplumber

def test_hdfc():
    doc = fitz.open("New_Data/HDFC_BANK/HDFC_BANK.pdf")
    page = doc[0]
    
    # default
    tabs_def = page.find_tables()
    for t in tabs_def:
        g = t.extract()
        print(f"fitz default: {len(g)} rows")
        
    # horizontal text
    tabs_text = page.find_tables(horizontal_strategy="text")
    for t in tabs_text:
        g = t.extract()
        print(f"fitz horizontal_strategy='text': {len(g)} rows")
        if len(g) > 2:
            print("  Row 0:", g[0])
            print("  Row 1:", g[1])
            print("  Row 2:", g[2])

    doc.close()
    
    # test pdfplumber
    with pdfplumber.open("New_Data/HDFC_BANK/HDFC_BANK.pdf") as pl:
        p0 = pl.pages[0]
        tabs = p0.extract_tables()
        print(f"pdfplumber default: {len(tabs)} tables")
        for t in tabs:
            print(f"  plumber rows: {len(t)}")
            if len(t) > 2:
                print("    R0:", t[0])
                print("    R1:", t[1])
                print("    R2:", t[2])

if __name__ == "__main__":
    test_hdfc()
