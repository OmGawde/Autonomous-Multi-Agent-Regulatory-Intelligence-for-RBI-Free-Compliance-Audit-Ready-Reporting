import sys
sys.path.insert(0, '.')
import glob
from pathlib import Path
from extractor import StandalonePDFExtractor

ext = StandalonePDFExtractor()

files = sorted(glob.glob("New_Data/**/*.pdf", recursive=True))

results = []

for f in files:
    fp = Path(f)
    try:
        bank = ext.detect_bank(fp)
        df = ext.extract_with_template(fp, bank)
        results.append((f, bank, len(df), "OK" if len(df) > 0 else "ZERO_ROWS"))
    except Exception as e:
        results.append((f, "ERROR", 0, str(e)))

print("\n" + "="*80)
print(f"{'FILE':<40} | {'DETECTED':<20} | {'ROWS':<6} | {'STATUS'}")
print("="*80)
for f, b, r, s in results:
    print(f"{f:<40} | {b:<20} | {r:<6} | {s}")
