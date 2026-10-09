# Part 3: Irregularity Detection & Fraud Checks

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Fraud detection engine

---

## 1. eSTATEMENT FRAUD DETECTION (PDF Authenticity)

### Checks Performed

| Check | What It Does | Result |
|---|---|---|
| Font Validation | Checks for unexpected font styles per bank | PASS/FAIL |
| Creator/Producer Metadata | Validates PDF creator/producer fields against expected values per bank | PASS/FAIL |
| Digital Signature | Verifies authenticity of digital signature | PASS/FAIL |
| Creation/Modification Date | Checks for date discrepancies (e.g., modified after creation) | PASS/FAIL |

### Key Details
- **Result type**: Binary (PASS/FAIL), some systems may provide confidence score
- **Score impact**: Failed eStatement check CAN lower Precisa Score (severity-dependent)
- **Per-bank rules**: Each bank has expected font styles and PDF Creator/Producer values

### Sample Report Flags
- "Unexpected font style found" → Font validation FAIL
- "PDF Creator/Producer check failed" → Metadata validation FAIL

---

## 2. FINANCIAL IRREGULARITY RULES

### Complete Detection Rules with Thresholds

| # | Irregularity | Detection Rule | Threshold | Severity |
|---|---|---|---|---|
| 1 | **RTGS Payments below ₹2 lakhs** | RTGS transaction amount < ₹2,00,000 | ₹2,00,000 (RBI mandate) | Medium |
| 2 | **Round Figure Tax Payments** | Tax payment amount is a multiple of ₹1,000 or higher | Multiples of ₹1,000+ | **Low** |
| 3 | **ATM Withdrawals above ₹20,000** | Single ATM withdrawal > ₹20,000 | ₹20,000 fixed | Medium |
| 4 | **Negative Computed Balance in DR txns** | Running total (Opening + Credits − Debits) goes negative | Balance < 0 | **High** |
| 5 | **Computed Balance vs Balance Mismatch** | \|Computed Balance − Statement Balance\| > 2% of Statement Balance | **2% tolerance** (fixed for all balances) | **High** |
| 6 | **Parties in both debits and credits** | Same counterparty name appears in both credit AND debit transactions | Any occurrence = flag (money rotation indicator) | Medium |
| 7 | **UTR Number Repeated** | Exact match of UTR number across transactions | Exact match only | **High** |
| 8 | **Cheque deposits on bank holidays** | Cheque deposit/clearing date falls on a bank holiday | **RBI official holiday calendar** | Medium |
| 9 | **Cash deposit on Bank Holiday** | Cash deposit date falls on a bank holiday | **RBI official holiday calendar** | Medium |
| 10 | **More Cash deposits vs Salary** | Total Cash Deposits > 1.5 × Total Salary Credits | **Ratio > 1.5:1** | Medium |
| 11 | **Equal Debits & Credits** | \|Total Debits − Total Credits\| / max(Total Debits, Total Credits) < tolerance | **1–2% tolerance** | Low |
| 12 | **Immediate big debit after Salary** | Debit > 50% of salary amount within 1 day of salary credit | **>50% of salary within 1 day** | Medium |
| 13 | **Salary unchanged over extended period** | Same salary amount for extended months (exact threshold not confirmed, likely 6+ months) | Extended period = likely 6+ months | Low |
| 14 | **Cash Deposits in range ₹9L–₹10L** | Single cash deposit between ₹9,00,000 and ₹10,00,000 | ₹9,00,000 – ₹10,00,000 | **High** (Structuring/Smurfing) |
| 15 | **Cash Deposits in range ₹40K–₹50K** | Single cash deposit between ₹40,000 and ₹50,000 | ₹40,000 – ₹50,000 | Medium (RBI threshold) |
| 16 | **ATM Withdrawals above ₹2,000** | ATM withdrawal > ₹2,000 — flagged by frequency of small withdrawals | ₹2,000 (unusual spending pattern) | Low |

---

## 3. IRREGULARITY DETECTION FORMULAS

### Computed Balance Calculation

```python
def compute_running_balance(transactions: list[dict], opening_balance: float) -> list[float]:
    """
    Calculate computed balance as running total.
    Negative computed balance = irregularity flag.
    """
    balance = opening_balance
    computed_balances = []
    
    for txn in transactions:
        if txn['type'] == 'credit':
            balance += txn['amount']
        elif txn['type'] == 'debit':
            balance -= txn['amount']
        
        computed_balances.append(balance)
        
        # Flag: Negative computed balance
        if balance < 0:
            flag_irregularity('NEGATIVE_COMPUTED_BALANCE', txn, severity='HIGH')
    
    return computed_balances
```

### Balance Mismatch Detection

```python
def check_balance_mismatch(computed_balance: float, statement_balance: float) -> bool:
    """
    Flag if computed balance differs from statement balance by >2%.
    """
    if statement_balance == 0:
        return computed_balance != 0
    
    mismatch_pct = abs(computed_balance - statement_balance) / abs(statement_balance)
    return mismatch_pct > 0.02  # 2% tolerance
```

