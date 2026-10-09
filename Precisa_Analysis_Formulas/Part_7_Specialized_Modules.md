# Part 7: UPI, Salary, Savings & Investments, OD/CC & Specialized Modules

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Income engine, debt engine, behaviour engine, cashflow engine

---

## 1. UPI TRANSACTION ANALYSIS

### P2P vs P2M Classification

| Type | Definition | Detection Mechanism |
|---|---|---|
| **P2P (Peer-to-Peer)** | Transfers between individuals | Personal VPAs (`@ybl`, `@paytm`, `@oksbi`, `@okhdfcbank`) or person names |
| **P2M (Peer-to-Merchant)** | Payments to businesses/merchants | Merchant VPAs (`@bharatpe`, `@razorpay`, `@hdfcbanksmartpay`), MCC merchant codes |

### App Identification
- **Method**: Regex extraction of VPA handles and narration tokens:
  - PhonePe: `@ybl`, `@ibl`, `@axl`
  - Google Pay: `@okhdfcbank`, `@oksbi`, `@okaxis`, `@okicici`
  - Paytm: `@paytm`
  - BharatPe: `*BHARATPE*`, `@bharatpe`

### UPI Behavior Score
- Metric derived from UPI transaction volume, P2P vs P2M ratio, and transaction frequency.
- High P2M ratio in a retail business account indicates healthy direct customer receipts.

---

## 2. SALARY DETECTION & CONSISTENCY SCORE

### Identification Criteria
1. **Keyword match**: Narration contains `"SALARY"`, `"SAL"`, `"PAYROLL"`.
2. **Behavioral match (No keyword)**:
   - **Monthly recurrence**: Frequency of ~30 days (±3 days).
   - **Amount consistency**: Consistent amount month-over-month (±5%).
   - **Counterparty source**: Consistent corporate/employer entity.

### Multi-Source Salary & Aggregation
- System aggregates multiple verified salary credits into total monthly salary income.
- Used directly in the **FOIR denominator** (Income).

### Salary Consistency Score
- Derived from month-on-month regularity and absence of missed salary credits.

```python
def calculate_salary_consistency(salary_txns: list[dict], statement_months: int) -> dict:
    """
    Calculate salary consistency and identify gaps.
    """
    received_count = len(salary_txns)
    if statement_months == 0:
        return {'score': 0, 'status': 'NO_DATA'}
    
    consistency_pct = min(100.0, (received_count / statement_months) * 100)
    
    # Assess amount variance
    amounts = [t['amount'] for t in salary_txns]
    avg_salary = sum(amounts) / len(amounts) if amounts else 0
    std_salary = (sum((x - avg_salary)**2 for x in amounts) / len(amounts))**0.5 if amounts else 0
    cov = (std_salary / avg_salary) if avg_salary > 0 else 0
    
    return {
        'consistency_pct': round(consistency_pct, 2),
        'salary_cov': round(cov, 3),
        'missed_months': max(0, statement_months - received_count),
        'avg_monthly_salary': round(avg_salary, 2),
        'score': round(max(0, consistency_pct * (1.0 - cov)), 2)
    }
```

---

## 3. SAVINGS & INVESTMENTS ANALYSIS

### Detection Rules & Keywords

| Investment Type | Narration Keywords / Indicators | Treatment |
|---|---|---|
| **Mutual Fund SIP** | `"MUTUAL FUND"`, `"SIP"`, `"AMC"`, `"HDFC MF"`, `"NIPPON"`, `"ICICIPRU MF"` | Tagged as Savings / MF |
| **Recurring Deposits** | `"RD INSTALLMENT"`, `"RD DEPOSIT"`, `"RECURRING DEP"` | Tagged as Savings / RD |
| **Govt Schemes** | `"PPF"`, `"NPS"`, `"SSY"`, `"SUKANYA"`, `"NSC"` | Tagged as Savings / Govt Schemes |

### Savings & Investment % Formula

```
Savings & Investment % = (Total Monthly Investments / Total Monthly Income) × 100
```

- **Score Impact**: Positive behavior signal that boosts creditworthiness and overall Precisa score.

---

## 4. OD/CC UTILIZATION & LIMIT MONITORING

### Parameters

| Metric | Determination | Thresholds |
|---|---|---|
| **Sanction Limit** | Extracted from statement header / metadata or user input | Baseline limit amount |
| **Overdrawn Days** | Count of days where EOD Balance went negative beyond limit | 0 is ideal; >0 is flagged |
| **Utilization Rate** | `(Average Utilized Amount / Sanction Limit) * 100` | **<30% = Healthy**, **30-50% = Moderate**, **>50% = Risky**, **>100% = Negative Impact** |

