# Part 4: AML Analysis, Circular Transactions & Inter-Bank Transfers

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: AML risk engine, circular transaction detection, inter-bank transfer matching

---

## 1. AML RISK SCORE

### Overview
- **Range**: 0–100
- **Sample report value**: 50 → Moderate Risk
- **Parameters**: Daily avg balance, Max/Min balance gap, Days gap between Max & Min, Transaction count, Max dormant days
- **Direction**: Higher transaction counts + larger balance gaps → higher risk score

### Risk Bands

| Band | Score Range | Interpretation |
|---|---|---|
| Low | 0–25 | Minimal AML concerns |
| Moderate | 26–50 | Some suspicious patterns, review recommended |
| High | 51–75 | Significant AML risk indicators |
| Critical | 76–100 | Severe AML risk, escalate immediately |

### Input Parameters

| Parameter | Influence on Score | Notes |
|---|---|---|
| Daily Average Balance | Baseline context | Lower balance + high txn volume = suspicious |
| Max Balance vs Min Balance Gap | Higher gap = higher risk | Large swings indicate potential money movement |
| Days Gap between Max & Min | Shorter gap = higher risk | Rapid balance changes = suspicious |
| Transaction Count | Higher count = higher risk | Many transactions relative to balance |
| Max Dormant Days | Longer dormancy = risk indicator | Sudden activity after dormancy |
| Suspicious Activity Count | Direct increase | Each suspicious activity adds to score |

---

## 2. SUSPICIOUS ACTIVITY DETECTION RULES

### Thresholds

| # | Suspicious Activity | Threshold / Rule | Detection Logic |
|---|---|---|---|
| 1 | **Big deposit followed by withdrawal (same/next day)** | "Big" = **>₹50,000** OR **>20% of average balance** | Credit > threshold, then debit within 0–1 days |
| 2 | **Multiple deposits → big withdrawal (same/next day)** | "Multiple" = **≥2 deposits**; "Big withdrawal" = **>₹50,000** | 2+ credits in a day, then large debit same/next day |
| 3 | **Multiple Cash/ATM deposits same day** | "Multiple" = **≥2 deposits on same day** | Count cash deposits per day ≥ 2 |
| 4 | **High value spending** | **>₹50,000** OR **>10% of average balance** | Single debit exceeding threshold |
| 5 | **International wire transfers** | Keywords: `"wire"`, `"international"` in narration | Narration text search |

### Implementation

