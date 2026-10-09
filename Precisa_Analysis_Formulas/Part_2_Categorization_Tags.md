# Part 2: Transaction Categorization, Tags & Counterparty Extraction

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: Transaction classification engine

---

## 1. CLASSIFICATION APPROACH

### Method
- **Hybrid system**: NLP + Rule-based + Machine Learning
- **Confidence scoring**: Each categorization has a confidence % (threshold: 70–80%)
- **Below threshold**: Transaction flagged for manual review or assigned default category
- **Bank support**: 390+ Indian banks with bank-specific narration parsing rules

### Classification Priority Order

```
Priority 1: Counterparty/Entity match (lender, insurer, business name)
    ↓ OVERRIDES
Priority 2: Payment rail/mode match (NEFT, RTGS, UPI, IMPS prefix)
    ↓ OVERRIDES
Priority 3: Default/Miscellaneous category
```

**Key rule**: Entity identification OVERRIDES rail identification. Example:
- `"RTGS/XXXX/BAJAJ FINANCE"` → **Loan / EMI** (not "O/W Funds Transfer / RTGS")
- `"RTGS/XXXX/VGUARD INDUSTRIES"` → **Sales & Marketing** (not "O/W Funds Transfer / RTGS")
- `"NEFT/XXXX/RANDOM PERSON"` → **O/W Funds Transfer / NEFT** (no entity match, rail wins)

### Credit/Debit Direction Rule
- Same lender name in **credit** = Loan disbursement (category: "Loan")
- Same lender name in **debit** = Loan repayment (category: "Loan / EMI")
- `"By Clg"` = Inward cheque (credit)
- `"TO Clg"` = Outward cheque (debit)

---

## 2. CATEGORY TAXONOMY

### Hierarchy Structure
- **First level**: Can be rail/mode-based OR purpose-based (flexible)
  - Rail-based: "I/W Funds Transfer", "O/W Funds Transfer", "Cash & ATM"
  - Purpose-based: "Loan / EMI", "Sales & Marketing", "Insurance", "Salary"
- **Second level**: Instrument/sub-type (e.g., "/ NEFT", "/ UPI", "/ Cheque")

### Complete Observed Categories

**Inflow Categories:**
| Category | Trigger |
|---|---|
| Salary | "SALARY", "SAL", "PAYROLL" keywords OR regularity + same counterparty |
| Loan | Lender name in credit narration (disbursement) |
| I/W Funds Transfer / Cheque | "By Clg" |
| I/W Funds Transfer / NACH | "NACH-CR-" prefix |
| I/W Funds Transfer / UPI | "UPI/" prefix in credit |
| I/W Funds Transfer / NEFT | "NEFT" in credit narration |
| I/W Funds Transfer / Third Party Transfer | Third party credit transfer |
| Internal Transfer | Account holder's own name as sender |
| Cash & ATM / Cash Deposit | Cash deposit narration |
| O/W Funds Transfer Return / Cheque Return | "ECS/RETURN", "NACH DR RETURN" |

**Outflow Categories:**
| Category | Trigger |
|---|---|
| Loan / EMI | Lender name in debit (ECS, NACH, known lender) |
| Insurance | "LIC", insurer name (overrides ACH/NACH rail) |
| Tax Paid | "INTERNET TAX PAYMENT" phrase |
| Salary (rare — employer paying out) | Context-dependent |
| O/W Funds Transfer / NEFT | "NEFT/" prefix, no entity override |
| O/W Funds Transfer / RTGS | "RTGS/" prefix, no entity override |
| O/W Funds Transfer / IMPS | "IMPS/" prefix |
| O/W Funds Transfer / UPI | "UPI/" prefix in debit |
| O/W Funds Transfer / Cheque | "TO Clg" |
| O/W Funds Transfer / INFT | "INB/IFT/" prefix |
| O/W Funds Transfer / Third Party Transfer | "IFT" keyword (interbank funds transfer) |
| Sales & Marketing | Business entity counterparty (e.g., VGUARD) |
| Interest | "INT PAID", "INTEREST DEBIT" |
| Charges & Fees / Bank Charges | "MIN BAL CHG", "SERVICE CHARGES" |
| Charges & Fees / Penal Charges | "PENAL CHARGES" |
| ECOM & Wallet Payments | E-commerce/wallet transactions |
| Entertainment | Entertainment-related merchants |
| Office Expenses | Office-related expenses |
| Cash & ATM withdrawals / ATM | "ATM" keyword |
| Cash & ATM / ATM Deposit | ATM deposit narration |
| I/W Funds Transfer Return / Cheque Return | Outward cheque bounce |
| Miscellaneous / Uncategorized | Unrecognizable narrations (e.g., "MISC DR") |

