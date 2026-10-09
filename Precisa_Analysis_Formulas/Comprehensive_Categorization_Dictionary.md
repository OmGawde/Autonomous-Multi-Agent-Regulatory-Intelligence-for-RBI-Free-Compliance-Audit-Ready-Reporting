# Comprehensive Transaction Categorization & Merchant Dictionary

> **Context**: Complete Indian Banking Merchant, VPA & Narration Keywords for granular expense categorization.
> **Format**: Direct drop-in configuration for `rules_config.json` and `classifier.py`.

---

## 1. CATEGORY TAXONOMY MAPPING

| Primary Category | Sub-Categories | Typical Narration Strings / Merchant VPAs |
|---|---|---|
| **Food & Dining** | Food Delivery, Restaurants, Cafes, Pubs | `SWIGGY`, `ZOMATO`, `BUNDL`, `ETERNAL`, `MCDONALDS`, `DOMINOS`, `STARBUCKS`, `CHAAYOS`, `BARBEQUE`, `HALDIRAM`, `SUBWAY`, `KFC` |
| **Groceries & Daily Essentials** | Quick Commerce, Supermarkets, Hypermarkets | `BLINKIT`, `ZEPTO`, `INSTAMART`, `BIGBASKET`, `DMART`, `AVENUE SUPERMARTS`, `RELIANCE FRESH`, `MORE RETAIL`, `SPENCERS`, `NATURES BASKET` |
| **Consumer Products & Shopping** | E-Commerce, Retail, Electronics, Apparel | `AMAZON`, `ASSPL`, `FLIPKART`, `FKRT`, `MYNTRA`, `AJIO`, `NYKAA`, `TATA CLiQ`, `CROMA`, `RELIANCE DIGITAL`, `ZARA`, `H&M`, `WESTSIDE`, `LIFESTYLE`, `DECATHLON`, `MEESHO` |
| **Travel, Transport & Fuel** | Cabs/Commute, Flights, Rail/Bus, Fuel/Toll | `UBER`, `OLA`, `RAPIDO`, `NAMMA YATRI`, `IRCTC`, `MAKEMYTRIP`, `EASEMYTRIP`, `INDIGO`, `AIR INDIA`, `RED BUS`, `HPCL`, `IOCL`, `BPCL`, `SHELL`, `FASTAG`, `NETC` |
| **Learning & Development (Education)** | EdTech, Coaching, School/Colleges, Certifications | `COURSERA`, `UDEMY`, `UPGRAD`, `UNACADEMY`, `PHYSICSWALLAH`, `BYJUS`, `SIMPLILEARN`, `COLLEGE`, `SCHOOL`, `TUITION`, `EASEBUZZ`, `FEE`, `UNIVERSITY` |
| **Utilities, Telecom & Bills** | Electricity, Piped Gas, Water, Mobile, Broadband | `BBPS`, `BESCOM`, `TATA POWER`, `MSEB`, `ADANI ELEC`, `MGL`, `IGL`, `INDANE`, `HP GAS`, `AIRTEL`, `JIO`, `VI `, `ACT FIBERNET`, `TATA PLAY`, `BSNL` |
| **Charges & Fees (Bank & Penal)** | Bank Charges, Minimum Balance, Penal, Returns | `MIN BAL CHG`, `SERVICE CHARGES`, `CONSOLIDATED CHARGES`, `ANNUAL CARD FEE`, `SMS CHG`, `PENAL CHARGES`, `BOUNCE CHG`, `RETURN FEE`, `INSUFFICIENT FUNDS`, `FOREX MARKUP` |

---

## 2. GRANULAR KEYWORD DICTIONARY FOR INDIA

### A. Food & Dining / Groceries

