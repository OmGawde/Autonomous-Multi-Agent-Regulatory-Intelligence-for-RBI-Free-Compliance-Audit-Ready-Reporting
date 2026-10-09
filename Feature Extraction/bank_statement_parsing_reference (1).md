# Bank Statement Parsing Reference
### Keywords, Codes & Patterns — SBI | ICICI | Axis | BOI | Union Bank | Bank of Baroda

Covers: Balance Features, Needs, Wants, Savings, Investment, Debt, Banking Behaviour.
Repeated per bank on purpose (for direct per-bank parser configs). Merchant/entity keywords are
identical across banks (brands don't change) — only the **rail prefix / delimiter syntax** differs.
Balance Features are computed from the balance column, not keyword-matched, so they are listed
once per bank only with the statement-column notes that differ.

---

## 1. SBI (State Bank of India)

### 5. Balance Features (computed, not keyword-based)
- Column header in SBI statement: `Balance` (running balance after every txn)
- Opening Balance = balance value of first row
- Closing Balance = balance value of last row
- Average Daily Balance = sum(EOD balances)/days in period
- Average Monthly Balance = ADB computed per calendar month
- Median Balance = median(all daily closing balances)
- Lowest / Highest Balance = min/max of balance column
- Low Balance Count = count of days balance < min-balance threshold (SBI metro AMB requirement ~₹3,000)
- Negative Balance Count = count of days balance < 0 (overdraft-linked accounts only)
- Days Below ₹1000 = count of days balance < 1000
- Balance Recovery Time = days taken to return to ADB/threshold after a low point
- Balance Volatility = std. deviation of daily balances
- Note: SBI shows balance after EVERY transaction (not just EOD) — most granular of the six banks

### 6. Needs — rail pattern: `TO TRANSFER-UPI/DR/<Ref>/<Payee Name>/<Bank>/<VPA>/<Remarks>` (credit: `BY TRANSFER-UPI/CR/...`)
- Rent: `RENTPAY`, `NOBROKER`, `CRED RENT`, `HOUSING.COM`
- Home Loan EMI: `HL EMI`, `HOUSING LOAN`, `SBIHLEMI`, `ECS-SBIHOME`
- Society/Property Tax: `MAINT`, `BBMP`, `MCGM`, `MUNICIPAL`, `PROPERTY TAX`
- Grocery/Supermarket: `BIGBASKET`, `BLINKIT`, `ZEPTO`, `DMART`, `RELIANCE FRESH`, `MORE RETAIL`, `SPENCERS`
- Electricity/Water/Gas: `BBPS`, `BESCOM`, `MSEB`, `TATA POWER`, `ADANI ELECTRICITY`, `INDANE`, `HP GAS`, `BHARAT GAS`
- Internet/Mobile/Broadband: `AIRTEL`, `JIO`, `VODAFONE`, `VI `, `ACT FIBERNET`, `BSNL`
- Fuel: `HPCL`, `IOCL`, `BPCL`, `INDIAN OIL`, `PETROLEUM`
- Metro/Bus/Toll/Parking: `DMRC`, `NMMT`, `BEST`, `FASTAG`, `NETC FASTAG-SBI`, `NHAI`
- Taxi: `UBER`, `OLA`, `RAPIDO`, `MERU`
- Healthcare: `APOLLO`, `FORTIS`, `MAX HEALTHCARE`, `1MG`, `PHARMEASY`, `NETMEDS`, `MEDPLUS`
- Medical/Life/Vehicle Insurance: `LIC`, `STAR HEALTH`, `SBI LIFE`, `HDFC ERGO`, `NIVA BUPA`, `ACKO`, `DIGIT`
- Education: `BYJU`, `UNACADEMY`, `PHYSICS WALLAH`, `VEDANTU`, direct school/college name, `EASEBUZZ`
- Loan/EMI/CC/Personal/Vehicle/Gold: `ECS-SBI`, `ACH D-`, `NACH-`, `CC PAYMENT`, `BILLDESK-CC`, `MUTHOOT`, `MANAPPURAM`

### 6B. Wants — same prefix as above
- Food Delivery: `SWIGGY`, `BUNDL TECHNOLOGIES`, `ZOMATO`, `ETERNAL`, `TATA STARBUCKS`, `CAFE`
- Entertainment: `NETFLIX`, `AMAZON PRIME`, `DISNEY`, `SPOTIFY`, `YOUTUBE PREMIUM`
- Shopping: `AMAZON`, `ASSPL`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`, `FSN E-COMMERCE`
- Travel: `MAKEMYTRIP`, `MMT`, `AIRBNB`, `IRCTC`, `INDIGO`, `AIR INDIA`, `VISTARA`, `OYO`
- Leisure: `BOOKMYSHOW`, `PVR`, `INOX`, `STEAM`, `PLAYSTATION`, `IMAGICA`, `CLUB`
- Electronics: `APPLE`, `SAMSUNG`, `CROMA`, `INFINITY RETAIL`, `RELIANCE DIGITAL`
- Fashion: `H&M`, `ZARA`, `LIFESTYLE`, `SHOPPERS STOP`, `WESTSIDE`
- Beauty: `LAKME SALON`, `NYKAA`, `PURPLLE`, `SPA`
- Luxury: `TANISHQ`, `KALYAN JEWELLERS`, `TITAN`, `TITAN COMPANY`

### 7. Savings (derived from balance + credit/debit ledger, not keyword-based)
- Monthly Savings = Total Credits − Total Debits (per month)
- Savings Rate = Monthly Savings / Total Income
- Positive Savings Months = count(Monthly Savings > 0)
- Savings Growth = MoM % change in Monthly Savings
- Average Savings = mean(Monthly Savings)
- Savings Consistency = std.dev/coefficient of variation of Monthly Savings
- Emergency Fund Estimate = Avg Monthly Needs × 3 to 6, vs current balance
- Signal keywords: `RD INSTALLMENT`, `SWEEP-IN`, `AUTO SWEEP`, `TD ACCOUNT`

### 8. Investment
- Mutual Funds/SIP: `SIP/`, `BSE SMALLCASE`, `NSE NMF`, `CAMS`, `KFINTECH`, `BILLDESK-MF`, `NACH-MF`
- Zerodha: `ZERODHA`, `ZERODHA COIN`
- Groww: `GROWW`, `NEXTBILLION TECHNOLOGY`
- Upstox: `UPSTOX`, `RKSV SECURITIES`
- INDmoney: `INDMONEY`
- ET Money: `ET MONEY`, `BILLIONLOOP`
- PPF: `PPF DEPOSIT`, `TO PPF A/C`
- NPS: `NPS TRUST`, `NSDL-NPS`, `PROTEAN NPS`, `CRA-NPS`
- FD/RD: `FD BOOKED`, `TD ACCOUNT`, `RD INSTALLMENT`
- Bonds/SGB: `SGB`, `RBI BOND`, `SOVEREIGN GOLD BOND`
- Gold ETF/REIT: broker name + ticker (`GOLDBEES`, `EMBASSY`, `MINDSPACE`) — mostly on demat statement
- Dividend Income: `DIVIDEND`, `<Company> DIV`, NSDL/CDSL dividend credit ref
- Derived: Monthly Investment, Investment Ratio, Investment Frequency, SIP Count (recurring same-amount+date debit), Investment Growth, Long-Term Investment Score (weight PPF/NPS/SGB/FD higher), Redemption Frequency (count of credits FROM broker/MF entity)

### 9. Debt Features
- Total EMI = sum of all EMI-tagged debits per month
- EMI Burden = Total EMI / Total Income
- Loan Count = distinct lender/loan-account references
- Credit Card Payments: `CC PAYMENT`, `BILLDESK-CC`, `SBICARD`, `CREDIT CARD BILL`
- BNPL: `SIMPL`, `LAZYPAY`, `ZESTMONEY`, `SLICE`, `AMAZON PAY LATER`, `FLIPKART PAY LATER`
- Personal Loan: `ECS-SBI PL`, `PERSONAL LOAN`, `NACH-PL`
- Gold Loan: `MUTHOOT`, `MANAPPURAM`, `GOLD LOAN`
- Home Loan: `HL EMI`, `HOUSING LOAN`
- Vehicle Loan: `VEHICLE LOAN`, `AUTO LOAN`, `CAR LOAN EMI`
- Education Loan: `EDU LOAN`, `EDUCATION LOAN EMI`
- Derived: Debt-to-Income Ratio = Total EMI/Total Income; Borrowing Dependency = frequency of new loan disbursement credits vs total credits

### 10. Banking Behaviour
- ATM Withdrawals: `ATW`, `ATM-CASH`, `CWDR`, `SBI ATM`
- Cash Deposits: `CASH DEP`, `CDM`, `CASH DEPOSIT MACHINE`
- UPI / IMPS / NEFT / RTGS: rail prefix counts directly from description
- Cheque Usage: `CHQ PAID`, `CHEQUE`, `CLG` (clearing)
- Online Purchases: `ECOM`, `POS ECOM`, `ONLINE`
- Merchant Diversity = count of distinct unique merchant names/VPAs
- Average Transaction Value = mean(abs(txn amounts))

---

## 2. ICICI Bank

### 5. Balance Features
- Column header: `Balance` (post-txn running balance)
- Same formulas as SBI section above (Opening/Closing/ADB/AMB/Median/Low/High/Low Balance Count/Negative Balance Count/Days Below ₹1000/Recovery Time/Volatility)
- Note: ICICI minimum balance requirement varies by account type (₹0–₹10,000) — use account-specific threshold for Low Balance Count

### 6. Needs — rail pattern: `UPI/<Ref No>/<Remarks>/<Payee VPA>/<Payee Bank>` (also seen: `UPI/<Payee Name>/<Ref>`)
- Rent: `RENTPAY`, `NOBROKER`, `CRED RENT`, `HOUSING.COM`
- Home Loan EMI: `HL EMI`, `HOUSING LOAN`, `ICICIHLEMI`, `ACH DEBIT-ICICI HFC`
- Society/Property Tax: `MAINT`, `BBMP`, `MCGM`, `MUNICIPAL`, `PROPERTY TAX`
- Grocery/Supermarket: `BIGBASKET`, `BLINKIT`, `ZEPTO`, `DMART`, `RELIANCE FRESH`, `MORE RETAIL`, `SPENCERS`
- Electricity/Water/Gas: `BBPS`, `BESCOM`, `MSEB`, `TATA POWER`, `ADANI ELECTRICITY`, `INDANE`, `HP GAS`
- Internet/Mobile: `AIRTEL`, `JIO`, `VODAFONE`, `VI `, `ACT FIBERNET`, `BSNL`
- Fuel: `HPCL`, `IOCL`, `BPCL`, `INDIAN OIL`
- Metro/Toll: `DMRC`, `FASTAG`, `NETC FASTAG-ICIC`, `NHAI`
- Taxi: `UBER`, `OLA`, `RAPIDO`
- Healthcare: `APOLLO`, `FORTIS`, `MAX HEALTHCARE`, `1MG`, `PHARMEASY`, `NETMEDS`, `MEDPLUS`
- Insurance: `LIC`, `ICICI PRU LIFE`, `ICICI LOMBARD`, `STAR HEALTH`, `NIVA BUPA`, `ACKO`, `DIGIT`
- Education: `BYJU`, `UNACADEMY`, `PHYSICS WALLAH`, `VEDANTU`, school/college name
- Loan/EMI: `ACH DEBIT-<Lender>`, `NACH-`, `CC PAYMENT`, `BILLDESK-CC`, `MUTHOOT`, `MANAPPURAM`

### 6B. Wants — same as SBI list (brand names identical across banks)
- Food Delivery: `SWIGGY`, `BUNDL TECHNOLOGIES`, `ZOMATO`, `ETERNAL`, `TATA STARBUCKS`, `CAFE`
- Entertainment: `NETFLIX`, `AMAZON PRIME`, `DISNEY`, `SPOTIFY`, `YOUTUBE PREMIUM`
- Shopping: `AMAZON`, `ASSPL`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`, `FSN E-COMMERCE`
- Travel: `MAKEMYTRIP`, `MMT`, `AIRBNB`, `IRCTC`, `INDIGO`, `AIR INDIA`, `OYO`
- Leisure: `BOOKMYSHOW`, `PVR`, `INOX`, `STEAM`, `PLAYSTATION`, `CLUB`
- Electronics: `APPLE`, `SAMSUNG`, `CROMA`, `INFINITY RETAIL`, `RELIANCE DIGITAL`
- Fashion: `H&M`, `ZARA`, `LIFESTYLE`, `SHOPPERS STOP`, `WESTSIDE`
- Beauty: `LAKME SALON`, `NYKAA`, `PURPLLE`, `SPA`
- Luxury: `TANISHQ`, `KALYAN JEWELLERS`, `TITAN COMPANY`

### 7. Savings
- Same derived formulas as SBI section
- Signal keywords: `RD INSTALLMENT`, `SWEEP-IN`, `AUTO SWEEP`, `TD ACCOUNT`, `ICICI FLEXI RD`

### 8. Investment
- Mutual Funds/SIP: `SIP/`, `BSE SMALLCASE`, `NSE NMF`, `CAMS`, `KFINTECH`, `ICICI DIRECT MF`
- Zerodha: `ZERODHA`, `ZERODHA COIN`
- Groww: `GROWW`, `NEXTBILLION TECHNOLOGY`
- Upstox: `UPSTOX`, `RKSV SECURITIES`
- INDmoney: `INDMONEY`
- ET Money: `ET MONEY`, `BILLIONLOOP`
- ICICI-native: `ICICI DIRECT`, `ICICI SECURITIES`
- PPF: `PPF DEPOSIT`
- NPS: `NPS TRUST`, `NSDL-NPS`, `PROTEAN NPS`
- FD/RD: `FD BOOKED`, `TD ACCOUNT`, `RD INSTALLMENT`
- Bonds/SGB: `SGB`, `RBI BOND`
- Dividend Income: `DIVIDEND`, NSDL/CDSL dividend credit ref
- Derived metrics same as SBI section

### 9. Debt Features
- Credit Card Payments: `CC PAYMENT`, `BILLDESK-CC`, `ICICI CREDIT CARD`
- BNPL: `SIMPL`, `LAZYPAY`, `ZESTMONEY`, `SLICE`, `AMAZON PAY LATER`
- Personal Loan: `ACH DEBIT-ICICI PL`, `PERSONAL LOAN`
- Gold Loan: `MUTHOOT`, `MANAPPURAM`
- Home Loan: `HL EMI`, `ICICI HFC`
- Vehicle Loan: `VEHICLE LOAN EMI`, `AUTO LOAN`
- Education Loan: `EDU LOAN EMI`
- Derived: Debt-to-Income Ratio, Borrowing Dependency (same formulas as SBI)

### 10. Banking Behaviour
- ATM Withdrawals: `ATW`, `ATM-CASH`, `ICICI ATM`
- Cash Deposits: `CASH DEP`, `CDM`
- UPI/IMPS/NEFT/RTGS: count from rail prefix
- Cheque Usage: `CHQ PAID`, `CLG`
- Online Purchases: `POS <Merchant> <City>`, `ECOM`
- Merchant Diversity / Avg Transaction Value: same formulas as SBI

---

## 3. Axis Bank

### 5. Balance Features
- Column header: `Balance` (post-txn running balance)
- Same formulas as SBI (Opening/Closing/ADB/AMB/Median/Low/High/Low Balance Count/Negative Balance Count/Days Below ₹1000/Recovery Time/Volatility)

### 6. Needs — rail pattern: `UPI/P2M/<Ref>/<Merchant Name>/<VPA>` (P2A drops `/P2M/`)
- **Key advantage**: Axis explicitly tags `P2M` (merchant) vs `P2A` (person) — the most reliable Needs-vs-transfer / Wants-vs-transfer signal of the six banks
- Rent: `RENTPAY`, `NOBROKER`, `CRED RENT`, `HOUSING.COM`
- Home Loan EMI: `HL EMI`, `HOUSING LOAN`, `NACH DR-AXIS HL`
- Society/Property Tax: `MAINT`, `BBMP`, `MCGM`, `MUNICIPAL`, `PROPERTY TAX`
- Grocery/Supermarket: `BIGBASKET`, `BLINKIT`, `ZEPTO`, `DMART`, `RELIANCE FRESH`, `MORE RETAIL`, `SPENCERS`
- Electricity/Water/Gas: `BBPS`, `BESCOM`, `MSEB`, `TATA POWER`, `ADANI ELECTRICITY`, `INDANE`, `HP GAS`
- Internet/Mobile: `AIRTEL`, `JIO`, `VODAFONE`, `VI `, `ACT FIBERNET`, `BSNL`
- Fuel: `HPCL`, `IOCL`, `BPCL`, `INDIAN OIL`
- Metro/Toll: `DMRC`, `FASTAG`, `NETC FASTAG-UTIB`, `NHAI`
- Taxi: `UBER`, `OLA`, `RAPIDO`
- Healthcare: `APOLLO`, `FORTIS`, `MAX HEALTHCARE`, `1MG`, `PHARMEASY`, `NETMEDS`, `MEDPLUS`
- Insurance: `LIC`, `MAX LIFE`, `NIVA BUPA`, `ACKO`, `DIGIT`
- Education: `BYJU`, `UNACADEMY`, `PHYSICS WALLAH`, `VEDANTU`, school/college name
- Loan/EMI: `NACH DR-<Lender>`, `CC PAYMENT`, `BILLDESK-CC`, `MUTHOOT`, `MANAPPURAM`

### 6B. Wants — same brand list as SBI/ICICI
- Food Delivery: `SWIGGY`, `BUNDL TECHNOLOGIES`, `ZOMATO`, `ETERNAL`, `TATA STARBUCKS`, `CAFE`
- Entertainment: `NETFLIX`, `AMAZON PRIME`, `DISNEY`, `SPOTIFY`, `YOUTUBE PREMIUM`
- Shopping: `AMAZON`, `ASSPL`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`, `FSN E-COMMERCE`
- Travel: `MAKEMYTRIP`, `MMT`, `AIRBNB`, `IRCTC`, `INDIGO`, `AIR INDIA`, `OYO`
- Leisure: `BOOKMYSHOW`, `PVR`, `INOX`, `STEAM`, `PLAYSTATION`, `CLUB`
- Electronics: `APPLE`, `SAMSUNG`, `CROMA`, `INFINITY RETAIL`, `RELIANCE DIGITAL`
- Fashion: `H&M`, `ZARA`, `LIFESTYLE`, `SHOPPERS STOP`, `WESTSIDE`
- Beauty: `LAKME SALON`, `NYKAA`, `PURPLLE`, `SPA`
- Luxury: `TANISHQ`, `KALYAN JEWELLERS`, `TITAN COMPANY`

### 7. Savings
- Same derived formulas as SBI
- Signal keywords: `RD INSTALLMENT`, `SWEEP-IN`, `AUTO SWEEP`, `TD ACCOUNT`

### 8. Investment
- Mutual Funds/SIP: `SIP/`, `BSE SMALLCASE`, `NSE NMF`, `CAMS`, `KFINTECH`
- Zerodha: `ZERODHA`, `ZERODHA COIN`
- Groww: `GROWW`, `NEXTBILLION TECHNOLOGY`
- Upstox: `UPSTOX`, `RKSV SECURITIES`
- INDmoney: `INDMONEY`
- ET Money: `ET MONEY`, `BILLIONLOOP`
- PPF: `PPF DEPOSIT`
- NPS: `NPS TRUST`, `NSDL-NPS`, `PROTEAN NPS`
- FD/RD: `FD BOOKED`, `TD ACCOUNT`, `RD INSTALLMENT`
- Bonds/SGB: `SGB`, `RBI BOND`
- Dividend Income: `DIVIDEND`, NSDL/CDSL dividend credit ref
- Derived metrics same as SBI

### 9. Debt Features
- Credit Card Payments: `CC PAYMENT`, `BILLDESK-CC`, `AXIS CREDIT CARD`
- BNPL: `SIMPL`, `LAZYPAY`, `ZESTMONEY`, `SLICE`, `AMAZON PAY LATER`
- Personal Loan: `NACH DR-AXIS PL`, `PERSONAL LOAN`
- Gold Loan: `MUTHOOT`, `MANAPPURAM`
- Home Loan: `HL EMI`
- Vehicle Loan: `VEHICLE LOAN EMI`
- Education Loan: `EDU LOAN EMI`
- Derived: Debt-to-Income Ratio, Borrowing Dependency (same formulas as SBI)

### 10. Banking Behaviour
- ATM Withdrawals: `ATW`, `ATM-CASH`, `AXIS ATM`
- Cash Deposits: `CASH DEP`, `CDM`
- UPI/IMPS/NEFT/RTGS: count from rail prefix (use `P2M`/`P2A` split for extra granularity)
- Cheque Usage: `CHQ PAID`, `CLG`
- Online Purchases: `<MERCHANT> <CITY> <STATE>`, `ECOM`
- Merchant Diversity / Avg Transaction Value: same formulas as SBI

---

## 4. Bank of India (BOI)

*Runs on Finacle core banking — shorter, terser strings than private banks. Merchant names frequently
truncated (~20-25 chars); build fuzzy/partial-match fallback.*

### 5. Balance Features
- Column header: `Balance` (running balance, may only update EOD in some Finacle exports)
- Same formulas as SBI section
- Note: forward-fill last known balance across no-transaction days for accurate ADB

### 6. Needs — rail pattern: `UPI-<Payee Name>-<VPA>-<Ref>` or terser `UPI/<Ref>/<Remarks>`
- Rent: `RENTPAY`, `NOBROKER`, `CRED RENT`
- Home Loan EMI: `HL EMI`, `HOUSING LOAN`, `ECS/BOI HL`
- Society/Property Tax: `MAINT`, `BBMP`, `MCGM`, `PROPERTY TAX`
- Grocery/Supermarket: `BIGBASKET`, `BLINKIT`, `ZEPTO`, `DMART`, `RELIANCE FRESH`, `MORE RETAIL`
- Electricity/Water/Gas: `BBPS`, `BESCOM`, `MSEB`, `TATA POWER`, `INDANE`, `HP GAS`
- Internet/Mobile: `AIRTEL`, `JIO`, `VODAFONE`, `VI `, `BSNL`
- Fuel: `HPCL`, `IOCL`, `BPCL`, `INDIAN OIL`
- Metro/Toll: `DMRC`, `FASTAG`, `NETC FASTAG-BKID`, `NHAI`
- Taxi: `UBER`, `OLA`, `RAPIDO`
- Healthcare: `APOLLO`, `FORTIS`, `1MG`, `PHARMEASY`, `NETMEDS`, `MEDPLUS`
- Insurance: `LIC`, `STAR HEALTH`, `NIVA BUPA`, `ACKO`, `DIGIT`
- Education: `BYJU`, `UNACADEMY`, `VEDANTU`, school/college name
- Loan/EMI: `ECS/<Lender>/<Loan No>`, `NACH-`, `CC PAYMENT`, `MUTHOOT`, `MANAPPURAM`

### 6B. Wants — same brand list (allow partial/truncated matches for this bank)
- Food Delivery: `SWIGG`, `ZOMATO`, `STARBUCKS`, `CAFE`
- Entertainment: `NETFLIX`, `PRIME`, `DISNEY`, `SPOTIFY`, `YOUTUBE`
- Shopping: `AMAZON`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`
- Travel: `MAKEMYTRIP`, `MMT`, `AIRBNB`, `IRCTC`, `INDIGO`, `OYO`
- Leisure: `BOOKMYSHOW`, `PVR`, `INOX`, `STEAM`, `CLUB`
- Electronics: `APPLE`, `SAMSUNG`, `CROMA`, `RELIANCE DIGITAL`
- Fashion: `H&M`, `ZARA`, `LIFESTYLE`, `SHOPPERS STOP`
- Beauty: `LAKME`, `NYKAA`, `SPA`
- Luxury: `TANISHQ`, `KALYAN`, `TITAN`

### 7. Savings
- Same derived formulas as SBI
- Signal keywords: `RD INSTALLMENT`, `SWEEP-IN`, `TD ACCOUNT`

### 8. Investment
- Mutual Funds/SIP: `SIP/`, `CAMS`, `KFINTECH`, `NACH-MF`
- Zerodha: `ZERODHA`
- Groww: `GROWW`, `NEXTBILLION`
- Upstox: `UPSTOX`, `RKSV`
- INDmoney: `INDMONEY`
- ET Money: `ET MONEY`, `BILLIONLOOP`
- PPF: `PPF DEPOSIT`
- NPS: `NPS TRUST`, `NSDL-NPS`
- FD/RD: `FD BOOKED`, `TD ACCOUNT`, `RD INSTALLMENT`
- Bonds/SGB: `SGB`, `RBI BOND`
- Dividend Income: `DIVIDEND`
- Derived metrics same as SBI

### 9. Debt Features
- Credit Card Payments: `CC PAYMENT`, `BOI CREDIT CARD`
- BNPL: `SIMPL`, `LAZYPAY`, `SLICE`
- Personal Loan: `ECS/BOI PL`, `PERSONAL LOAN`
- Gold Loan: `MUTHOOT`, `MANAPPURAM`
- Home Loan: `HL EMI`
- Vehicle Loan: `VEHICLE LOAN EMI`
- Education Loan: `EDU LOAN EMI`
- Derived: Debt-to-Income Ratio, Borrowing Dependency (same formulas as SBI)

### 10. Banking Behaviour
- ATM Withdrawals: `ATW`, `BOI ATM`, `CWDR`
- Cash Deposits: `CASH DEP`, `CDM`
- UPI/IMPS/NEFT/RTGS: count from rail prefix
- Cheque Usage: `CHQ PAID`, `CLG`
- Online Purchases: `ECOM`, `POS`
- Merchant Diversity / Avg Transaction Value: same formulas as SBI

---

## 5. Union Bank of India

*Finacle-based, same family as BOI. Legacy accounts from Andhra Bank/Corporation Bank (merged 2020)
may show older, inconsistent format strings — add a fallback parsing path for these.*

### 5. Balance Features
- Column header: `Balance`
- Same formulas as SBI section
- Note: check for dual format co-existing (legacy Andhra Bank/Corp Bank strings vs new Union Finacle strings) in accounts opened before 2020

### 6. Needs — rail pattern: `UPI/<Ref>/<Payee Name>/<Remarks>`
- Rent: `RENTPAY`, `NOBROKER`, `CRED RENT`
- Home Loan EMI: `HL EMI`, `HOUSING LOAN`, `NACH-UNION HL`
- Society/Property Tax: `MAINT`, `BBMP`, `MCGM`, `PROPERTY TAX`
- Grocery/Supermarket: `BIGBASKET`, `BLINKIT`, `ZEPTO`, `DMART`, `RELIANCE FRESH`, `MORE RETAIL`
- Electricity/Water/Gas: `BBPS`, `BESCOM`, `MSEB`, `TATA POWER`, `INDANE`, `HP GAS`
- Internet/Mobile: `AIRTEL`, `JIO`, `VODAFONE`, `VI `, `BSNL`
- Fuel: `HPCL`, `IOCL`, `BPCL`, `INDIAN OIL`
- Metro/Toll: `DMRC`, `FASTAG`, `NETC FASTAG-UBIN`, `NHAI`
- Taxi: `UBER`, `OLA`, `RAPIDO`
- Healthcare: `APOLLO`, `FORTIS`, `1MG`, `PHARMEASY`, `NETMEDS`, `MEDPLUS`
- Insurance: `LIC`, `STAR HEALTH`, `NIVA BUPA`, `ACKO`, `DIGIT`
- Education: `BYJU`, `UNACADEMY`, `VEDANTU`, school/college name
- Loan/EMI: `NACH-<Lender>-EMI`, `CC PAYMENT`, `MUTHOOT`, `MANAPPURAM`

### 6B. Wants — same brand list (allow partial/truncated matches)
- Food Delivery: `SWIGG`, `ZOMATO`, `STARBUCKS`, `CAFE`
- Entertainment: `NETFLIX`, `PRIME`, `DISNEY`, `SPOTIFY`, `YOUTUBE`
- Shopping: `AMAZON`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`
- Travel: `MAKEMYTRIP`, `MMT`, `AIRBNB`, `IRCTC`, `INDIGO`, `OYO`
- Leisure: `BOOKMYSHOW`, `PVR`, `INOX`, `STEAM`, `CLUB`
- Electronics: `APPLE`, `SAMSUNG`, `CROMA`, `RELIANCE DIGITAL`
- Fashion: `H&M`, `ZARA`, `LIFESTYLE`, `SHOPPERS STOP`
- Beauty: `LAKME`, `NYKAA`, `SPA`
- Luxury: `TANISHQ`, `KALYAN`, `TITAN`

### 7. Savings
- Same derived formulas as SBI
- Signal keywords: `RD INSTALLMENT`, `SWEEP-IN`, `TD ACCOUNT`

### 8. Investment
- Mutual Funds/SIP: `SIP/`, `CAMS`, `KFINTECH`, `NACH-MF`
- Zerodha: `ZERODHA`
- Groww: `GROWW`, `NEXTBILLION`
- Upstox: `UPSTOX`, `RKSV`
- INDmoney: `INDMONEY`
- ET Money: `ET MONEY`, `BILLIONLOOP`
- PPF: `PPF DEPOSIT`
- NPS: `NPS TRUST`, `NSDL-NPS`
- FD/RD: `FD BOOKED`, `TD ACCOUNT`, `RD INSTALLMENT`
- Bonds/SGB: `SGB`, `RBI BOND`
- Dividend Income: `DIVIDEND`
- Derived metrics same as SBI

### 9. Debt Features
- Credit Card Payments: `CC PAYMENT`, `UNION CREDIT CARD`
- BNPL: `SIMPL`, `LAZYPAY`, `SLICE`
- Personal Loan: `NACH-UNION PL`, `PERSONAL LOAN`
- Gold Loan: `MUTHOOT`, `MANAPPURAM`
- Home Loan: `HL EMI`
- Vehicle Loan: `VEHICLE LOAN EMI`
- Education Loan: `EDU LOAN EMI`
- Derived: Debt-to-Income Ratio, Borrowing Dependency (same formulas as SBI)

### 10. Banking Behaviour
- ATM Withdrawals: `ATW`, `UNION ATM`, `CWDR`
- Cash Deposits: `CASH DEP`, `CDM`
- UPI/IMPS/NEFT/RTGS: count from rail prefix
- Cheque Usage: `CHQ PAID`, `CLG`
- Online Purchases: `ECOM`, `POS`
- Merchant Diversity / Avg Transaction Value: same formulas as SBI

---

## 6. Bank of Baroda (BOB)

*Finacle-based, same family as BOI/Union. Legacy accounts from Vijaya Bank/Dena Bank (merged 2019)
may retain older format strings — add a fallback parsing path for these.*

### 5. Balance Features
- Column header: `Balance`
- Same formulas as SBI section
- Note: check for dual format co-existing (legacy Vijaya/Dena Bank strings vs new BOB Finacle strings) in accounts opened before 2019

### 6. Needs — rail pattern: `UPI/<Ref>/<Remarks>/<Payee Name>`
- Rent: `RENTPAY`, `NOBROKER`, `CRED RENT`
- Home Loan EMI: `HL EMI`, `HOUSING LOAN`, `ECS DR-BOB HL`
- Society/Property Tax: `MAINT`, `BBMP`, `MCGM`, `PROPERTY TAX`
- Grocery/Supermarket: `BIGBASKET`, `BLINKIT`, `ZEPTO`, `DMART`, `RELIANCE FRESH`, `MORE RETAIL`
- Electricity/Water/Gas: `BBPS`, `BESCOM`, `MSEB`, `TATA POWER`, `INDANE`, `HP GAS`
- Internet/Mobile: `AIRTEL`, `JIO`, `VODAFONE`, `VI `, `BSNL`
- Fuel: `HPCL`, `IOCL`, `BPCL`, `INDIAN OIL`
- Metro/Toll: `DMRC`, `FASTAG`, `NETC FASTAG-BARB`, `NHAI`
- Taxi: `UBER`, `OLA`, `RAPIDO`
- Healthcare: `APOLLO`, `FORTIS`, `1MG`, `PHARMEASY`, `NETMEDS`, `MEDPLUS`
- Insurance: `LIC`, `STAR HEALTH`, `NIVA BUPA`, `ACKO`, `DIGIT`
- Education: `BYJU`, `UNACADEMY`, `VEDANTU`, school/college name
- Loan/EMI: `ECS DR-<Lender>`, `NACH-`, `CC PAYMENT`, `MUTHOOT`, `MANAPPURAM`

### 6B. Wants — same brand list (allow partial/truncated matches)
- Food Delivery: `SWIGG`, `ZOMATO`, `STARBUCKS`, `CAFE`
- Entertainment: `NETFLIX`, `PRIME`, `DISNEY`, `SPOTIFY`, `YOUTUBE`
- Shopping: `AMAZON`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`
- Travel: `MAKEMYTRIP`, `MMT`, `AIRBNB`, `IRCTC`, `INDIGO`, `OYO`
- Leisure: `BOOKMYSHOW`, `PVR`, `INOX`, `STEAM`, `CLUB`
- Electronics: `APPLE`, `SAMSUNG`, `CROMA`, `RELIANCE DIGITAL`
- Fashion: `H&M`, `ZARA`, `LIFESTYLE`, `SHOPPERS STOP`
- Beauty: `LAKME`, `NYKAA`, `SPA`
- Luxury: `TANISHQ`, `KALYAN`, `TITAN`

### 7. Savings
- Same derived formulas as SBI
- Signal keywords: `RD INSTALLMENT`, `SWEEP-IN`, `TD ACCOUNT`

### 8. Investment
- Mutual Funds/SIP: `SIP/`, `CAMS`, `KFINTECH`, `NACH-MF`
- Zerodha: `ZERODHA`
- Groww: `GROWW`, `NEXTBILLION`
- Upstox: `UPSTOX`, `RKSV`
- INDmoney: `INDMONEY`
- ET Money: `ET MONEY`, `BILLIONLOOP`
- PPF: `PPF DEPOSIT`
- NPS: `NPS TRUST`, `NSDL-NPS`
- FD/RD: `FD BOOKED`, `TD ACCOUNT`, `RD INSTALLMENT`
- Bonds/SGB: `SGB`, `RBI BOND`
- Dividend Income: `DIVIDEND`
- Derived metrics same as SBI

### 9. Debt Features
- Credit Card Payments: `CC PAYMENT`, `BOB CREDIT CARD`
- BNPL: `SIMPL`, `LAZYPAY`, `SLICE`
- Personal Loan: `ECS DR-BOB PL`, `PERSONAL LOAN`
- Gold Loan: `MUTHOOT`, `MANAPPURAM`
- Home Loan: `HL EMI`
- Vehicle Loan: `VEHICLE LOAN EMI`
- Education Loan: `EDU LOAN EMI`
- Derived: Debt-to-Income Ratio, Borrowing Dependency (same formulas as SBI)

### 10. Banking Behaviour
- ATM Withdrawals: `ATW`, `BOB ATM`, `CWDR`
- Cash Deposits: `CASH DEP`, `CDM`
- UPI/IMPS/NEFT/RTGS: count from rail prefix
- Cheque Usage: `CHQ PAID`, `CLG`
- Online Purchases: `ECOM`, `POS`
- Merchant Diversity / Avg Transaction Value: same formulas as SBI

---

## Notes for parser implementation

1. **Confidence tiers**: SBI/ICICI/Axis formats are high-confidence (well-documented, verbose strings).
   BOI/Union/BOB are medium-confidence common-pattern estimates (Finacle-family, less publicly
   documented) — validate against a handful of real statement rows per bank before finalizing regex.
2. **Merged keyword dictionary**: Wants, Investment, and Debt-BNPL/lender keyword lists are IDENTICAL
   across all six banks — maintain ONE master dictionary and only swap the rail-prefix regex per bank.
3. **Truncation handling**: BOI/Union/BOB are more likely to truncate merchant names — use partial/fuzzy
   string matching (e.g. Levenshtein or substring) rather than exact match for these three.
4. **Legacy format fallback**: Union Bank (ex-Andhra/Corporation Bank) and BOB (ex-Vijaya/Dena Bank)
   accounts opened pre-merger may show old-format strings — build a secondary regex path for these.
5. **P2M/P2A flag**: Only Axis reliably exposes this — if available, use it as a high-confidence
   Needs/Wants-vs-transfer filter; for other banks, fall back to keyword dictionary matching only.
