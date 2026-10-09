# Part 8: Scoring Framework, Credit Decisioning & Integration

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Underwriting decision engine, report summary generation, multi-account aggregator

---

## 1. CREDIT DECISIONING & POLICY CUTOFFS

### Recommendation Matrix

| Precisa Score Range | Risk Band | Default Recommendation | Underwriting Action |
|---|---|---|---|
| **800 – 1000** | Very Low Risk | **Approve (Fast-Track)** | Instant approval, best pricing/terms |
| **650 – 799** | Low Risk | **Approve / Minor Review** | Standard approval (Sample score: 744) |
| **500 – 649** | Moderate Risk | **Manual Review** | Underwriter inspection, request collateral/guarantor |
| **300 – 499** | High Risk | **Reject** | High default probability |
| **0 – 299** | Very High Risk | **Reject (Auto-Decline)** | Critical irregularities / high AML risk |

### Policy Customization
- The decisioning engine allows lenders to set custom cutoffs per lending product (e.g., Unsecured Personal Loan requires >750, Secured Business Loan accepts >600).

---

## 2. STATEMENT PERIOD SUFFICIENCY & CONFIDENCE

### Data Sufficiency Rules

| Statement Duration | Reliability Level | System Action |
|---|---|---|
| **6 to 12+ Months** | **High (Optimal)** | Standard analysis with full confidence score (100%) |
| **3 to 5 Months** | **Medium (Partial)** | Generates score + raises **"Data Sufficiency Warning"** flag |
| **< 3 Months** | **Low (Insufficient)** | Score generated marked as low confidence / requires supplementary docs |

### Missing & Inactive Periods
- **Missing Months**: If a month has no data in a contiguous period (e.g., Jan, Feb, [Gap], Apr), triggers a continuity integrity flag.
- **Dormant Periods**: Account with no transactions for >30 consecutive days is flagged under AML / Inactivity tracking.

---

## 3. TREND & TRAJECTORY INDICATORS

### Trajectory Flagging

The system outputs a high-level trajectory flag on cash flow and average monthly balance (AMB):

| Trajectory Flag | Condition | Impact on Scoring |
|---|---|---|
| **Positive / Improving** | AMB and Net Cash Flow increasing over last 3–6 months | Score boost (+10 to +25 pts) |
| **Stable** | Balances and inflows within ±10% variance | Neutral |
| **Negative / Deteriorating** | AMB declining consistently or Net Cash Flow negative for 2+ consecutive months | Penalty deduction (-15 to -35 pts) |

### Month-over-Month Trend Algorithm

```python
def calculate_trend_trajectory(monthly_metrics: list[dict]) -> dict:
    """
    Compute trajectory based on last 3-6 months AMB and Net Cash Flow.
    
    Each item in monthly_metrics: {'month': str, 'amb': float, 'net_cash_flow': float}
    """
    if len(monthly_metrics) < 3:
        return {'trajectory': 'STABLE', 'confidence': 'LOW'}
    
    amb_values = [m['amb'] for m in monthly_metrics]
    net_cf_values = [m['net_cash_flow'] for m in monthly_metrics]
    
    # Calculate simple slope / direction for AMB
    recent_amb = amb_values[-1]
    baseline_amb = amb_values[0]
    amb_growth = (recent_amb - baseline_amb) / baseline_amb if baseline_amb > 0 else 0
    
    # Check consecutive negative cash flow
    recent_cf_negative = sum(1 for cf in net_cf_values[-2:] if cf < 0)
    
    if amb_growth > 0.15 and recent_cf_negative == 0:
        trajectory = 'POSITIVE'
    elif amb_growth < -0.15 or recent_cf_negative >= 2:
        trajectory = 'NEGATIVE'
    else:
        trajectory = 'STABLE'
        
    return {
        'trajectory': trajectory,
        'amb_growth_pct': round(amb_growth * 100, 2),
        'recent_negative_cf_months': recent_cf_negative
    }
```

---

## 4. MULTI-ACCOUNT CONSOLIDATION & ELIMINATION