**Additional categories likely in taxonomy (confirmed to exist):**
- Rent, Grocery, Utilities, Telecom, Healthcare, Travel
- Food Delivery, Government/Subsidy, Refund
- Dividend, Mutual Fund, FD/RD

---

## 3. NARRATION KEYWORD RULES

### Payment Rail Detection (Prefix-based)

| Keyword/Pattern | Category | Notes |
|---|---|---|
| `"NEFT/"` or `"NEFT-"` or contains `"NEFT"` | O/W Funds Transfer / NEFT | Caught anywhere in narration |
| `"RTGS/"` | O/W Funds Transfer / RTGS | Unless entity overrides |
| `"IMPS/"` | O/W Funds Transfer / IMPS | — |
| `"UPI/"` or `"UPI-"` | UPI transfer | Bank-specific prefixes vary |
| `"ECS/"` | Electronic Clearing | Usually maps to Loan/EMI |
| `"NACH-DR-"` | NACH Debit | Usually maps to Loan/EMI |
| `"ECS/DR"` | Same as NACH-DR | Older format, treated identically |
| `"INB/IFT/"` | Third Party Transfer | IFT = Interbank Funds Transfer |
| `"ACH Debit"` | Auto-debit | Entity determines sub-category |
| `"By Clg"` | Inward Cheque | Credit direction |
| `"TO Clg"` | Outward Cheque | Debit direction |
| `"CLG/"` | Cheque (clearing) | — |
| `"CHEQUE DEPOSIT"` | Cheque Deposit | — |
| `"ATM"` | ATM transaction | Cash withdrawal/deposit |

### Entity/Purpose Detection (Counterparty-based)

| Keyword/Pattern | Category | Notes |
|---|---|---|
| Known lender name (BAJAJ FINANCE, HDFC, etc.) | Loan / EMI | Overrides rail |
| `"LIC"` or insurer name | Insurance | Overrides ACH/NACH rail |
| Known business entity | Sales & Marketing | Overrides RTGS/NEFT rail |
| `"SALARY"`, `"SAL"`, `"PAYROLL"` | Salary | Direct keyword match |
| `"INTERNET TAX PAYMENT"` | Tax Paid | Full phrase match |
| `"INT PAID"`, `"INTEREST DEBIT"` | Interest | — |
| `"MIN BAL CHG"`, `"SERVICE CHARGES"` | Charges & Fees / Bank Charges | — |
| `"PENAL CHARGES"` | Charges & Fees / Penal Charges | — |
| `"ECS/RETURN"`, `"NACH DR RETURN"` | Return / Cheque Return | Bounce/return transaction |

### Salary Detection (Without Keyword)
When narration does NOT contain "SALARY"/"SAL"/"PAYROLL":
1. Regular recurring credit (monthly interval)
2. Consistent amount (same or very similar each month)
3. Same counterparty (company/employer name)
4. All three conditions met → classified as Salary

---

## 4. BANK-SPECIFIC NARRATION PATTERNS

### HDFC Bank