### Implementation

```python
def analyze_od_cc_utilization(daily_eod_balances: dict, sanction_limit: float) -> dict:
    """
    Analyze OD/CC account utilization metrics.
    """
    if sanction_limit <= 0:
        return {'status': 'NO_SANCTION_LIMIT'}
    
    total_days = len(daily_eod_balances)
    overdrawn_days = 0
    utilization_list = []
    
    for date, balance in daily_eod_balances.items():
        # In OD/CC accounts, debit balance is utilized limit (represented as negative or debit)
        utilized = max(0.0, -balance) if balance < 0 else 0.0
        util_pct = (utilized / sanction_limit) * 100
        utilization_list.append(util_pct)
        
        if utilized > sanction_limit:
            overdrawn_days += 1
            
    avg_utilization = sum(utilization_list) / total_days if total_days > 0 else 0
    max_utilization = max(utilization_list, default=0)
    
    if avg_utilization < 30:
        band = 'HEALTHY'
    elif avg_utilization <= 50:
        band = 'MODERATE'
    else:
        band = 'RISKY'
        
    return {
        'sanction_limit': sanction_limit,
        'avg_utilization_pct': round(avg_utilization, 2),
        'max_utilization_pct': round(max_utilization, 2),
        'overdrawn_days': overdrawn_days,
        'utilization_band': band,
        'exceeds_100_pct': max_utilization > 100
    }
```

---

## 5. DUPLICATE TRANSACTION DETECTION

### Matching Logic
- **Exact duplicate criteria**: Same `Transaction Date` + Same `Amount` + Same `Narration/Description`.
- **Cross-statement checks**: Compares across multiple uploaded PDF files to avoid duplicate statement overlap.
- **Handling**: Auto-deduplicates exact duplicates or flags identical same-day transactions for manual audit.

---

## 6. HIGH-VALUE TRANSACTION FLAGGING

### Criteria
- **Default Fixed Threshold**: `>₹1,00,000` (configurable by user/lender).
- **Directional Separation**: Separate rules and thresholds for Debits vs Credits.
- **Relative Threshold**: Debits/Credits exceeding `>50%` of monthly average balance or `>3×` average transaction size.
- **Outcome**: Flagged as high-value for underwriting and risk review.

---

## 7. COMPUTED BALANCE VS STATEMENT BALANCE

### Architecture & Integrity Checks
- **Computed Balance**: Mathematical running balance calculated step-by-step:
  $$\text{Computed Balance}_{t} = \text{Balance}_{t-1} + \text{Credit}_t - \text{Debit}_t$$
- **Adjusted Balance**: Reconciled balance taking into account back-dated value dates, reversals, or corrections.
- **Balance Gap**: $|\text{Computed Balance} - \text{Statement Balance}|$.
- **Tolerance**: $2\%$ mismatch threshold triggers high-severity fraud flag.

---

## 8. NET DEBIT & NET CREDIT (TURNOVER COMPUTATION)

### Exclusion Rules for Actual Turnover

To compute real operational business turnover:
$$\text{Net Credit (True Turnover)} = \text{Total Credits} - (\text{Loan Disbursements} + \text{Internal Transfers} + \text{Returns/Reversals})$$
$$\text{Net Debit (True Expense)} = \text{Total Debits} - (\text{Loan EMIs} + \text{Internal Transfers} + \text{Returns/Reversals})$$

### Summary Table

| Inflow/Outflow Item | Total Credit/Debit | Net Credit/Debit (Turnover) |
|---|---|---|
| Customer Sales / Receipts | ✅ Included | ✅ Included |
| Operational Supplier Payments | ✅ Included | ✅ Included |
| Loan Disbursements | ✅ Included | ❌ **Excluded** |
| Loan EMIs / Repayments | ✅ Included | ❌ **Excluded** |
| Own Account / Internal Transfers | ❌ Excluded / Ignored | ❌ **Excluded** |
| Cheque / NACH Returns | ✅ Recorded | ❌ **Excluded** |

---

## 9. IMPLEMENTATION & PIPELINE MAPPING

### Files to Modify
- `Feature Extraction/src/engines/debt_engine.py` → Add OD/CC utilization engine & limit violation tracker.
- `Feature Extraction/src/engines/cashflow.py` → Implement Net Credit / Net Debit turnover calculation.
- `Feature Extraction/src/engines/income.py` → Integrate multi-source salary aggregation & consistency scoring.
- `Feature Extraction/src/classifier.py` → Enhance SIP / Govt scheme keyword tags and UPI VPA app recognizer.
