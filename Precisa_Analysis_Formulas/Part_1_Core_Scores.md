# Part 1: Core Scores — Precisa Score, Volatility Score, FOIR Score

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Bank Statement Analysis scoring engine

---

## 1. PRECISA SCORE

### Overview
- **Type**: Composite credit risk score derived from bank statement analysis
- **Range**: 0–1000 (higher = lower risk, 1000 = no risk)
- **Calculation scope**: Per account (can be consolidated across multiple statements)
- **Difference from CIBIL**: Captures real-time cash flow, balance behavior, and transaction patterns — signals that bureau scores don't capture

### Risk Bands

| Band | Score Range | Interpretation |
|---|---|---|
| Very Low Risk | 800–1000 | Excellent financial health |
| Low Risk | 650–799 | Good financial health |
| Moderate Risk | 500–649 | Average, needs review |
| High Risk | 300–499 | Concerning, likely reject |
| Very High Risk | 0–299 | Severe risk, reject |

**Sample report value**: 744 → Low Risk

### Input Parameters

| Parameter | Direction | Notes |
|---|---|---|
| Average Balance | Higher = Higher score ↑ | Monthly average EOD balance |
| Cheque Bounce Rate | Higher = Lower score ↓ | Threshold: >1% by transaction COUNT starts impacting |
| Cash Deposit % | Higher = Higher score ↑ | Increases total inflow, BUT >30% triggers separate irregularity flag |
| FOIR | Higher = Lower score ↓ | Fixed Obligation to Income Ratio |
| Volatility Score | Higher = Lower score ↓ | EOD balance variance |
| Irregularity Count | More = Lower score ↓ | All irregularity types combined |
| EMI Regularity | Better = Higher score ↑ | (Paid on time / Total expected) × 100 |
| Balance Stability | Related to Volatility | NOT a separate sub-score — the volatility score IS the balance stability measure |
| Suspicious Activities | More = Lower score ↓ | AML-related flags |
| OD/CC Utilization | Higher utilization = Lower score ↓ | Overdraft/Cash Credit usage |

### What We DON'T Know (Proprietary)
- Exact weight (%) of each parameter in the composite score
- How parameters are combined (linear, weighted sum, ML model, etc.)
- Whether there's a minimum data threshold before score is calculated
- Exact penalty values for each irregularity type

---

## 2. VOLATILITY SCORE

### Overview
- **Type**: Account stability metric
- **Range**: 0 to 1 (0 = perfectly stable, 1 = highly volatile)
- **Also serves as**: The "Balance Stability" component in the Precisa Score (not a separate sub-score)

### Formula

```
Volatility Score = StdDev(Daily EOD Balances) / Mean(Daily EOD Balances)
```

This is the **Coefficient of Variation (CV)** of daily end-of-day balances.

**Additional factor**: Also considers stability of transaction amounts (inflows/outflows), not just balances.

### Calculation Details
- **Granularity**: Daily transaction-level data (not monthly aggregates)
- **Balance data used**: End-of-Day (EOD) balance for each calendar day in the statement period
- **For days with no transactions**: EOD balance carries forward from previous day

### Implementation Formula (Python pseudocode)

```python
import numpy as np

def calculate_volatility(daily_eod_balances: list[float]) -> float:
    """
    Calculate Precisa-style volatility score.
    
    Args:
        daily_eod_balances: List of EOD balances for each day in statement period
    
    Returns:
        Volatility score between 0 and 1
    """
    balances = np.array(daily_eod_balances)
    mean_balance = np.mean(balances)
    
    if mean_balance == 0:
        return 1.0  # Edge case: zero mean = maximum volatility
    
    std_dev = np.std(balances)
    volatility = std_dev / mean_balance
    
    # Clamp to 0-1 range
    return min(max(volatility, 0.0), 1.0)
```

### Risk Bands

| Band | Score Range | Interpretation |
|---|---|---|
| Low | 0.00–0.15 | Stable account, consistent balances |
| Moderate | 0.15–0.40 | Normal variation, acceptable |
| High | 0.40–0.70 | Significant fluctuations, needs review |
| Very High | 0.70–1.00 | Extreme instability, red flag |