### Cash vs Salary Ratio

```python
def check_cash_vs_salary(total_cash_deposits: float, total_salary_credits: float) -> bool:
    """
    Flag if cash deposits exceed 1.5x salary.
    """
    if total_salary_credits == 0:
        return total_cash_deposits > 0  # Any cash with no salary = flag
    
    return total_cash_deposits > (1.5 * total_salary_credits)
```

### Immediate Big Debit After Salary

```python
from datetime import timedelta

def check_big_debit_after_salary(transactions: list[dict]) -> list[dict]:
    """
    Flag debits >50% of salary within 1 day of salary credit.
    """
    flags = []
    salary_txns = [t for t in transactions if t['category'] == 'Salary']
    
    for sal in salary_txns:
        sal_date = sal['date']
        sal_amount = sal['amount']
        threshold = sal_amount * 0.50  # 50% of salary
        
        # Check debits within 1 day
        for txn in transactions:
            if txn['type'] == 'debit' and txn['amount'] > threshold:
                days_diff = (txn['date'] - sal_date).days
                if 0 <= days_diff <= 1:
                    flags.append({
                        'salary_date': sal_date,
                        'salary_amount': sal_amount,
                        'debit_date': txn['date'],
                        'debit_amount': txn['amount'],
                        'pct_of_salary': txn['amount'] / sal_amount * 100
                    })
    return flags
```

### Cash Structuring Detection (₹9L–₹10L)

```python
def check_cash_structuring(transactions: list[dict]) -> list[dict]:
    """
    Detect structuring: cash deposits between ₹9L and ₹10L
    (just below the ₹10L RBI reporting threshold).
    """
    flags = []
    for txn in transactions:
        if txn['type'] == 'credit' and 'Cash' in txn.get('tags', []):
            if 900000 <= txn['amount'] <= 1000000:
                flags.append({
                    'type': 'STRUCTURING_9_10L',
                    'severity': 'HIGH',
                    'amount': txn['amount'],
                    'date': txn['date']
                })
            elif 40000 <= txn['amount'] <= 50000:
                flags.append({
                    'type': 'STRUCTURING_40_50K',
                    'severity': 'MEDIUM',
                    'amount': txn['amount'],
                    'date': txn['date']
                })
    return flags
```

### Round Figure Tax Detection

```python
def check_round_figure_tax(transactions: list[dict]) -> list[dict]:
    """
    Flag tax payments that are multiples of ₹1,000.
    """
    flags = []
    for txn in transactions:
        if txn.get('category') == 'Tax Paid':
            if txn['amount'] % 1000 == 0:  # Multiple of ₹1,000
                flags.append({
                    'type': 'ROUND_FIGURE_TAX',
                    'severity': 'LOW',
                    'amount': txn['amount'],
                    'date': txn['date']
                })
    return flags
```

### RTGS Below Minimum

```python
def check_rtgs_below_minimum(transactions: list[dict]) -> list[dict]:
    """
    Flag RTGS transactions below ₹2,00,000 (RBI mandate).
    """
    flags = []
    for txn in transactions:
        if 'RTGS' in txn.get('tags', []) and txn['amount'] < 200000:
            flags.append({
                'type': 'RTGS_BELOW_MINIMUM',
                'severity': 'MEDIUM',
                'amount': txn['amount'],
                'date': txn['date']
            })
    return flags
```

### Equal Debits & Credits Detection

```python
def check_equal_debits_credits(total_debits: float, total_credits: float) -> bool:
    """
    Flag if total debits ≈ total credits (within 1-2% tolerance).
    Indicates potential money rotation / pass-through account.
    """
    if max(total_debits, total_credits) == 0:
        return False
    
    diff_pct = abs(total_debits - total_credits) / max(total_debits, total_credits)
    return diff_pct < 0.02  # Within 2% = suspicious
```

### UTR Duplicate Detection

```python
def check_duplicate_utr(transactions: list[dict]) -> list[dict]:
    """
    Flag exact duplicate UTR numbers.
    """
    utr_map = {}
    flags = []
    
    for txn in transactions:
        utr = txn.get('utr_number')
        if utr and utr in utr_map:
            flags.append({
                'type': 'UTR_REPEATED',
                'severity': 'HIGH',
                'utr': utr,
                'original_date': utr_map[utr]['date'],
                'duplicate_date': txn['date']
            })
        elif utr:
            utr_map[utr] = txn
    
    return flags
```

### Bank Holiday Check

```python
def check_holiday_transactions(transactions: list[dict], rbi_holidays: set) -> list[dict]:
    """
    Flag cheque deposits or cash deposits on RBI bank holidays.
    Holiday calendar: RBI official list (https://www.rbi.org.in/scripts/HolidayMat498.aspx)
    """
    flags = []
    for txn in transactions:
        if txn['date'] in rbi_holidays:
            if 'Cheque' in txn.get('tags', []):
                flags.append({
                    'type': 'CHEQUE_ON_HOLIDAY',
                    'severity': 'MEDIUM',
                    'date': txn['date']
                })
            elif 'Cash' in txn.get('tags', []) and txn['type'] == 'credit':
                flags.append({
                    'type': 'CASH_DEPOSIT_ON_HOLIDAY',
                    'severity': 'MEDIUM',
                    'date': txn['date']
                })
    return flags
```

