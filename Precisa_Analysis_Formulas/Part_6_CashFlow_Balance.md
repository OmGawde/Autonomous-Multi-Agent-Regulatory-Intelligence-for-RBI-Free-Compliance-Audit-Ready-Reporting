# Part 6: Cash Flow, Balance Analysis & Counterparty Concentration

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Cash flow engine, balance engine, behaviour engine

---

## 1. CASH FLOW CLASSIFICATION

### Business vs Non-Business

| Category | Classification |
|---|---|
| Sales & Marketing | **Business** |
| Office Expenses | **Business** |
| O/W Funds Transfer (to business entities) | **Business** |
| I/W Funds Transfer (from business entities) | **Business** |
| Loan / EMI | **Non-Business** |
| Salary (inflow) | **Non-Business** |
| Insurance | **Non-Business** |
| Cash Deposit | **Non-Business** (unless specified for business) |
| Internal Transfer | **Excluded** from cash flow |
| Cheque Return Credits | **Included** as inflow |
| Loan Disbursement Credits | **Included** as inflow |

### Cash Flow Formulas

```python
def calculate_cash_flows(transactions: list[dict]) -> dict:
    """
    Calculate standard and business cash flows.
    """
    BUSINESS_CATEGORIES = [
        'Sales & Marketing', 'Office Expenses',
    ]
    EXCLUDED_CATEGORIES = ['Internal Transfer']
    NON_BIZ_CATEGORIES = [
        'Loan / EMI', 'Salary', 'Insurance', 'Tax Paid',
        'Charges & Fees / Bank Charges', 'Charges & Fees / Penal Charges',
        'Entertainment', 'Cash & ATM withdrawals / ATM'
    ]
    
    total_inflow = 0
    total_outflow = 0
    biz_inflow = 0
    biz_outflow = 0
    non_biz_inflow_count = 0
    non_biz_outflow_count = 0
    
    for txn in transactions:
        cat = txn.get('category', '')
        if cat in EXCLUDED_CATEGORIES:
            continue
        
        if txn['type'] == 'credit':
            total_inflow += txn['amount']
            if cat in BUSINESS_CATEGORIES or txn.get('is_business', False):
                biz_inflow += txn['amount']
            else:
                non_biz_inflow_count += 1
        elif txn['type'] == 'debit':
            total_outflow += txn['amount']
            if cat in BUSINESS_CATEGORIES or txn.get('is_business', False):
                biz_outflow += txn['amount']
            else:
                non_biz_outflow_count += 1
    
    return {
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_cash_flow': total_inflow - total_outflow,
        'biz_inflow': biz_inflow,
        'biz_outflow': biz_outflow,
        'pct_biz_inflow': (biz_inflow / total_inflow * 100) if total_inflow > 0 else 0,
        'pct_biz_outflow': (biz_outflow / total_outflow * 100) if total_outflow > 0 else 0,
        'net_biz_cash_flow': biz_inflow - biz_outflow,
        'non_biz_inflow_count': non_biz_inflow_count,
        'non_biz_outflow_count': non_biz_outflow_count
    }
```

### Aggregation Periods
- Monthly, Quarterly (Last 3, 6, 9, 12 months), Financial Year
- **Averaging method**: Simple averages (weighted averages may apply in specific analyses)
- **Incomplete data**: If <12 months, may extrapolate based on available data

---

## 2. BALANCE ANALYSIS

### Daily Balance Change %

**Formula:**
```
Daily Balance Change % = ((Today's EOD Balance - Yesterday's EOD Balance) / Yesterday's EOD Balance) × 100
```

```python
def calculate_daily_balance_change(daily_eod_balances: dict) -> list[dict]:
    """
    Calculate day-over-day balance change percentage.
    """
    sorted_dates = sorted(daily_eod_balances.keys())
    changes = []
    
    for i in range(1, len(sorted_dates)):
        today = sorted_dates[i]
        yesterday = sorted_dates[i-1]
        today_bal = daily_eod_balances[today]
        yesterday_bal = daily_eod_balances[yesterday]
        
        if yesterday_bal != 0:
            change_pct = ((today_bal - yesterday_bal) / abs(yesterday_bal)) * 100
        else:
            change_pct = 0 if today_bal == 0 else 100
        
        changes.append({
            'date': today,
            'eod_balance': today_bal,
            'prev_balance': yesterday_bal,
            'change_pct': round(change_pct, 2)
        })
    
    return changes
```

### ABB (Average Balance on 1st, 14th, 30th)
- **Purpose**: Assess consistency in maintaining minimum balance requirements
- **Impact**: Used in scoring — consistent balance above MAB = positive signal
- **Dates tracked**: 1st, 14th, 30th (or last day) of each month

### Available Balance Distribution
- **Method**: Threshold-based (NOT percentile)
- Shows percentage of days balance exceeded specific amounts (₹50K, ₹1L, ₹5L, ₹10L)