```python
def check_big_deposit_withdrawal(transactions: list[dict], avg_balance: float) -> list[dict]:
    """
    Detect big deposit followed by withdrawal on same or next day.
    Big = >₹50,000 OR >20% of average balance
    """
    flags = []
    big_threshold = max(50000, avg_balance * 0.20)
    
    credits = [t for t in transactions if t['type'] == 'credit' and t['amount'] > big_threshold]
    
    for credit in credits:
        # Find debits on same day or next day
        for txn in transactions:
            if txn['type'] == 'debit':
                days_diff = (txn['date'] - credit['date']).days
                if 0 <= days_diff <= 1:
                    flags.append({
                        'type': 'BIG_DEPOSIT_WITHDRAWAL',
                        'deposit_date': credit['date'],
                        'deposit_amount': credit['amount'],
                        'withdrawal_date': txn['date'],
                        'withdrawal_amount': txn['amount']
                    })
    return flags


def check_multiple_deposits_big_withdrawal(transactions: list[dict]) -> list[dict]:
    """
    Multiple deposits (≥2) followed by big withdrawal (>₹50,000) same/next day.
    """
    from collections import defaultdict
    flags = []
    
    # Group credits by date
    credits_by_date = defaultdict(list)
    for t in transactions:
        if t['type'] == 'credit':
            credits_by_date[t['date']].append(t)
    
    # Check dates with 2+ deposits
    for date, credits in credits_by_date.items():
        if len(credits) >= 2:
            total_deposited = sum(c['amount'] for c in credits)
            # Check for big withdrawal same/next day
            for txn in transactions:
                if txn['type'] == 'debit' and txn['amount'] > 50000:
                    days_diff = (txn['date'] - date).days
                    if 0 <= days_diff <= 1:
                        flags.append({
                            'type': 'MULTIPLE_DEPOSITS_BIG_WITHDRAWAL',
                            'deposit_date': date,
                            'deposit_count': len(credits),
                            'total_deposited': total_deposited,
                            'withdrawal_amount': txn['amount']
                        })
    return flags


def check_multiple_cash_deposits_same_day(transactions: list[dict]) -> list[dict]:
    """
    Flag ≥2 cash/ATM deposits on the same day.
    """
    from collections import defaultdict
    flags = []
    
    cash_by_date = defaultdict(list)
    for t in transactions:
        if t['type'] == 'credit' and 'Cash' in t.get('tags', []):
            cash_by_date[t['date']].append(t)
    
    for date, deposits in cash_by_date.items():
        if len(deposits) >= 2:
            flags.append({
                'type': 'MULTIPLE_CASH_DEPOSITS_SAME_DAY',
                'date': date,
                'count': len(deposits),
                'total_amount': sum(d['amount'] for d in deposits)
            })
    return flags


def check_high_value_spending(transactions: list[dict], avg_balance: float) -> list[dict]:
    """
    Flag single debits >₹50,000 OR >10% of average balance.
    """
    flags = []
    threshold = max(50000, avg_balance * 0.10)
    
    for txn in transactions:
        if txn['type'] == 'debit' and txn['amount'] > threshold:
            flags.append({
                'type': 'HIGH_VALUE_SPENDING',
                'date': txn['date'],
                'amount': txn['amount'],
                'pct_of_avg_balance': (txn['amount'] / avg_balance * 100) if avg_balance > 0 else 0
            })
    return flags


def check_international_transfers(transactions: list[dict]) -> list[dict]:
    """
    Detect international wire transfers via narration keywords.
    """
    keywords = ['WIRE', 'INTERNATIONAL', 'FOREIGN', 'SWIFT', 'FOREX']
    flags = []
    
    for txn in transactions:
        narration = txn.get('description', '').upper()
        if any(kw in narration for kw in keywords):
            flags.append({
                'type': 'INTERNATIONAL_WIRE',
                'date': txn['date'],
                'amount': txn['amount'],
                'narration': txn['description']
            })
    return flags
```

---

## 3. CIRCULAR TRANSACTION DETECTION

### Rules

| Parameter | Value |
|---|---|
| Definition | A→B then B→A within time window |
| Time window | **1–3 days** |
| Amount tolerance | **Exact match OR ±5%** |
| Multi-hop detection | **Yes** — detects A→B→C→A patterns |
| Red flag threshold | **≥2 instances** trigger a flag |

### Implementation

```python
def detect_circular_transactions(transactions: list[dict], 
                                  time_window_days: int = 3,
                                  amount_tolerance_pct: float = 0.05) -> list[dict]:
    """
    Detect circular transactions: A sends to B, B sends back to A within time window.
    
    Args:
        time_window_days: Max days between outflow and return inflow (default: 3)
        amount_tolerance_pct: Amount match tolerance (default: 5%)
    """
    flags = []
    debits = [t for t in transactions if t['type'] == 'debit']
    credits = [t for t in transactions if t['type'] == 'credit']
    
    for debit in debits:
        counterparty = debit.get('counterparty', '')
        if not counterparty:
            continue
        
        debit_amount = debit['amount']
        min_amount = debit_amount * (1 - amount_tolerance_pct)
        max_amount = debit_amount * (1 + amount_tolerance_pct)
        
        # Look for matching credit from same counterparty within time window
        for credit in credits:
            if credit.get('counterparty', '') == counterparty:
                days_diff = (credit['date'] - debit['date']).days
                if 0 <= days_diff <= time_window_days:
                    if min_amount <= credit['amount'] <= max_amount:
                        flags.append({
                            'type': 'CIRCULAR_TRANSACTION',
                            'counterparty': counterparty,
                            'outflow_date': debit['date'],
                            'outflow_amount': debit_amount,
                            'return_date': credit['date'],
                            'return_amount': credit['amount'],
                            'days_gap': days_diff,
                            'amount_diff_pct': abs(credit['amount'] - debit_amount) / debit_amount * 100
                        })
    
    # Red flag if 2+ circular instances detected
    return flags  # Flag if len(flags) >= 2


def detect_multi_hop_circular(transactions: list[dict],
                               time_window_days: int = 3,
                               amount_tolerance_pct: float = 0.05) -> list[dict]:
    """
    Detect multi-hop circular flows: A→B→C→A
    Requires counterparty chain tracking.
    """
    flags = []
    debits = sorted([t for t in transactions if t['type'] == 'debit'], key=lambda x: x['date'])
    credits = sorted([t for t in transactions if t['type'] == 'credit'], key=lambda x: x['date'])
    
    # Build outflow chain
    for debit in debits:
        counterparty_b = debit.get('counterparty', '')
        debit_amount = debit['amount']
        min_amt = debit_amount * (1 - amount_tolerance_pct)
        max_amt = debit_amount * (1 + amount_tolerance_pct)
        
        # Look for credit from DIFFERENT counterparty (C) with similar amount
        for credit in credits:
            counterparty_c = credit.get('counterparty', '')
            if counterparty_c and counterparty_c != counterparty_b:
                days_diff = (credit['date'] - debit['date']).days
                if 0 <= days_diff <= time_window_days:
                    if min_amt <= credit['amount'] <= max_amt:
                        flags.append({
                            'type': 'MULTI_HOP_CIRCULAR',
                            'chain': f"Self → {counterparty_b} → {counterparty_c} → Self",
                            'amount': debit_amount,
                            'start_date': debit['date'],
                            'return_date': credit['date']
                        })
    return flags
```