---

## 4. SEVERITY LEVELS

### Scale: 4 Levels

| Level | Description | Score Impact |
|---|---|---|
| **Low** | Minor anomaly, informational | ~2 points reduction per occurrence |
| **Medium** | Notable concern, review recommended | ~5 points reduction per occurrence (estimated) |
| **High** | Significant risk indicator | ~10 points reduction per occurrence |
| **Critical** | Severe fraud/compliance risk | ~20+ points reduction per occurrence (estimated) |

### Severity Assignment per Irregularity

| Irregularity | Severity | Rationale |
|---|---|---|
| Round Figure Tax Payments | **Low** | Common in legitimate tax payments |
| ATM Withdrawals above ₹2,000 | **Low** | Frequency-based, minor |
| Equal Debits & Credits | **Low** | Could be legitimate |
| Salary unchanged extended period | **Low** | Common for stable employment |
| RTGS Payments below ₹2L | **Medium** | RBI rule violation — why use RTGS for small amounts? |
| ATM Withdrawals above ₹20,000 | **Medium** | RBI daily limit concern |
| Cheque/Cash on Bank Holiday | **Medium** | Possible backdating |
| Cash deposits > 1.5× Salary | **Medium** | Source of funds concern |
| Big debit after Salary (>50% in 1 day) | **Medium** | Pass-through risk |
| Parties in both debits & credits | **Medium** | Money rotation indicator |
| Cash Deposits ₹40K–₹50K | **Medium** | RBI threshold proximity |
| Negative Computed Balance | **High** | Statement integrity issue |
| Balance Mismatch >2% | **High** | Possible tampering |
| UTR Number Repeated | **High** | Duplicate transaction / fraud |
| Cash Deposits ₹9L–₹10L | **High** | Structuring / smurfing (below ₹10L reporting) |
| eStatement font/metadata FAIL | **High–Critical** | Possible PDF tampering |

### Score Impact Formula (Estimated)

```python
SEVERITY_POINTS = {
    'LOW': 2,
    'MEDIUM': 5,
    'HIGH': 10,
    'CRITICAL': 20
}

def calculate_irregularity_penalty(irregularities: list[dict]) -> int:
    """
    Calculate total score reduction from irregularities.
    Each irregularity reduces the Precisa Score by severity-based points.
    """
    total_penalty = 0
    for irr in irregularities:
        severity = irr.get('severity', 'LOW')
        total_penalty += SEVERITY_POINTS.get(severity, 2)
    return total_penalty
```

---

## 5. KEY THRESHOLDS SUMMARY

| Parameter | Threshold | Unit |
|---|---|---|
| RTGS minimum | ₹2,00,000 | Amount |
| ATM high withdrawal | ₹20,000 | Amount |
| ATM low withdrawal flag | ₹2,000 | Amount |
| Round figure tax | Multiples of ₹1,000 | Amount |
| Balance mismatch tolerance | 2% | Percentage |
| Cash vs Salary ratio | 1.5:1 | Ratio |
| Big debit after salary | >50% of salary | Percentage |
| Big debit time window | 1 day | Days |
| Equal debits/credits tolerance | 1–2% | Percentage |
| Cash structuring (high) | ₹9,00,000 – ₹10,00,000 | Amount range |
| Cash structuring (medium) | ₹40,000 – ₹50,000 | Amount range |
| Holiday calendar | RBI official list | Calendar |
| UTR match | Exact match | String |
| Severity: Low penalty | ~2 points | Score |
| Severity: High penalty | ~10 points | Score |

---

## 6. IMPLEMENTATION NOTES

### Files to Modify
- `Feature Extraction/src/engines/fraud_engine.py` → Add all 16 irregularity checks
- `Feature Extraction/src/engines/rules_config.json` → Add thresholds under `fraud_engine_config`
- New file needed: `Feature Extraction/src/rules/rbi_holidays.json` → RBI bank holiday calendar

### Integration with Existing Fraud Engine
Our current `fraud_engine_config` in `rules_config.json` already has:
- `round_txn_modulus: 1000` → Similar to round figure detection
- `structuring_min_amount: 45000, structuring_max_amount: 49999` → Maps to ₹40-50K check
- `high_value_cash_threshold: 25000` → Near the ₹20K ATM threshold
- `rapid_transfer_window_hours: 2.0` → Related to "immediate debit after salary"

### What's New to Add
1. RTGS below ₹2L check (new)
2. Balance mismatch at 2% tolerance (new)
3. Cash vs Salary 1.5:1 ratio (new)
4. Big debit >50% salary within 1 day (new)
5. Cash ₹9-10L structuring (enhance existing)
6. UTR duplicate detection (new)
7. Bank holiday calendar integration (new)
8. Equal debits & credits check (new)
9. Parties in both debits & credits (new)
10. eStatement PDF fraud checks (separate module — PDF level)