| Transaction Type | Narration Format(s) | Regex Pattern |
|---|---|---|
| UPI Debit | `"UPI/123456789/NAME/HDFC"` | `^UPI/` |
| UPI Credit | Same format, credit direction | `^UPI/` |
| NEFT | `"NEFT/XXXX/BENEFICIARY"` | `^NEFT/` or contains `NEFT` |
| IMPS | `"IMPS/XXXX/BENEFICIARY"` or `"MMT/IMPS/XXXX"` | `IMPS/` or `^MMT/IMPS/` |
| Cheque In | `"By Clg"` or `"CLG/XXXX"` | `By Clg` or `^CLG/` |
| Cheque Out | `"TO Clg"` | `TO Clg` |
| Salary | `"SALARY"` keyword or employer NEFT | `SALARY` or regularity detection |
| EMI/Loan | `"ECS/LENDER"` or `"NACH-DR-LENDER"` | `^ECS/` or `^NACH-DR-` |
| Cash Withdrawal | `"ATM-CASH/XXXX"` or `"ATM WDL/XXXX"` | `ATM` |
| Cash Deposit | Cash deposit narration | `CASH DEP` or `BY CASH` |
| Internal Transfer | `"FT/XXXX"` or `"IFT/XXXX"` | `^FT/` or `^IFT/` |

### SBI (State Bank of India)

| Transaction Type | Narration Format(s) | Regex Pattern |
|---|---|---|
| UPI Debit | `"TO TRANSFER-UPI/DR/XXXX/NAME"` | `TO TRANSFER-UPI/` |
| UPI Credit | `"BY TRANSFER-UPI/CR/XXXX/NAME"` | `BY TRANSFER-UPI/` |
| NEFT Debit | `"TO TRANSFER-NEFT/XXXX"` | `TO TRANSFER-NEFT/` or `NEFT` |
| NEFT Credit | `"BY TRANSFER-NEFT/XXXX"` | `BY TRANSFER-NEFT/` or `NEFT` |
| IMPS | `"TO TRANSFER-IMPS/XXXX"` | `TO TRANSFER-IMPS/` |
| Cheque In | `"BY CLG"` | `BY CLG` |
| Cheque Out | `"TO CLG"` | `TO CLG` |
| Salary | `"BY TRANSFER-SALARY"` or `"SALARY/XXXX"` | `SALARY` |
| ECS/NACH | `"ECS/XXXX"` or `"NACH/XXXX"` | `^ECS/` or `^NACH` |
| Cash Deposit | `"BY CASH"` | `BY CASH` |
| Cash Withdrawal | `"TO ATM"` | `TO ATM` |

**SBI unique**: Prefixes all transfers with `"TO TRANSFER-"` (debit) and `"BY TRANSFER-"` (credit).

### ICICI Bank

| Transaction Type | Narration Format(s) | Regex Pattern |
|---|---|---|
| UPI P2P | `"UPI/P2P/XXXX/VPA"` | `UPI/P2P/` |
| UPI P2M | `"UPI/P2M/XXXX/VPA"` | `UPI/P2M/` |
| NEFT | `"NEFT-XXXX-NAME-IFSC"` (dash-separated) | `^NEFT-` or contains `NEFT` |
| IMPS | `"IMPS/XXXX"` | `^IMPS/` |
| Cheque | `"CLG/XXXX"` or `"CHEQUE DEPOSIT"` | `CLG/` or `CHEQUE` |
| Salary | `"SALARY"` or employer name | `SALARY` or regularity |
| ECS/NACH | Standard `"ECS/"` / `"NACH-"` formats | `^ECS/` or `^NACH` |

**ICICI unique**: Includes `P2P`/`P2M` flag directly in UPI narration. NEFT uses dashes instead of slashes.

### Axis Bank

| Transaction Type | Narration Format(s) | Regex Pattern |
|---|---|---|
| UPI | `"UPI/P2M/XXXX/VPA"` | `^UPI/` — includes P2M flag |
| NEFT | `"BIL/NEFT/XXXX/NAME"` | `^BIL/NEFT/` or contains `NEFT` |
| IMPS | `"IMPS/XXXX"` | `^IMPS/` |
| Cheque | `"CLG/XXXX"` or `"By Transfer-Clg"` | `CLG/` or `Clg` |
| EMI/Loan | Standard ECS/NACH formats | `^ECS/` or `^NACH` |

**Axis unique**: `"BIL/"` prefix on NEFT transactions (unique to Axis). UPI includes P2M flag.

### Kotak Mahindra Bank

| Transaction Type | Narration Format(s) | Regex Pattern |
|---|---|---|
| UPI | `"UPI-XXXX-NAME"` (dash, not slash) | `^UPI-` |
| NEFT | `"NEFT/XXXX"` | `^NEFT/` or contains `NEFT` |
| IMPS | `"IMPS/XXXX"` | `^IMPS/` |
| Cash/ATM | Standard formats | `ATM` |