---

## 4. INTER-BANK TRANSFER DETECTION

### Matching Rules

| Parameter | Value |
|---|---|
| Matching criteria | Same amount + same date + opposite direction |
| Date tolerance | **Same day OR ±1 day** |
| Cash flow treatment | **Excluded** from business cash flow calculations |
| Velocity metric | **Yes** — frequency of transfers between accounts assessed |

### Implementation

```python
def detect_inter_bank_transfers(account_a_txns: list[dict], 
                                 account_b_txns: list[dict],
                                 date_tolerance_days: int = 1) -> list[dict]:
    """
    Match transfers between two accounts of the same entity.
    Criteria: Same amount + same/±1 day + opposite direction
    """
    matches = []
    
    a_debits = [t for t in account_a_txns if t['type'] == 'debit']
    b_credits = [t for t in account_b_txns if t['type'] == 'credit']
    
    for debit in a_debits:
        for credit in b_credits:
            # Amount match (exact)
            if debit['amount'] == credit['amount']:
                # Date match (±1 day)
                days_diff = abs((credit['date'] - debit['date']).days)
                if days_diff <= date_tolerance_days:
                    matches.append({
                        'type': 'INTER_BANK_TRANSFER',
                        'from_account': 'A',
                        'to_account': 'B',
                        'amount': debit['amount'],
                        'debit_date': debit['date'],
                        'credit_date': credit['date'],
                        'days_gap': days_diff
                    })
    
    # Also check B→A direction
    b_debits = [t for t in account_b_txns if t['type'] == 'debit']
    a_credits = [t for t in account_a_txns if t['type'] == 'credit']
    
    for debit in b_debits:
        for credit in a_credits:
            if debit['amount'] == credit['amount']:
                days_diff = abs((credit['date'] - debit['date']).days)
                if days_diff <= date_tolerance_days:
                    matches.append({
                        'type': 'INTER_BANK_TRANSFER',
                        'from_account': 'B',
                        'to_account': 'A',
                        'amount': debit['amount'],
                        'debit_date': debit['date'],
                        'credit_date': credit['date'],
                        'days_gap': days_diff
                    })
    
    return matches


def calculate_transfer_velocity(inter_bank_transfers: list[dict], 
                                 statement_days: int) -> float:
    """
    Calculate inter-bank transfer velocity.
    Higher velocity = more frequent transfers = potential flag.
    """
    if statement_days == 0:
        return 0
    return len(inter_bank_transfers) / statement_days  # Transfers per day
```

### Cash Flow Exclusion

```python
def exclude_inter_bank_from_cashflow(transactions: list[dict], 
                                      inter_bank_ids: set) -> list[dict]:
    """
    Exclude identified inter-bank transfers from cash flow calculations
    to avoid double-counting / inflating volumes.
    """
    return [t for t in transactions if t.get('id') not in inter_bank_ids]
```

---

## 5. AML RISK SCORE CALCULATION (Estimated)

