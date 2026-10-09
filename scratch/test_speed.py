import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from extractor import StandalonePDFExtractor

def benchmark():
    extractor = StandalonePDFExtractor()
    uploads = list(extractor.uploads_dir.glob("*.pdf"))
    
    print("=" * 95)
    print("      PyMuPDF STATEMENT EXTRACTION BENCHMARK RESULTS (5-COLUMN SCHEMA)")
    print("=" * 95)
    print(f"{'Filename':<22} | {'Bank':<12} | {'Pages':<6} | {'Transactions':<12} | {'Extract Time':<12}")
    print("-" * 95)
    
    for pdf_path in sorted(uploads):
        bank_name = extractor.detect_bank(pdf_path)
        t0 = time.time()
        df = extractor.extract_with_template(pdf_path, bank_name)
        dt = time.time() - t0
        
        doc_len = 0
        try:
            import fitz
            doc = fitz.open(pdf_path)
            doc_len = len(doc)
            doc.close()
        except:
            pass
            
        print(f"{pdf_path.name:<22} | {bank_name:<12} | {doc_len:<6} | {len(df):<12} | {dt:.3f}s")
        expected_cols = ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
        assert list(df.columns) == expected_cols, f"Mismatch columns: {list(df.columns)}"

    print("-" * 95)
    print("Schema Validation: 100% PASS on all output columns:")
    print("  ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']")
    print("=" * 95)

if __name__ == '__main__':
    benchmark()