**Kotak unique**: UPI uses dash (`-`) separator instead of slash (`/`).

### Bank of India (BOI)

| Transaction Type | Narration Format(s) | Regex Pattern |
|---|---|---|
| UPI | `"UPI-XXXX"` or `"UPI/XXXX"` (both formats) | `^UPI[-/]` |
| NEFT | Standard `"NEFT/XXXX"` | `NEFT` |
| IMPS | Standard `"IMPS/XXXX"` | `IMPS` |
| Cheque | `"CLG/XXXX"` or `"CHEQUE DEPOSIT"` | `CLG/` or `CHEQUE` |

**BOI unique**: UPI uses both dash and slash — need to match both.

### Cross-Bank Summary

| Feature | HDFC | SBI | ICICI | Axis | Kotak | BOI |
|---|---|---|---|---|---|---|
| UPI prefix | `UPI/` | `TO TRANSFER-UPI/` | `UPI/` | `UPI/` | `UPI-` | `UPI-` or `UPI/` |
| UPI has P2P/P2M | No | No | Yes | Yes (P2M) | No | No |
| NEFT prefix | `NEFT/` | `TO/BY TRANSFER-NEFT/` | `NEFT-` (dash) | `BIL/NEFT/` | `NEFT/` | `NEFT/` |
| IMPS prefix | `IMPS/` or `MMT/IMPS/` | `TO TRANSFER-IMPS/` | `IMPS/` | `IMPS/` | `IMPS/` | `IMPS/` |
| Cheque | `By/TO Clg`, `CLG/` | `BY/TO CLG` | `CLG/`, `CHEQUE` | `CLG/`, `By Transfer-Clg` | Standard | `CLG/`, `CHEQUE` |
| Internal Transfer | `FT/`, `IFT/` | — | — | — | — | — |
| Cash Deposit | `CASH DEP` | `BY CASH` | Standard | Standard | Standard | Standard |
| Cash Withdrawal | `ATM-CASH/`, `ATM WDL/` | `TO ATM` | Standard | Standard | Standard | Standard |

### ECS vs NACH (All Banks)
- `"ECS/DR"` (older format) = `"NACH-DR-"` (newer format)
- **Treated identically** for categorization purposes
- Both map to Loan/EMI when combined with lender name

---

## 5. TAG ASSIGNMENT SYSTEM

### Rule: Apply ALL matching tags (additive/multi-label)

Example: `"ECS/BAJAJ FINANCE LI/7UPBFR5092879"`
- Matches "ECS" → Tag: **NACH** (ECS ≈ NACH)
- Matches "BAJAJ FINANCE" (known lender) → Tags: **Loan**, **EMI**
- Result: Tags = `[Loan, NACH, EMI]`

### System-Generated Tags

| Tag | Trigger Rule |
|---|---|
| Loan | Lender name detected in narration |
| EMI | Recurring lender debit (ECS/NACH/auto-debit) |
| NACH | "NACH-" or "ECS/" in narration |
| Cheque | "Clg", "CLG/", "CHEQUE" in narration |
| Cash | Cash deposit/withdrawal narration |
| ATM | "ATM" in narration |
| NEFT | "NEFT" in narration |
| IMPS | "IMPS" in narration |
| RTGS | "RTGS" in narration |
| UPI | "UPI/" or "UPI-" in narration |
| UPI/P2P | UPI + person VPA (@ybl, @paytm, @oksbi) or person name |
| UPI/P2M | UPI + merchant VPA (@bharatpe, @razorpay, @hdfcbanksmartpay) |
| Return | "RETURN" in narration (bounce/reversal) |
| Bank Charges | "SERVICE CHARGES", "MIN BAL CHG" |
| Tax | "TAX" in narration |
| Insurance | "LIC", insurer name |
| Third Party Transfer | "IFT" keyword |
| Salary | "SALARY", "SAL", "PAYROLL" or detected via regularity |
| customtag1, customtag2 | User-defined via API/UI |

### UPI P2P vs P2M VPA Patterns

