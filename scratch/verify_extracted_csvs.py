import os
import glob
import pandas as pd
import fitz

def verify_all_csvs():
    output_dir = "output"
    csv_files = sorted(glob.glob(os.path.join(output_dir, "*_extracted.csv")))
    
    print("=" * 100)
    print("                 BANK STATEMENT EXTRACTED CSV QUALITY & ACCURACY AUDIT")
    print("=" * 100)
    
    target_cols = ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
    
    summary = []
    
    for csv_file in csv_files:
        filename = os.path.basename(csv_file)
        pdf_name = filename.replace("_extracted.csv", ".pdf")
        pdf_path = os.path.join("uploads", pdf_name)
        
        print(f"\nAUDITING FILE: {filename}")
        print("-" * 80)
        
        # 1. Load CSV
        df = pd.read_csv(csv_file)
        
        # 2. Check Schema
        cols_ok = list(df.columns) == target_cols
        print(f"  [1] Schema Match: {'PASS' if cols_ok else 'FAIL'}")
        if not cols_ok:
            print(f"      Got: {list(df.columns)}")
            print(f"      Exp: {target_cols}")
            
        # 3. Transaction Count
        row_count = len(df)
        print(f"  [2] Total Transactions Extracted: {row_count:,}")
        
        # 4. Check Nulls/Empty Values
        null_dates = df['Date'].isna().sum()
        df['Desc_Str'] = df['Description'].fillna("").astype(str).str.strip()
        empty_descs = (df['Desc_Str'] == "").sum()
        print(f"  [3] Data Integrity Check:")
        print(f"      - Null / Unparseable Dates: {null_dates}")
        print(f"      - Empty / Missing Descriptions: {empty_descs}")
        
        # 5. Check Amounts
        df['Withdrawal Amt.'] = pd.to_numeric(df['Withdrawal Amt.'], errors='coerce').fillna(0.0)
        df['Deposit Amt.'] = pd.to_numeric(df['Deposit Amt.'], errors='coerce').fillna(0.0)
        df['Closing Balance'] = pd.to_numeric(df['Closing Balance'], errors='coerce').fillna(0.0)
        
        total_wdr = df['Withdrawal Amt.'].sum()
        total_dep = df['Deposit Amt.'].sum()
        print(f"      - Total Withdrawals: INR {total_wdr:,.2f}")
        print(f"      - Total Deposits:    INR {total_dep:,.2f}")
        print(f"      - Min Closing Bal:   INR {df['Closing Balance'].min():,.2f}")
        print(f"      - Max Closing Bal:   INR {df['Closing Balance'].max():,.2f}")
        
        # 6. Sample Data Verification (First 3 & Last 3 rows)
        print(f"\n  [4] Sample Extracted Rows (First 3):")
        for i, row in df.head(3).iterrows():
            print(f"      Row {i+1}: Date={row['Date']} | Desc={str(row['Desc_Str'])[:50]:<50} | Wdr={row['Withdrawal Amt.']} | Dep={row['Deposit Amt.']} | Bal={row['Closing Balance']}")
            
        print(f"\n  [5] Sample Extracted Rows (Last 3):")
        for i, row in df.tail(3).iterrows():
            print(f"      Row {i+1}: Date={row['Date']} | Desc={str(row['Desc_Str'])[:50]:<50} | Wdr={row['Withdrawal Amt.']} | Dep={row['Deposit Amt.']} | Bal={row['Closing Balance']}")
            
        # 7. Check PDF page count alignment
        pdf_pages = 0
        if os.path.exists(pdf_path):
            doc = fitz.open(pdf_path)
            pdf_pages = len(doc)
            doc.close()
            avg_txns_per_page = row_count / max(pdf_pages - 1, 1)
            print(f"\n  [6] PDF Alignment: {pdf_pages} pages in PDF -> ~{avg_txns_per_page:.1f} txns/page")
        
        summary.append({
            'filename': filename,
            'pdf_pages': pdf_pages,
            'txns': row_count,
            'null_dates': null_dates,
            'empty_descs': empty_descs,
            'wdr_total': total_wdr,
            'dep_total': total_dep
        })
        print("=" * 100)

    print("\n" + "=" * 100)
    print("                              AUDIT SUMMARY OVERVIEW")
    print("=" * 100)
    print(f"{'Filename':<30} | {'PDF Pages':<10} | {'Extracted Txns':<15} | {'Empty Descs':<12} | {'Status':<10}")
    print("-" * 100)
    for s in summary:
        status = "PERFECT" if s['null_dates'] == 0 and s['empty_descs'] == 0 else "CHECK"
        print(f"{s['filename']:<30} | {s['pdf_pages']:<10} | {s['txns']:<15,} | {s['empty_descs']:<12} | {status:<10}")
    print("=" * 100)

if __name__ == '__main__':
    verify_all_csvs()