### Inter-Bank Elimination
- When multiple bank accounts are analyzed for the same entity:
  1. Detect all cross-account self-transfers (matches: Same Amount + Opposite Direction + Same/±1 Day).
  2. **Eliminate** these from Total Inflow and Total Outflow to prevent artificial inflation of business turnover.
  3. Aggregate remaining true commercial transactions to compute the **Consolidated Precisa Score**.

---

## 5. COMPLETE BSA INTEGRATION ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                      PDF STATEMENT(S)                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
               [PDF Parsing & Authenticity Check]
               • Font Check & Producer Validation (Part 3)
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              TRANSACTION CLASSIFICATION ENGINE              │
│  • Priority 1: Entity / Counterparty Match (Part 2)         │
│  • Priority 2: Payment Rail Regex (NEFT/RTGS/UPI) (Part 2)  │
│  • Priority 3: Additive Tagging (Loan, EMI, NACH) (Part 2)  │
└──────────────────────────────┬──────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
┌──────────────┐       ┌──────────────┐        ┌──────────────┐
│ CORE SCORES  │       │  IRREGULARITY│        │  AML & DEBT  │
│  (Part 1)    │       │   (Part 3)   │        │ (Part 4,5,7) │
│ • Volatility │       │ • 16 Rules   │        │ • AML Score  │
│ • FOIR Score │       │ • 4 Severity │        │ • OD/CC Util │
│ • Avg Bal    │       │   Levels     │        │ • Net Turnov │
└──────┬───────┘       └───────┬──────┘        └──────┬───────┘
       │                       │                      │
       └───────────────────────┼──────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  COMPOSITE PRECISA SCORE                    │
│                        (0 – 1000)                           │
│  • 800 - 1000: Very Low Risk (Approve)                      │
│  • 650 - 799 : Low Risk (Approve / Review)                  │
│  • 500 - 649 : Moderate Risk (Manual Review)                │
│  • 300 - 499 : High Risk (Reject)                           │
│  • 0   - 299 : Very High Risk (Decline)                     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 UNDERWRITING & SUMMARY                      │
│  • Trajectory Flag: POSITIVE / STABLE / NEGATIVE            │
│  • Data Sufficiency: 6–12m (Optimal) vs 3m (Warning)        │
│  • True Turnover (Net Credits)                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. COMPLETE REPOSITORY INDEX

All components and formulas from the Precisa BSA report are documented across the 8 parts:

1. **[Part_1_Core_Scores.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_1_Core_Scores.md)**: Precisa Score (0–1000), Volatility (0–1), FOIR calculation, EMI regularity.
2. **[Part_2_Categorization_Tags.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_2_Categorization_Tags.md)**: 390+ Bank patterns, Priority ordering, Multi-tagging, Counterparty matching.
3. **[Part_3_Irregularity_Fraud.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_3_Irregularity_Fraud.md)**: 16 Financial Irregularities, 2% mismatch rule, 4 Severity levels, Point penalties.
4. **[Part_4_AML_Circular.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_4_AML_Circular.md)**: AML Score (0–100), Circular txns (1–3 days, ±5%), Inter-bank matching.
5. **[Part_5_Loan_EMI_Repayment.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_5_Loan_EMI_Repayment.md)**: Loan detection, EMI discipline (>90% good), Cheque bounces (>10% red flag).
6. **[Part_6_CashFlow_Balance.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_6_CashFlow_Balance.md)**: Biz vs Non-Biz cash flows, Day-over-day balance change %, Concentration bands.
7. **[Part_7_Specialized_Modules.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_7_Specialized_Modules.md)**: OD/CC utilization (<30% healthy, >50% risky), Salary consistency, Net Turnover.
8. **[Part_8_Framework_Decisioning.md](file:///c:/Users/9c23o/TIH%20MAIN%20WEB/Precisa_Analysis_Formulas/Part_8_Framework_Decisioning.md)**: Credit decision bands, Trajectory algorithms, Data sufficiency rules.