```python
def calculate_aml_risk_score(
    daily_avg_balance: float,
    max_balance: float,
    min_balance: float,
    days_between_max_min: int,
    total_txn_count: int,
    max_dormant_days: int,
    suspicious_activity_count: int
) -> int:
    """
    Estimated AML risk score calculation (0-100).
    Actual Precisa formula is proprietary — this is an approximation
    based on confirmed parameters and their directional influence.
    """
    score = 0
    
    # Balance gap risk (larger gap = higher risk)
    if daily_avg_balance > 0:
        balance_gap_ratio = (max_balance - min_balance) / daily_avg_balance
        if balance_gap_ratio > 5:
            score += 20
        elif balance_gap_ratio > 3:
            score += 15
        elif balance_gap_ratio > 1:
            score += 10
    
    # Days between max and min (shorter = more suspicious)
    if days_between_max_min <= 3:
        score += 15
    elif days_between_max_min <= 7:
        score += 10
    elif days_between_max_min <= 14:
        score += 5
    
    # Transaction frequency (high count relative to balance)
    if daily_avg_balance > 0:
        txn_intensity = total_txn_count / (daily_avg_balance / 10000)
        if txn_intensity > 10:
            score += 15
        elif txn_intensity > 5:
            score += 10
    
    # Dormancy (sudden activity after dormancy)
    if max_dormant_days > 30:
        score += 10
    elif max_dormant_days > 15:
        score += 5
    
    # Suspicious activities (direct addition)
    score += suspicious_activity_count * 5
    
    return min(score, 100)
```

---

## 6. KEY THRESHOLDS SUMMARY

| Parameter | Threshold | Notes |
|---|---|---|
| AML Score Range | 0–100 | 4 bands: Low/Moderate/High/Critical |
| "Big" deposit/withdrawal | >₹50,000 OR >20% avg balance | Whichever is larger |
| "High value" spending | >₹50,000 OR >10% avg balance | Whichever is larger |
| "Multiple" deposits | ≥2 deposits | On same day |
| International keywords | "WIRE", "INTERNATIONAL" | Narration search |
| Circular time window | 1–3 days | Between outflow and return |
| Circular amount tolerance | ±5% | Or exact match |
| Circular red flag threshold | ≥2 instances | Less than 2 = monitor |
| Multi-hop detection | Yes | A→B→C→A chains |
| Inter-bank date tolerance | ±1 day | Same day or next day |
| Inter-bank matching | Exact amount + date | Opposite direction |
| Structuring | Small txns aggregating to large | Pattern-based detection |
| FATF/RBI mapped | Yes | Guidelines directly mapped |

---

## 7. IMPLEMENTATION NOTES

### Files to Modify
- `Feature Extraction/src/engines/fraud_engine.py` → Add AML suspicious activity checks
- `Feature Extraction/src/engines/rules_config.json` → Add AML thresholds:
  ```json
  "aml_config": {
      "big_deposit_threshold": 50000,
      "big_deposit_pct_avg_balance": 0.20,
      "high_value_spending_threshold": 50000,
      "high_value_spending_pct_avg_balance": 0.10,
      "multiple_deposit_min_count": 2,
      "circular_time_window_days": 3,
      "circular_amount_tolerance_pct": 0.05,
      "circular_red_flag_min_instances": 2,
      "interbank_date_tolerance_days": 1,
      "international_keywords": ["WIRE", "INTERNATIONAL", "FOREIGN", "SWIFT", "FOREX"]
  }
  ```

### Integration with Existing Fraud Engine
Our current `fraud_engine_config` already has:
- `rapid_transfer_window_hours: 2.0` → Related to "big deposit then withdrawal" (extend to 24 hours)
- `rapid_transfer_threshold_ratio: 0.85` → Similar concept, different threshold
- `structuring_min_amount: 45000` → Maps to ₹40-50K AML check
- `suspicious_score_weights` → Already has a scoring framework

### What's New to Add
1. AML Risk Score (0-100) as separate metric
2. Big deposit → withdrawal detection (₹50K / 20% avg balance)
3. Multiple deposits → big withdrawal detection
4. Multiple cash deposits same day
5. High value spending detection (₹50K / 10% avg balance)
6. International wire transfer keyword detection
7. Circular transaction detection (1-3 day window, ±5%)
8. Multi-hop circular detection (A→B→C→A)
9. Inter-bank transfer matching (multi-account)
10. Transfer velocity metric
