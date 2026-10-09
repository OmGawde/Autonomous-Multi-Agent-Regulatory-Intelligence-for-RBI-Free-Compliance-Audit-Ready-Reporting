# Standalone Bank Statement PDF Extractor

A robust, standalone Python utility to extract tabular transaction data from PDF bank statements. This uses the exact same parsing engine, template matching configurations, stable sorting, and cheque number extraction developed for the main loan approval pipeline.

## Features
- **Auto-Detection**: Scans filenames and first-page PDF text to auto-identify supported banks (`HDFC`, `SBI`, `ICICI`, `Axis`, `Kotak`, `Bank Of India`).
- **Precision Extraction**: Uses explicit coordinate horizontal-line slicing for tricky borderless layouts (e.g. `ICICI`).
- **Multi-Row Header Search**: Discards page-top junk rows and correctly locates start of transaction lists automatically.
- **Cheque Number Matching**: Automatically extracts Cheque Numbers (e.g. for CLG clearing transactions) and appends them cleanly to transaction descriptions (` - Cheque No: XXXX`).
- **Multiple Output Formats**: Generates `.csv`, `.xlsx` (Excel), `.json`, and a cleanly formatted `.txt` table view in the output folder.

---

## Getting Started

### 1. Setup Environment
Open your terminal/command prompt, navigate to this directory, and create a virtual environment:

```bash
# Navigate to the pdf_extractor folder
cd "e:\Main Projects\Loan_Approval\pdf_extractor"

# Create a virtual environment
python -m venv venv

# Activate virtual environment (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Or Windows Command Prompt (CMD)
# .\venv\Scripts\activate.bat
```

### 2. Install Dependencies
Install all required libraries inside the virtual environment:

```bash
pip install -r requirements.txt
```

### 3. Place Input Statements
Put all your bank statement PDF files (e.g. `account_statement.pdf`) into the `uploads/` folder.
*(If the folder doesn't exist, it will be automatically created the first time you run the script).*

### 4. Run the Extractor
Execute the Python script:

```bash
python extractor.py
```

### 5. Access Structured Outputs
Check the `output/` directory for your parsed statements. For every input PDF file `X.pdf`, four files will be generated:
- `X_extracted.csv`: Clean CSV file containing columns `date`, `description`, `debit`, `credit`, `balance`.
- `X_extracted.xlsx`: Production-ready Excel spreadsheet containing all transactions.
- `X_extracted.json`: JSON payload containing all transaction records.
- `X_table.txt`: Clean, human-readable ASCII table representation.

---

## Templates Reference
Column names and format patterns are managed inside `templates/banks.json`. You can easily add, remove, or modify bank definitions by editing that file.
