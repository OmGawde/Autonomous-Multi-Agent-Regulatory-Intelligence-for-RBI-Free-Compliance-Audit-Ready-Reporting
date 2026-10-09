# Part 5: Loan, EMI, Repayment & Financial Discipline

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Debt engine, behaviour engine

---

## 1. LOAN DETECTION

### Disbursement Detection
- **Keywords**: `"disbursed"`, `"loan amount"`, `"credited"` in credit narrations
- Combined with known lender name → classified as Loan Disbursement

### Repayment/EMI Detection
- **Keywords**: `"EMI payment"`, `"loan repayment"`, `"installment"` in debit narrations
- Also: `"ECS/"`, `"NACH-DR-"` + lender name → Loan / EMI

### EMI Obligation Amount
- **Determined from**: First EMI debit amount recorded for that lender
- Subsequent EMIs compared against this baseline

### Bank/Lender Detection
- **Method**: Keywords in narration — e.g., `"HDFC"`, `"ICICI"`, `"BAJAJ FINANCE"`
- Matched against lender dictionary

### Active vs Inactive Status

| Status | Rule |
|---|---|
| **Active (Yes)** | EMIs are currently being debited (recurring debits found in recent months) |
| **Inactive (No)** | Only disbursement credit found, no recurring EMI debits |

---

## 2. EMI DISCIPLINE SCORE

### Formula

```
EMI Discipline Score = (On-time EMIs / Total Expected EMIs) × 100
```

### Bands

| Band | Score Range | Interpretation |
|---|---|---|
| Good | >90% | Excellent repayment discipline |
| Fair | 70–90% | Acceptable, minor misses |
| Poor | <70% | Concerning, multiple misses |

### Key Details
- **Bounce charges**: NOT directly included in EMI Discipline Score (separate metric)
- **Bounce charges affect**: Overall Precisa Score separately
- **Feeds into**: Precisa Score as a sub-component

### Implementation

```python
def calculate_emi_discipline(on_time_emis: int, total_expected_emis: int) -> dict:
    """
    Calculate EMI Discipline Score.
    """
    if total_expected_emis == 0:
        return {'score': 100, 'band': 'Good'}  # No EMIs = no misses
    
    score = (on_time_emis / total_expected_emis) * 100
    
    if score > 90:
        band = 'Good'
    elif score >= 70:
        band = 'Fair'
    else:
        band = 'Poor'
    
    return {
        'score': round(score, 2),
        'band': band,
        'on_time': on_time_emis,
        'expected': total_expected_emis,
        'missed': total_expected_emis - on_time_emis
    }
```

---

## 3. EMI BOUNCE DETECTION

### Detection Method
- EMI bounce = EMI payment fails due to insufficient funds
- Detected via return/bounce narrations following expected EMI date

### Keywords for EMI Return Charges

| Keyword | Detection |
|---|---|
| `"bounce charge"` | EMI bounce charge |
| `"return fee"` | Return fee charged |
| `"insufficient funds"` | Bounce reason |
| `"RETURNED"` | General return indicator |
| `"ECS/RETURN"` | ECS return (bounce) |
| `"NACH DR RETURN"` | NACH return (bounce) |

### Average Previous Day Balance
- **Calculation**: Average of EOD balances from the day BEFORE each EMI debit date
- **Purpose**: Shows whether the account had sufficient funds to cover EMI
- **Use**: If Avg Previous Day Balance < EMI amount → high bounce risk indicator

```python
def calculate_avg_prev_day_balance(emi_dates: list, daily_balances: dict) -> float:
    """
    Average balance from the day before each EMI debit.
    
    Args:
        emi_dates: List of dates when EMIs were debited
        daily_balances: Dict mapping date → EOD balance
    """
    prev_day_balances = []
    for emi_date in emi_dates:
        prev_day = emi_date - timedelta(days=1)
        if prev_day in daily_balances:
            prev_day_balances.append(daily_balances[prev_day])
    
    if not prev_day_balances:
        return 0
    return sum(prev_day_balances) / len(prev_day_balances)
```

---

## 4. CHEQUE BOUNCE ANALYSIS

### Bounce Percentage Formula

```
Cheque Bounce % = (Number of Bounced Cheques / Total Cheques Presented) × 100
```

- **Calculation basis**: By COUNT (not amount)
- **Red flag threshold**: **>10% bounce rate**

### Inward vs Outward Impact

| Type | Impact on Score | Reason |
|---|---|---|
| **Inward Bounce** | **Higher impact** (more weight) | Received cheques bouncing = cash flow issues, counterparty risk |
| **Outward Bounce** | Lower impact | Issued cheques bouncing = insufficient funds on your side |

- Exact multiplier varies but inward > outward in weight

### Recency Weighting

| Recency | Impact |
|---|---|
| Bounce within **last 3 months** | **Highest negative impact** |
| Bounce 3–6 months ago | Moderate impact |
| Bounce **6+ months ago** | **Lower impact** (decay over time) |

### Same Day Returns
- **Detection**: Cheque deposited and returned on the same calendar day
- **Significance**: Indicates immediate rejection, likely insufficient funds

