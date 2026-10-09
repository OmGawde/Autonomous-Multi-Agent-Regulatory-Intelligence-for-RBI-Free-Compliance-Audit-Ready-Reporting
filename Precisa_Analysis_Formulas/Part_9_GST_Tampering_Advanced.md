# Part 9: GST Reconciliation, PDF Tampering & Advanced Underwriting

> **Source**: Precisa AI Agent responses (August 2026)
> **Status**: Implementation-ready
> **Applicable to**: GST reconciliation module, PDF security/tamper checker, profile-based underwriting

---

## 1. GST VS BANK STATEMENT RECONCILIATION

### Reconciliation Methodology
- Compares declared revenue in **GSTR-3B (Table 3.1a - Outward Taxable Supplies)** and **GSTR-1** against **Net Bank Inward Credits (True Turnover)** for matching tax periods.

### Discrepancy & Under-Reporting Rules

| Turnover Variance ($\Delta\%$) | Risk Level | Underwriting Flag |
|---|---|---|
| **$\le 10\%$** | Low Risk | Turnover reconciled within normal trade credit/timing variance |
| **$15\% - 20\%$** | **Moderate / High Flag** | **Under-reporting or circular billing indicator** |
| **$> 20\%$** | **Critical Red Flag** | Major tax evasion / artificial bank inflation alert |

$$\text{Variance } \% = \frac{|\text{Net Bank Turnover} - \text{GSTR-3B Turnover}|}{\text{GSTR-3B Turnover}} \times 100$$

### GST Tax Payment Narration Detection
- Bank debits matching GST payments:
  - `"GST PAYMENT"`, `"CBIC"`, `"GSTN"`, `"GOVT TAX"`, `"GST DEPOSIT"`

---

## 2. PDF TAMPERING & SECURITY CHECKS

### Metadata Discrepancy Matrix

| Check Type | Detection Rule | Severity |
|---|---|---|
| **Modification Discrepancy** | `ModDate` is significantly later than `CreationDate` | **High / Critical** |
| **Third-Party Editor Stamp** | `Producer` or `Creator` metadata contains: `iText`, `PDFTron`, `Canva`, `Photoshop`, `Nitro`, `Foxit`, `LibreOffice`, `wkhtmltopdf` | **Critical** (Statement edited) |
| **Font Inconsistency** | Non-standard or embedded font styles that do not match the bank's core banking PDF template | **High** |
| **Digital Signature Broken** | Bank's native digital signature absent or invalidated | **Critical** |

---

## 3. BORROWER PROFILE-BASED THRESHOLDS

### Profile Comparison Matrix

| Rule / Metric | Salaried Profile | Business / Current Account Profile |
|---|---|---|
| **Cash Deposit Warning** | **$> 10\%$** of total credits (or $> 1.5\times$ salary) | **$> 30\%$** of total credits (Traders allow higher cash) |
| **Primary Income Metric** | Regular Monthly Salary Credits | Net Business Credits (Turnover) |
| **FOIR Cutoff** | **$> 50\%$ High Risk**, $> 70\%$ Critical | **$> 60\%$ High Risk** |
| **OD/CC Utilization** | N/A (or Personal Overdraft) | $<30\%$ Healthy, $>50\%$ Risky |
| **Minimum Statement** | 3 to 6 months | 6 to 12 months |