```python
def calculate_balance_distribution(daily_eod_balances: dict, 
                                    thresholds: list[float] = None) -> dict:
    """
    Calculate what % of days balance exceeded each threshold.
    """
    if thresholds is None:
        thresholds = [50000, 100000, 200000, 500000, 1000000]
    
    total_days = len(daily_eod_balances)
    if total_days == 0:
        return {}
    
    balances = list(daily_eod_balances.values())
    distribution = {}
    
    for threshold in thresholds:
        days_above = sum(1 for b in balances if b >= threshold)
        distribution[f'above_{threshold}'] = round(days_above / total_days * 100, 2)
    
    return distribution
```

### Balance Stability Score
- **Separate metric** from Volatility Score
- **Range**: 0–1 (like Volatility)
- **Measures**: Consistency in daily balances (different aspect from volatility)
- **Volatility** = overall variance; **Stability** = day-to-day consistency

---

## 3. COUNTERPARTY CONCENTRATION RISK

### Concentration Bands

| Band | Threshold | Risk Level |
|---|---|---|
| Normal | <30% from single counterparty | Low risk |
| **Moderate** | **>30%** from single counterparty | Review needed |
| **High** | **>50%** from single counterparty | Significant risk |
| **Critical** | **>70%** from single counterparty | Severe dependency |

### Primary Transaction Category
- **Determination**: Most frequent OR highest value transaction category for a counterparty
- When counterparty has multiple categories → most frequent wins (ties broken by highest amount)

### Impact on Score
- Greater counterparty diversity → **higher** Precisa Score (reduced risk)
- High concentration (>50% from one source) → **lower** score

### Implementation

```python
from collections import defaultdict

def analyze_counterparty_concentration(transactions: list[dict]) -> dict:
    """
    Analyze counterparty concentration risk.
    """
    # Calculate per-counterparty totals
    credit_by_cp = defaultdict(float)
    debit_by_cp = defaultdict(float)
    total_credits = 0
    total_debits = 0
    
    for txn in transactions:
        cp = txn.get('counterparty', 'Unknown')
        if txn['type'] == 'credit':
            credit_by_cp[cp] += txn['amount']
            total_credits += txn['amount']
        else:
            debit_by_cp[cp] += txn['amount']
            total_debits += txn['amount']
    
    # Calculate concentration percentages
    credit_concentration = {}
    for cp, amount in credit_by_cp.items():
        pct = (amount / total_credits * 100) if total_credits > 0 else 0
        credit_concentration[cp] = {
            'amount': amount,
            'pct': round(pct, 2),
            'band': _get_concentration_band(pct)
        }
    
    # Find highest concentration
    max_credit_pct = max((c['pct'] for c in credit_concentration.values()), default=0)
    max_debit_pct = max(
        ((amt / total_debits * 100) if total_debits > 0 else 0 
         for amt in debit_by_cp.values()), 
        default=0
    )
    
    return {
        'credit_concentration': credit_concentration,
        'max_credit_concentration_pct': round(max_credit_pct, 2),
        'max_debit_concentration_pct': round(max_debit_pct, 2),
        'overall_risk': _get_concentration_band(max(max_credit_pct, max_debit_pct)),
        'unique_counterparties': len(set(list(credit_by_cp.keys()) + list(debit_by_cp.keys())))
    }

def _get_concentration_band(pct: float) -> str:
    if pct >= 70:
        return 'CRITICAL'
    elif pct >= 50:
        return 'HIGH'
    elif pct >= 30:
        return 'MODERATE'
    return 'NORMAL'
```

---

## 4. BUSINESS HEALTH METRICS

### Biz Avg Balance
- **Calculation**: Average of daily EOD balances computed from ONLY business-tagged transactions
- **Difference from Monthly Avg Balance**: Monthly includes ALL transactions; Biz excludes personal

### Business Health Score
- **Exists**: Yes (may be derived from business cash flow metrics)
- **Likely inputs**: Net Biz Cash Flow trend, Biz Inflow consistency, Biz Outflow regularity
- **Range**: Not confirmed (likely 0–100)

---

## 5. KEY THRESHOLDS SUMMARY

| Parameter | Value | Notes |
|---|---|---|
| Daily Balance Change % | ((Today - Yesterday) / Yesterday) × 100 | Day-over-day |
| Balance Distribution | Threshold-based | % of days above ₹50K, ₹1L, etc. |
| Concentration Normal | <30% | Low risk |
| Concentration Moderate | >30% | Review needed |
| Concentration High | **>50%** | Significant risk |
| Concentration Critical | **>70%** | Severe dependency |
| Primary Category | Most frequent or highest value | Per counterparty |
| Cash Flow Averaging | Simple averages | May use weighted in specific cases |
| Incomplete Data | Extrapolated | For <12 month statements |

---

## 6. IMPLEMENTATION NOTES

### Files to Modify
- `Feature Extraction/src/engines/cashflow.py` → Add Biz vs Non-Biz split, aggregation periods
- `Feature Extraction/src/engines/balance.py` → Add Daily Balance Change %, ABB, Available Balance Distribution, Balance Stability Score
- `Feature Extraction/src/engines/behaviour_engine.py` → Add counterparty concentration analysis
- `Feature Extraction/src/engines/rules_config.json` → Add:
  ```json
  "concentration_config": {
      "moderate_threshold_pct": 30,
      "high_threshold_pct": 50,
      "critical_threshold_pct": 70
  },
  "balance_distribution_thresholds": [50000, 100000, 200000, 500000, 1000000]
  ```
