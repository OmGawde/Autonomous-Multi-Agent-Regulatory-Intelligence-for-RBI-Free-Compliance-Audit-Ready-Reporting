# Key Results — ICICI Bank Statement Analysis

| Metric / Key Result | Value | Details / Source |
| --- | --- | --- |
| Bank Name | ICICI | Inferred from statement file |
| Statement Period | 2025-04-01 to 2026-03-31 | Extracted transaction date range |
| Classification Accuracy | 99.7% deterministic | Tiers 1-2 without any ML model (251 bank rules, 47 keywords) |
| Salary Detected | ₹30.21L | via ACH rule / employer credit pattern |
| Total Income | ₹30.31L | 4 income sources detected |
| Total Expenses | ₹15.64L | Needs: ₹12.23L | Wants: ₹3.41L |
| Average Daily Balance (ADB) | ₹174,569.82 | Opening: ₹338,577.85 | Closing: ₹59,099.37 |
| Investments Found | Equity Trading, Mutual Funds / SIP, NPS, National Pension Scheme (NPS), PPF (₹5.84L total) | 5 investment categories identified |
| SIP Patterns | 8 detected | Recurring monthly debits on fixed dates |
| Long-Term Investment Score | 0.74 | Weighted score based on PPF/NPS/MF/FD allocations |
| Average Monthly Savings | ₹-23,289.87 | Positive savings in 5 months |
| Emergency Fund | 0.2 months coverage | 3-Mo target: ₹888,634.16 | 6-Mo target: ₹1,777,268.32 |
| Debt-to-Income Ratio (DTI) | 64.02% | 4 active loans, EMI: ₹161,694.00 |
| Behaviour Profile | Depleting Balance | Stability: 76.01 | Confidence: 0.76 |