### Implementation

```python
def analyze_cheque_bounces(transactions: list[dict]) -> dict:
    """
    Complete cheque bounce analysis.
    """
    from datetime import datetime, timedelta
    
    cheque_txns = [t for t in transactions if 'Cheque' in t.get('tags', [])]
    bounced = [t for t in transactions if 'Return' in t.get('tags', []) and 'Cheque' in t.get('tags', [])]
    
    # Separate inward vs outward
    inward_total = len([t for t in cheque_txns if t['type'] == 'credit'])
    outward_total = len([t for t in cheque_txns if t['type'] == 'debit'])
    inward_bounced = len([t for t in bounced if t['type'] == 'credit'])
    outward_bounced = len([t for t in bounced if t['type'] == 'debit'])
    
    total_cheques = inward_total + outward_total
    total_bounced = inward_bounced + outward_bounced
    
    bounce_rate = (total_bounced / total_cheques * 100) if total_cheques > 0 else 0
    red_flag = bounce_rate > 10  # >10% = red flag
    
    # Recency analysis
    today = max(t['date'] for t in transactions)
    recent_bounces = 0  # Within 3 months
    for b in bounced:
        months_ago = (today - b['date']).days / 30
        if months_ago <= 3:
            recent_bounces += 1
    
    # Same day returns
    same_day_returns = 0
    for b in bounced:
        deposited_same_day = any(
            t['date'] == b['date'] and t != b and 'Cheque' in t.get('tags', [])
            for t in cheque_txns
        )
        if deposited_same_day:
            same_day_returns += 1
    
    return {
        'total_cheques': total_cheques,
        'total_bounced': total_bounced,
        'bounce_rate_pct': round(bounce_rate, 2),
        'red_flag': red_flag,
        'inward_bounced': inward_bounced,
        'outward_bounced': outward_bounced,
        'recent_bounces_3m': recent_bounces,
        'same_day_returns': same_day_returns,
        'months_since_last_bounce': None  # Calculate from last bounce date
    }
```

---

## 5. RECURRING PAYMENT DETECTION

### Algorithm
- Uses transaction **frequency** and **consistency** in amounts
- Pattern matching on: same counterparty + similar amount + regular interval

### Tolerances

| Parameter | Tolerance | Example |
|---|---|---|
| **Date** | **±3 days** | Expected on 5th → accepted 2nd through 8th |
| **Amount** | **±5%** | Expected ₹10,000 → accepted ₹9,500 to ₹10,500 |
| **Minimum occurrences** | **2** | At least 2 payments to classify as recurring |

### Miss Detection
- **Rule**: Payment counted as "missed" only AFTER the date window passes
- **Example**: Expected on 5th, ±3 day window, no payment by 8th → counted as MISSED
- **Miss date**: Recorded as the expected payment date

### Scoring Impact
- Regular payments → **positive** influence on Precisa Score
- Missed payments → **negative** influence on Precisa Score

### Implementation

```python
from datetime import timedelta
from collections import defaultdict

def detect_recurring_payments(transactions: list[dict],
                               date_tolerance_days: int = 3,
                               amount_tolerance_pct: float = 0.05,
                               min_occurrences: int = 2) -> list[dict]:
    """
    Detect recurring payment patterns.
    
    Args:
        date_tolerance_days: ±3 days (default)
        amount_tolerance_pct: ±5% (default)
        min_occurrences: Minimum 2 to classify as recurring
    """
    # Group debits by counterparty
    counterparty_txns = defaultdict(list)
    for t in transactions:
        if t['type'] == 'debit' and t.get('counterparty'):
            counterparty_txns[t['counterparty']].append(t)
    
    recurring = []
    
    for counterparty, txns in counterparty_txns.items():
        if len(txns) < min_occurrences:
            continue
        
        # Sort by date
        txns.sort(key=lambda x: x['date'])
        
        # Check if amounts are consistent (±5%)
        amounts = [t['amount'] for t in txns]
        avg_amount = sum(amounts) / len(amounts)
        consistent_amount = all(
            abs(a - avg_amount) / avg_amount <= amount_tolerance_pct
            for a in amounts
        )
        
        if not consistent_amount:
            continue
        
        # Check if dates are roughly monthly (±3 days)
        intervals = []
        for i in range(1, len(txns)):
            gap = (txns[i]['date'] - txns[i-1]['date']).days
            intervals.append(gap)
        
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        is_monthly = 25 <= avg_interval <= 35  # ~30 days ±5
        
        if is_monthly and consistent_amount:
            # Calculate misses
            start_date = txns[0]['date']
            end_date = txns[-1]['date']
            expected_count = ((end_date - start_date).days // 30) + 1
            actual_count = len(txns)
            misses = max(0, expected_count - actual_count)
            
            recurring.append({
                'counterparty': counterparty,
                'start_date': start_date,
                'end_date': end_date,
                'amount': round(avg_amount, 2),
                'txn_count': actual_count,
                'interval': 'MONTHLY',
                'misses': misses,
                'regularity_pct': round((actual_count / expected_count) * 100, 2)
            })
    
    return recurring
```

