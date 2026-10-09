import sys
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from extractor import StandalonePDFExtractor


def test_multi_statement_deduplication_and_sorting(monkeypatch):
    extractor = StandalonePDFExtractor()

    # Statement 1 (Jan - Feb)
    df1 = pd.DataFrame([
        {"Date": "2025-01-10", "Description": "SALARY CREDIT", "Withdrawal Amt.": 0.0, "Deposit Amt.": 50000.0, "Closing Balance": 55000.0},
        {"Date": "2025-02-05", "Description": "RENT DEBIT", "Withdrawal Amt.": 15000.0, "Deposit Amt.": 0.0, "Closing Balance": 40000.0},
    ])
    df1.attrs["extraction_diagnostics"] = {"rows_extracted": 2}

    # Statement 2 (Feb - Mar, with overlapping Feb rent transaction)
    df2 = pd.DataFrame([
        {"Date": "2025-02-05", "Description": "RENT DEBIT", "Withdrawal Amt.": 15000.0, "Deposit Amt.": 0.0, "Closing Balance": 40000.0},
        {"Date": "2025-03-10", "Description": "SALARY CREDIT", "Withdrawal Amt.": 0.0, "Deposit Amt.": 50000.0, "Closing Balance": 90000.0},
    ])
    df2.attrs["extraction_diagnostics"] = {"rows_extracted": 2}

    calls = []
    def mock_extract(path, bank_name=None, password=None):
        calls.append(path)
        if "stmt1" in str(path):
            return df1
        return df2

    monkeypatch.setattr(extractor, "extract_with_template", mock_extract)
    monkeypatch.setattr(extractor, "detect_bank", lambda p, pw: "HDFC")
    monkeypatch.setattr(extractor, "extract_account_holder", lambda p, pw: {"account_number": "1234567890"})

    merged = extractor.extract_multiple_statements(["stmt1.pdf", "stmt2.pdf"], "HDFC")

    # 4 rows minus 1 duplicate = 3 rows
    assert len(merged) == 3
    assert merged.iloc[0]["Date"] == "2025-01-10"
    assert merged.iloc[1]["Date"] == "2025-02-05"
    assert merged.iloc[2]["Date"] == "2025-03-10"
    assert merged.attrs["extraction_diagnostics"]["deduplicated_overlapping_rows"] == 1
    assert merged.attrs["extraction_diagnostics"]["merged_files_count"] == 2