**Sample report value**: 0.25 → Moderate

---

## 3. FOIR SCORE (Fixed Obligation to Income Ratio)

### Overview
- **Type**: Debt burden indicator
- **Formula**: `FOIR = Total Fixed Obligations / Total Income`
- **Calculation period**: Total aggregates across full statement period (NOT monthly average)
- **Range**: 0 to 1+ (can exceed 1.0 if obligations > income)

### Income Definition (Denominator)

**INCLUDED in Total Income:**
- All inward credits (deposits)
- Cash deposits ✅
- Salary credits ✅
- Cheque deposits ✅
- NEFT/IMPS/UPI inward ✅
- Business receipts ✅

**EXCLUDED from Total Income:**
- Loan disbursement credits ❌ (e.g., "CAPITAL FIRST LIMITED" credit of ₹4,50,000)
- Internal transfers ❌ (transfers between own accounts)
- Cheque return credits ❌ (bounced cheque reversals like "RETURNED:49:FUNDS INSUFFICIENT")

### Fixed Obligations Definition (Numerator)

**INCLUDED in Fixed Obligations:**
- EMI payments ✅ (Bajaj Finance, Edelweiss, Fullerton, Magma, etc.)
- Insurance premiums ✅ (LIC/ACH Debit, health insurance)
- NACH mandates ✅ (all auto-debit mandates)
- Recurring payments ✅ (any detected recurring outflow)

**NOT included (implied):**
- One-time large payments ❌
- Variable business expenses ❌
- ATM withdrawals ❌
- Tax payments ❌
- Bank charges ❌

### Implementation Formula (Python pseudocode)

```python
def calculate_foir(transactions: list[dict]) -> float:
    """
    Calculate FOIR from transaction list.
    
    Each transaction has: amount, type (credit/debit), category, tags
    """
    # Calculate Total Income (denominator)
    total_income = 0
    for txn in transactions:
        if txn['type'] == 'credit':
            # Exclude loan disbursements
            if 'Loan' in txn.get('tags', []) and txn['category'] == 'Loan':
                continue
            # Exclude internal transfers
            if txn['category'] == 'Internal Transfer':
                continue
            # Exclude cheque return credits
            if 'Return' in txn.get('tags', []):
                continue
            total_income += txn['amount']
    
    # Calculate Fixed Obligations (numerator)
    fixed_obligations = 0
    for txn in transactions:
        if txn['type'] == 'debit':
            tags = txn.get('tags', [])
            category = txn.get('category', '')
            
            # EMI payments
            if 'EMI' in tags:
                fixed_obligations += txn['amount']
            # Insurance premiums
            elif 'Insurance' in tags or category == 'Insurance':
                fixed_obligations += txn['amount']
            # NACH mandates (non-EMI, non-insurance)
            elif 'NACH' in tags:
                fixed_obligations += txn['amount']
            # Other detected recurring payments
            elif txn.get('is_recurring', False):
                fixed_obligations += txn['amount']
    
    if total_income == 0:
        return 1.0  # Edge case: no income = maximum risk
    
    return fixed_obligations / total_income
```

### Risk Bands

| Band | FOIR Range | Interpretation |
|---|---|---|
| Low Risk | < 0.30 | Healthy — obligations are < 30% of income |
| Moderate Risk | 0.30–0.50 | Acceptable but stretched |
| High Risk | 0.50–0.70 | Debt-heavy, repayment capacity strained |
| Very High Risk | > 0.70 | Severe — obligations consume > 70% of income |

**Sample report value**: 0.15 → Low Risk

---

## 4. EMI REGULARITY SCORE

### Formula

```
EMI Regularity = (Number of EMIs Paid On Time / Total Expected EMIs) × 100
```

### Examples
- 9 out of 9 on time → 100% (perfect)
- 8 out of 9 on time → 88.89%
- 7 out of 9 on time → 77.78%