```json
{
  "Food_Delivery": [
    "SWIGGY", "BUNDL TECHNOLOGIES", "ZOMATO", "ETERNAL", "EATS",
    "MAGICPIN", "EATFIT", "BOX8", "FAASOS", "REBEL FOODS", "FRESHMENU"
  ],
  "Restaurants_Cafes": [
    "MCDONALDS", "HARDCASTLE", "DOMINOS", "JUBILANT FOODWORKS", "PIZZA HUT",
    "DEVYANI INTL", "SUBWAY", "STARBUCKS", "TATA STARBUCKS", "CHAAYOS", "CHAI POINT",
    "CAFE COFFEE DAY", "CCD", "BARBEQUE NATION", "HALDIRAMS", "BIKANERVALA",
    "SOCIAL", "BEER CAFE", "MAINLAND CHINA", "PVR FOOD", "RESTAURANT", "CAFE", "BAKERY", "DINER"
  ],
  "Groceries_QuickCommerce": [
    "BLINKIT", "ZEPTO", "BIGBASKET", "INNOVATIVE RETAIL", "INSTAMART",
    "DMART", "AVENUE SUPERMARTS", "RELIANCE FRESH", "RELIANCE RETAIL", "SMART BAZAAR",
    "MORE RETAIL", "SPENCERS", "NATURES BASKET", "LICKIOUS", "COUNTRY DELIGHT",
    "OTIPY", "SUPERMARKET", "PROVISION", "KIRANA", "FRESH VEG"
  ]
}
```

---

### B. Consumer Products & Shopping (Retail & E-Commerce)

```json
{
  "ECommerce_General": [
    "AMAZON", "ASSPL", "AMZN", "FLIPKART", "FKRT", "MEESHO", "FASHNEAR",
    "TATA CLIQ", "SNAPDEAL", "JIO MART", "CRED STORE", "PAYTM MALL"
  ],
  "Apparel_Fashion": [
    "MYNTRA", "AJIO", "RELIANCE RETAIL", "NYKAA", "FSN E-COMMERCE", "ZARA", "INDITEX",
    "H&M", "HENNES", "WESTSIDE", "TRENT", "LIFESTYLE", "SHOPPERS STOP", "MAX FASHION",
    "PANTALOONS", "ADITYA BIRLA FASHION", "MARKS & SPENCER", "DECATHLON", "PUMA",
    "NIKE", "ADIDAS", "UNIQLO", "BEWAKOOF", "SNITCH", "URBANIC"
  ],
  "Electronics_Appliances": [
    "CROMA", "INFINITI RETAIL", "RELIANCE DIGITAL", "VIJAY SALES", "APPLE",
    "SAMSUNG", "BOAT", "IMAGINE STORE", "UNISTORE", "ONEPLUS", "XIAOMI", "LENOVO"
  ],
  "Beauty_PersonalCare": [
    "NYKAA", "PURPLLE", "SUGAR COSMETICS", "MAMAEARTH", "HONASA", "THE DERMA CO",
    "KAPIVA", "BOMBAY SHAVING", "BEARDO", "LAKME", "KAYA", "SPA", "SALON"
  ]
}
```

---

### C. Travel, Transport & Fuel

```json
{
  "Cabs_Commute": [
    "UBER", "OLA", "ANI TECHNOLOGIES", "RAPIDO", "ROPPEN", "NAMMA YATRI",
    "MERU", "BLUSMART", "BLU SMART", "AUTODRIVER", "CAB"
  ],
  "Air_Rail_Bus": [
    "IRCTC", "INDIAN RAILWAYS", "MAKEMYTRIP", "MMT", "GOIBIBO", "EASEMYTRIP",
    "YATRA", "CLEARTRIP", "IXIGO", "RED BUS", "REDBUS", "ABHIBUS",
    "INDIGO", "INTERGLOBE", "AIR INDIA", "SPICEJET", "AKASA AIR", "VISTARA"
  ],
  "Fuel_Petroleum": [
    "HPCL", "HINDUSTAN PETROLEUM", "IOCL", "INDIAN OIL", "BPCL", "BHARAT PETROLEUM",
    "SHELL", "JIO-BP", "NAYARA", "PETROL PUMP", "PETROLEUM", "AUTO GAS"
  ],
  "Toll_Fastag_Transit": [
    "FASTAG", "NETC", "NHAI", "IHMCL", "TOLL PLAZA", "DMRC", "DELHI METRO",
    "MUMBAI METRO", "BMRCL", "BANGALORE METRO", "BEST BUS", "NMMT"
  ]
}
```

