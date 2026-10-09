import sys
import glob
from pathlib import Path

def run_verification():
    sys.path.insert(0, '.')
    from extractor import StandalonePDFExtractor
    ext = StandalonePDFExtractor()

    files = sorted(glob.glob("New_Data/**/*.pdf", recursive=True))
    results = []

    print(f"Total PDFs to test: {len(files)}\n")

    for f in files:
        fp = Path(f)
        try:
            detected = ext.detect_bank(fp)
            df = ext.extract_with_template(fp, detected)
            num_rows = len(df)
            
            # Additional sanity checks
            dates_valid = df['Date'].notna().all() if num_rows > 0 and 'Date' in df.columns else False
            has_amounts = (df['Withdrawal Amt.'].abs().sum() + df['Deposit Amt.'].abs().sum() > 0) if num_rows > 0 else False
            
            status = "OK" if num_rows > 0 else ("SCANNED_IMAGE" if "PNB_BANK_2" in f else "ZERO_ROWS")
            results.append((f, detected, num_rows, dates_valid, has_amounts, status))
        except Exception as e:
            results.append((f, "ERROR", 0, False, False, str(e)[:40]))

    print("=" * 105)
    print(f"{'FILE':<38} | {'BANK DETECTED':<22} | {'ROWS':<6} | {'VALID DATES':<11} | {'AMOUNTS':<8} | {'STATUS'}")
    print("=" * 105)
    for f, b, r, dv, ha, s in results:
        print(f"{f:<38} | {b:<22} | {r:<6} | {str(dv):<11} | {str(ha):<8} | {s}")
    print("=" * 105)

if __name__ == '__main__':
    run_verification()