### Detection Logic
- "On time" = EMI paid within the expected date window (typically ± 5 days of due date)
- "Expected EMIs" = derived from first EMI date, interval (monthly), and statement period
- "Misses" = months where expected EMI was not found in statement

### Impact on Precisa Score
- 100% regularity → positive contribution
- Each miss reduces the score
- Exact penalty per miss is proprietary

---

## 5. CHEQUE BOUNCE RATE

### Formula

```
Cheque Bounce Rate = (Number of Bounced Cheques / Total Cheques Presented) × 100
```

### Key Details
- **Calculation basis**: By transaction COUNT (not amount)
- **Threshold**: >1% bounce rate starts negatively impacting the Precisa Score
- **A single bounce**: May not significantly impact the score if total cheque count is high
- **Types tracked separately**: Inward bounces vs Outward bounces (both affect score negatively)

### Examples
- 0 bounces out of 20 cheques → 0% → No impact
- 1 bounce out of 100 cheques → 1% → Borderline
- 2 bounces out of 20 cheques → 10% → Significant negative impact

---

## 6. CASH DEPOSIT PERCENTAGE

### Formula

```
Cash Deposit % = (Total Cash Deposits / Total Credits) × 100
```

### Dual Impact
1. **Score impact**: Higher cash deposits increase total inflow → positive for score
2. **Irregularity flag**: If Cash Deposit % > 30% of total credits → triggers a concern flag SEPARATELY from the score

### Thresholds
- < 30% → Normal, no flag
- > 30% → Raises concern about source of funds (irregularity flag triggered)
- This threshold may vary by context (business accounts vs salaried)

---

## 7. CROSS-REFERENCE: SAMPLE REPORT VALUES

From the Precisa BSA Sample Report (Maheshwari Traders, Axis Bank, Jan–Sep 2020):

| Metric | Value | Band | Notes |
|---|---|---|---|
| Precisa Score | 744 | Low Risk (650–799) | Good financial health |
| Volatility Score | 0.25 | Moderate (0.15–0.40) | Normal variation |
| FOIR Score | 0.15 | Low Risk (<0.30) | Healthy debt burden |
| Cheque Bounce Count | 2 (total) | — | Observed in Overview sheet |
| Total Transactions | 105 | — | Over 9 months |
| Monthly Avg Balance | ₹6,03,586 | — | Across statement period |
| Cash Deposits | ₹9,91,000 | — | 4 transactions |
| Cash Deposit % | ~39.4% | >30% flag | ₹9,91,000 / ₹25,12,732 total credits |
| Total EMI Payments | ₹8,90,387 | — | 20 EMI transactions |
| EMI Regularity | 100% | Perfect | 0 misses across all lenders |
| Circular Transactions | 0 | Clean | No circular flows detected |

---

## 8. IMPLEMENTATION NOTES

### Priority for Our Pipeline
1. **Volatility Score** → Easiest to implement, formula is clear (CV of daily EOD balances)
2. **FOIR Score** → Need categorization engine to identify fixed obligations vs income
3. **EMI Regularity** → Need recurring payment detection first
4. **Cheque Bounce Rate** → Need cheque transaction identification
5. **Cash Deposit %** → Need cash transaction tagging
6. **Precisa Score (composite)** → Hardest — weights are proprietary, will need to design our own weighting

### Dependencies on Other Parts
- FOIR requires → Transaction categorization (Part 2) + Loan/EMI detection (Part 5)
- Cash Deposit % requires → Transaction tagging with "Cash" tag (Part 2)
- EMI Regularity requires → Recurring payment detection (Part 5)
- Precisa Score requires → ALL sub-scores computed first

### Files to Modify in Our Pipeline
- `Feature Extraction/src/engines/balance.py` → Add volatility score calculation
- `Feature Extraction/src/engines/debt_engine.py` → Add FOIR calculation + EMI regularity
- `Feature Extraction/src/engines/behaviour_engine.py` → Add cheque bounce rate + cash deposit %
- `Feature Extraction/src/engines/fraud_engine.py` → Add cash deposit >30% irregularity flag
- `Feature Extraction/src/engines/rules_config.json` → Add all threshold values from this document