| Pattern | Classification |
|---|---|
| `@ybl` | P2P (Yes Bank Lite — personal) |
| `@paytm` | P2P (Paytm personal) |
| `@oksbi` | P2P (SBI personal) |
| `@okhdfcbank` | P2P (HDFC personal) |
| `@bharatpe` | P2M (BharatPe merchant) |
| `@razorpay` | P2M (Razorpay merchant) |
| `@hdfcbanksmartpay` | P2M (HDFC merchant) |
| Person name in narration | P2P |
| Merchant/business name | P2M |

---

## 6. COUNTERPARTY EXTRACTION

### Method
- **Algorithm**: NLP-based extraction from raw narrations
- **Master Database**: Yes — known counterparties (financial institutions, merchants, etc.)
- **String Matching**: Fuzzy matching (Levenshtein distance) OR token-based matching
- **Fallback**: "Unknown" or default label when counterparty can't be identified
- **"LG" label**: Likely a default/system label for unidentified counterparties

### Extraction Examples

| Raw Narration | Extracted Counterparty |
|---|---|
| `"ECS/BAJAJ FINANCE LI/7UPBFR5092879"` | Bajaj Finance |
| `"RTGS/AXISR52024030416738/VGUARD INDUSTRIES LTD"` | Vguard Industries Ltd |
| `"ACH Debit/LIC OF INDIA/XXXX"` | LIC of India |
| `"NEFT/MB/XXXX/JOHN DOE"` | John Doe |
| `"NACH-DR-XXXX-HDFC BANK"` | HDFC Bank |

### Variation Merging
- "Fulllerton India" → "Fullerton India" (typo correction)
- "EDELWEISSRETAILFINLT" → "Edelweiss Retail Finance" (abbreviation expansion)
- "BAJAJFINANCELTD" → "Bajaj Finance Ltd" (space/case normalization)

### Self vs Internal vs External Detection

| Type | Detection Rule |
|---|---|
| Self Transaction | Account holder's name appears in narration |
| Internal Transfer | Account holder's name appears as BOTH sender AND receiver |
| External Third Party | No match with account holder's name |

---

## 7. IMPLEMENTATION NOTES

### What We Can Build from This

1. **Rail Detection Layer** (Tier 1 — fastest):
   - Regex prefix matching: `^UPI/`, `^NEFT`, `^RTGS/`, `^IMPS/`, `^ECS/`, `^NACH-`, `By Clg`, `TO Clg`, `^ATM`, `^INB/IFT/`
   - Bank-specific normalization (SBI: `"TO TRANSFER-UPI/"`, Kotak: `"UPI-"`)

2. **Entity Override Layer** (Tier 2 — overrides Tier 1):
   - Match against lender dictionary → Loan/EMI category
   - Match against insurer list → Insurance category
   - Match against business entity database → Sales & Marketing

3. **Keyword Layer** (Tier 3):
   - "SALARY"/"SAL"/"PAYROLL" → Salary
   - "INTERNET TAX PAYMENT" → Tax Paid
   - "INT PAID" → Interest
   - "PENAL CHARGES" → Charges / Penal

4. **Behavioral Layer** (Tier 4 — ML/pattern):
   - Salary without keyword: regularity + amount + same counterparty
   - UPI P2P vs P2M: VPA pattern matching

5. **Tag Layer** (applied after category):
   - Additive — all matching tags applied
   - Independent of category assignment

### Files to Modify in Our Pipeline
- `Feature Extraction/src/classifier.py` → Add entity override priority, bank-specific UPI patterns
- `Feature Extraction/src/engines/rules_config.json` → Add cheque keywords, tax phrases, charges keywords
- `Feature Extraction/src/engines/behaviour_engine.py` → Add salary detection without keyword (regularity method)
- Consider adding: `Feature Extraction/src/rules/bank_patterns.json` → Bank-specific narration rules

### Our Existing Advantages
- We already have a 4-tier classifier (rules → keywords → rail → SLM) in `classifier.py`
- We already have `lender_dictionary` and `taxonomies` in `rules_config.json`
- We already have bank-specific patterns for 6 banks in `bank_rail_patterns`
- **Gap to fill**: Entity override priority, cheque keywords, VPA P2P/P2M patterns, salary regularity detection