---

### D. Learning & Development / Education

```json
{
  "EdTech_OnlineCourses": [
    "COURSERA", "UDEMY", "UPGRAD", "UNACADEMY", "PHYSICSWALLAH", "PW", "BYJUS",
    "THINK AND LEARN", "VEDANTU", "SIMPLILEARN", "GREAT LEARNING", "SCALER",
    "INTERNSHALA", "LEAD SCHOOL", "EDX", "LINKEDIN LEARNING"
  ],
  "Institutions_Schools_Colleges": [
    "SCHOOL FEE", "COLLEGE FEE", "TUITION FEE", "EXAM FEE", "UNIVERSITY",
    "VIDYALANKAR", "SOMAIYA", "MANIPAL", "AMITY", "NARAYANA", "CHAITANYA",
    "FIITJEE", "ALLEN", "AARKAY", "RESONANCE", "AKASH INSTITUTE", "EASEBUZZ",
    "FEE COLLECTION", "CAMPUS", "ACADEMY", "INSTITUTE"
  ]
}
```

---

### E. Utilities, Telecom & Bills

```json
{
  "Electricity": [
    "BESCOM", "MSEB", "MSEDCL", "TATA POWER", "ADANI ELECTRICITY", "BSES RAJDHANI",
    "BSES YAMUNA", "UPPCL", "CESC", "TANGEDCO", "TSSPDCL", "DHBVN", "ELECTRICITY"
  ],
  "Gas_Water": [
    "INDANE", "HP GAS", "BHARAT GAS", "MAHANAGAR GAS", "MGL", "INDRAPRASTHA GAS",
    "IGL", "GUJARAT GAS", "ADANI TOTAL GAS", "WATER BOARD", "JAL BOARD", "BWSSB", "DJB"
  ],
  "Telecom_Broadband_DTH": [
    "AIRTEL", "BHARTI AIRTEL", "JIO", "RELIANCE JIO", "VODAFONE", "VI ", "BSNL",
    "ACT FIBERNET", "HATHWAY", "YOU BROADBAND", "TATA PLAY", "DISH TV", "SUN DIRECT", "BBPS"
  ]
}
```

---

### F. Charges & Fees (Bank & Penal)

```json
{
  "Bank_Service_Charges": [
    "MIN BAL CHG", "MINIMUM BALANCE", "CONSOLIDATED CHARGES", "MAB CHG",
    "SERVICE CHARGES", "LEDGER FOLIO CHG", "SMS CHARGES", "SMS ALERT FEE",
    "ANNUAL MAINTENANCE", "DEBIT CARD AMC", "ATM DECLINE CHARGE", "NON HOME BRANCH CHG"
  ],
  "Penal_Bounce_Charges": [
    "PENAL CHARGES", "OVERDUE CHARGES", "BOUNCE CHARGE", "RETURN CHARGE",
    "ECS RETURN", "NACH RETURN", "CHEQUE RETURN CHARGES", "INSUFFICIENT FUNDS CHG",
    "LATE PAYMENT FEE", "FINANCE CHARGE"
  ],
  "Forex_Government_Tax": [
    "FOREX MARKUP", "CROSS CURRENCY MARKUP", "GST ON CHARGES", "CGST", "SGST", "IGST"
  ]
}
```

---

## 3. HOW TO INTEGRATE INTO YOUR PIPELINE

You can directly merge these patterns into `Feature Extraction/src/engines/rules_config.json` under `taxonomies.NEEDS`, `taxonomies.WANTS`, and a new `taxonomies.CHARGES_AND_FEES` section!