---

## 6. PENALTY & CHARGES DETECTION

### Keywords

| Keyword | Charge Type |
|---|---|
| `"penalty"` | Penal charge |
| `"charge"` | Generic charge |
| `"fee"` | Service/transaction fee |
| `"service charge"` | Bank service charge |
| `"MIN BAL CHG"` | Minimum balance charge |
| `"PENAL CHARGES"` | Penal charge |
| `"bounce charge"` | Cheque/EMI bounce charge |
| `"return fee"` | Return/bounce fee |

### Interest Service Delay
- **Measurement**: Number of days a payment is delayed beyond the due date
- **Detection**: Compare expected EMI/payment date vs actual payment date
- **Impact**: Delays reduce Precisa Score

---

## 7. FINANCIAL DISCIPLINE SCORE

### Overview
- **Range**: 0–100
- **Feeds into**: Overall Precisa Score (sub-component)

### Parameters

| Parameter | Influence |
|---|---|
| Penalty charges count & amount | Higher penalties = lower score |
| Cheque bounce count & rate | More bounces = lower score |
| EMI misses | More misses = lower score |
| Bank charges | More charges = lower score |
| Interest service delays | Longer delays = lower score |
| EMI Discipline Score | Direct input |

### Estimated Formula

```python
def calculate_financial_discipline(
    emi_discipline_score: float,  # 0-100
    bounce_rate_pct: float,       # 0-100
    penalty_count: int,
    total_charges_amount: float,
    avg_monthly_balance: float,
    interest_delay_days: int
) -> float:
    """
    Estimated Financial Discipline Score (0-100).
    Higher = better discipline.
    """
    score = 100
    
    # EMI discipline (biggest factor)
    if emi_discipline_score < 70:
        score -= 30
    elif emi_discipline_score < 90:
        score -= 15
    
    # Bounce rate
    if bounce_rate_pct > 10:
        score -= 25  # Red flag
    elif bounce_rate_pct > 5:
        score -= 15
    elif bounce_rate_pct > 1:
        score -= 5
    
    # Penalty count
    score -= min(penalty_count * 3, 20)  # Max 20 point deduction
    
    # Charges relative to balance
    if avg_monthly_balance > 0:
        charges_ratio = total_charges_amount / avg_monthly_balance
        if charges_ratio > 0.05:  # Charges > 5% of balance
            score -= 10
    
    # Interest delay
    if interest_delay_days > 30:
        score -= 10
    elif interest_delay_days > 7:
        score -= 5
    
    return max(0, min(100, score))
```

---

## 8. KEY THRESHOLDS SUMMARY

| Parameter | Threshold | Notes |
|---|---|---|
| EMI Discipline Good | >90% | On-time / Expected × 100 |
| EMI Discipline Fair | 70–90% | — |
| EMI Discipline Poor | <70% | — |
| Cheque Bounce Red Flag | >10% by count | Count-based, not amount |
| Bounce Recency High Impact | Within 3 months | — |
| Bounce Recency Low Impact | 6+ months ago | Decay over time |
| Recurring Date Tolerance | **±3 days** | — |
| Recurring Amount Tolerance | **±5%** | — |
| Recurring Min Occurrences | **2** | — |
| Miss Detection | After date window passes | Expected + 3 days |
| Financial Discipline Score | 0–100 | Feeds into Precisa Score |
| Inward vs Outward Bounce | Inward > Outward weight | Exact multiplier varies |

---

## 9. IMPLEMENTATION NOTES

### Files to Modify
- `Feature Extraction/src/engines/debt_engine.py` → Add:
  - EMI Discipline Score calculation
  - Bounce charge keyword detection
  - Active vs Inactive EMI status logic
  - Financial Discipline Score
- `Feature Extraction/src/engines/behaviour_engine.py` → Add:
  - Cheque bounce analysis with recency weighting
  - Same day return detection
- `Feature Extraction/src/engines/rules_config.json` → Add:
  ```json
  "emi_discipline_config": {
      "good_threshold": 90,
      "fair_threshold": 70,
      "bounce_keywords": ["bounce charge", "return fee", "insufficient funds", "RETURNED", "ECS/RETURN", "NACH DR RETURN"],
      "penalty_keywords": ["penalty", "charge", "fee", "service charge", "MIN BAL CHG", "PENAL CHARGES"]
  },
  "recurring_config": {
      "date_tolerance_days": 3,
      "amount_tolerance_pct": 0.05,
      "min_occurrences": 2,
      "cadence_days_nominal": 30
  },
  "cheque_bounce_config": {
      "red_flag_threshold_pct": 10,
      "high_recency_months": 3,
      "low_recency_months": 6
  }
  ```

### Existing Pipeline Alignment
Our `debt_engine_config` already has:
- `amount_tolerance_percent: 2.0` → Precisa uses **5%** (we should increase)
- `date_tolerance_days: 5` → Precisa uses **3** (we should decrease)
- `min_emi_recurrence: 2` → Matches Precisa ✅
- `cadence_days_nominal: 30` → Matches Precisa ✅
