"""
Shared merchant keyword dictionaries — ONE master copy for all banks.

Source: bank_statement_parsing_reference.md
Note #2: "Wants, Investment, and Debt-BNPL/lender keyword lists are IDENTICAL
across all six banks — maintain ONE master dictionary and only swap the
rail-prefix regex per bank."

Brand names do not change across banks. Only the rail prefix / delimiter
syntax differs, which is handled in bank_rules.py.
"""

import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple


# ============================================================
# KEYWORD MATCHING
# ============================================================
# Keywords used to be tested with a bare substring `in`, which matched inside
# unrelated words and produced confidently-wrong categories on real statements:
#   "garlic"            -> LIC        -> Insurance
#   "SHALIMAR HOSPITALITY" -> HOSPITAL -> Healthcare
#   "Bandhan Bank"      -> DHAN       -> Investment
#   "Cable"             -> CAB        -> Taxi
#   "SALARY CREDIT..."  -> CRED       -> the CRED app
# Matching is now anchored on alphanumeric boundaries. Boundaries are only
# applied where the keyword itself starts/ends with an alphanumeric, so
# punctuation-bearing keys such as "SIP/" or "ACH-CR-" still match.

# Keywords that are legitimately contained in a longer, unrelated phrase.
# Matching that longer phrase suppresses the keyword.
KEYWORD_EXCLUSIONS: Dict[str, List[str]] = {
    "NAVI": ["NAVI MUMBAI"],
    "BEST": ["BEST BUY"],
    "PW": ["PW SOLUTIONS"],
    "RING": ["RING ROAD"],
    "DIGIT": ["DIGITAL"],
    "MMT": ["MMT/IMPS", "MMT/"],
}

# Bank names appear in most UPI/IMPS narrations as the *counterparty's* bank,
# not as a lender. Treating them as loan keywords turned ordinary purchases
# into home loans -- e.g. "UPI/P2M/.../HAPPY FRUIT JUICE CEN/juice/HDFC BANK
# LTD" (Rs 90) was booked as a Home Loan EMI, and eleven such rows became six
# fictional Axis "home loans" with EMIs as low as Rs 75.89/month.
# These keywords only count when the narration also carries a lending signal.
LOAN_CONTEXT_TOKENS = [
    "EMI", "LOAN", "DISB", "ACH", "NACH", "ECS", "MANDATE",
    "REPAY", "INSTAL", "ADVANCE", "FORECLOS",
]

KEYWORD_REQUIRED_CONTEXT: Dict[str, List[str]] = {
    kw: LOAN_CONTEXT_TOKENS
    for kw in [
        "HDFC BANK", "ICICI BANK", "AXIS BANK", "KOTAK MAHINDRA", "KOTAK BANK",
        "STATE BANK", "SBI", "BANK OF BARODA", "BANK OF INDIA", "UNION BANK",
        "PUNJAB NATIONAL", "IDFC FIRST", "INDUSIND", "YES BANK", "RBL BANK",
        "FEDERAL BANK", "CANARA BANK", "BANDHAN BANK", "AU SMALL",
    ]
}


# ============================================================
# UPI REMARK DICTIONARY
# ============================================================
# The remark is the free-text note the payer typed into their UPI app. It is the
# only description of *purpose* a person-to-merchant payment carries -- the payee
# is usually a small local trader that appears in no merchant dictionary.
#
# Two properties drive the design:
#   * remarks are truncated to roughly 6-10 characters ("medici", "societ",
#     "shampo", "transfe"), so matching must be by PREFIX, not equality
#   * they are user-typed, so coverage is partial and always will be
#
# Anything not matched here resolves to Unknown. That is deliberate: the previous
# behaviour labelled every unmatched merchant payment "Want", which inflated one
# statement's discretionary spend by roughly 3-5x.
REMARK_NEED_PREFIXES = [
    # groceries and staples
    "milk", "curd", "dahi", "oil", "ghee", "butter", "bread", "wheat", "atta",
    "rice", "dal", "sugar", "salt", "banana", "apple", "fruit", "veg", "sabzi",
    "kirana", "grocer", "chees", "lassi", "paneer", "egg", "masala", "coconu",
    "olive", "1 kg", "2 kg",
    # household and toiletries
    "dettol", "soap", "shampo", "towel", "detergen", "det pd", "hand w",
    "brush", "paste", "tissue", "napkin", "phenyl", "harpic",
    # healthcare
    "medici", "medicin", "tablet", "eye dr", "eye do", "specs", "spectac",
    "arthre", "arthrel", "doctor", "clinic", "hospit", "pharma", "chemist",
    "nepa ey", "test", "2 teste", "xray", "scan",
    # utilities and housing
    "cable", "cabale", "societ", "maint", "electric", "water", "gas cyl",
    "rent", "wifi", "broadb", "recharg", "bill", "billdesk",
    # transport
    "taxi", "auto", "rickshaw", "railwa", "train", "ticket", "bus", "petrol",
    "diesel", "fuel", "maruti", "parking", "toll", "payvia",
    # work and education
    "zerox", "xerox", "print", "photoco", "stationer", "book", "notebook",
    "fee", "tuition", "school", "colleg", "legal",
]

REMARK_WANT_PREFIXES = [
    # eating out
    "lunch", "dinner", "breakfa", "tea", "coffee", "snack", "sandwic", "bhel",
    "biryan", "pizza", "burger", "cake", "sweet", "laddu", "icecrea", "ice cr",
    "chocola", "juice", "cold dr", "hotel", "restau", "canteen", "cater",
    # apparel and personal
    "shirt", "t shirt", "dress", "sadra", "tailor", "cloth", "jean", "saree",
    "kurta", "shoe", "chappal", "bag", "watch", "salon", "parlour", "haircut",
    # leisure and gifting
    "buke", "bouque", "flower", "gift", "movie", "cinema", "game", "toy",
    "lyric", "4 lyri", "party", "picnic",
]

# Remarks that carry no purpose information at all.
REMARK_UNINFORMATIVE = [
    "upi", "payment", "paymen", "pay", "pay to", "payvia", "transf", "transfe",
    "transfer", "to", "for", "na", "n/a", "-", "cash", "amount", "amt", "money",
    "send", "sent", "recv", "received", "self", "test",
]


@lru_cache(maxsize=4096)
def classify_remark(remark: str) -> str:
    """
    Map a UPI remark to "Need", "Want" or "Unknown".

    Longest matching prefix wins, so "eye dr" beats "eye" and "1 kg ap" is not
    mistaken for a bare "apple". Returns "Unknown" when nothing matches -- an
    honest third state rather than a guess.
    """
    r = (remark or "").strip().lower()
    if not r or r in REMARK_UNINFORMATIVE:
        return "Unknown"

    best_len, best_label = 0, "Unknown"
    for prefixes, label in ((REMARK_NEED_PREFIXES, "Need"), (REMARK_WANT_PREFIXES, "Want")):
        for p in prefixes:
            if r.startswith(p) and len(p) > best_len:
                best_len, best_label = len(p), label
    return best_label


@lru_cache(maxsize=8192)
def _keyword_regex(keyword: str) -> re.Pattern:
    """Compile a boundary-anchored matcher for a single keyword."""
    kw = keyword.strip()
    esc = re.escape(kw)
    left = r"(?<![A-Za-z0-9])" if kw[:1].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if kw[-1:].isalnum() else ""
    return re.compile(left + esc + right, re.IGNORECASE)


def keyword_matches(keyword: str, description: str) -> bool:
    """True if `keyword` occurs in `description` as a whole token."""
    kw = keyword.strip()
    if not kw:
        return False
    desc_upper = description.upper()

    for bad in KEYWORD_EXCLUSIONS.get(kw.upper(), []):
        if bad.upper() in desc_upper:
            return False

    required = KEYWORD_REQUIRED_CONTEXT.get(kw.upper())
    if required and not any(tok in desc_upper for tok in required):
        return False

    if _keyword_regex(kw).search(description):
        return True

    # UPI VPAs and handles run words together ("bajajfinanceltd",
    # "hdfcergo@icici"), so a spaced keyword never matches them. Retry
    # multi-word keywords against a de-spaced copy of the narration, anchoring
    # only on the left -- a trailing "ltd"/"pvt" is alphanumeric and would
    # otherwise block the match.
    if " " in kw:
        squashed = re.sub(r"[\s\-_.]", "", description)
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw.replace(" ", "")), re.IGNORECASE)
        return bool(pattern.search(squashed))

    return False


def find_truncated_match(keywords: List[str], value: str, min_len: int = 6) -> Optional[str]:
    """
    Match a bank-truncated field against a full keyword.

    Banks clip the payee and remark fields to a fixed width, so the statement
    carries "Google I" for Google India and "V V TRADE" for V V Traders. Exact
    and boundary matching both fail on those. Here the *value* is treated as a
    prefix of the keyword, which is the opposite direction to normal matching.

    Deliberately scoped to short structured fields (payee, remark) rather than
    whole narrations, and floored at `min_len` characters so short fragments
    cannot match half the dictionary.
    """
    v = (value or "").strip().upper()
    if len(v) < min_len:
        return None
    best = None
    for kw in keywords:
        k = kw.upper()
        if k.startswith(v) and (best is None or len(kw) > len(best)):
            best = kw
    return best


def find_longest_match(keywords: List[str], description: str) -> Optional[str]:
    """
    Return the longest keyword in `keywords` that matches `description`.

    Longest-match-wins replaces first-match-wins, which made the result depend
    on a keyword's position in a literal dict rather than on how specific it is.
    """
    best = None
    for kw in keywords:
        if keyword_matches(kw, description) and (best is None or len(kw) > len(best)):
            best = kw
    return best


# ============================================================
# NEEDS KEYWORDS — Essential spending categories
# ============================================================
NEEDS_KEYWORDS: Dict[str, List[str]] = {
    "Rent": [
        "RENTPAY", "NOBROKER", "CRED RENT", "HOUSING.COM", "RENT ", "HOUSE RENT", "FLAT RENT", "ROOM RENT",
    ],
    "Home Loan EMI": [
        "HL EMI", "HOUSING LOAN", "HOME LOAN", "HDFC HL", "SBI HL",
        "HDFC BANK", "HDFCBANKLTD", "LIC HOUSING", "PNB HOUSING",
    ],
    "Retail Loan EMI": [
        "RASMECCC NAVI MUMBAI", "RASMECCC", "RETAIL ASSET", "RETAIL ASSETS", "SME CREDIT",
    ],
    "Society / Property Tax": [
        "MAINT", "BBMP", "MCGM", "MUNICIPAL", "PROPERTY TAX", "SOCIETY", "CHSL", "MAINTENANCE",
    ],
    "Grocery / Supermarket": [
        "BIGBASKET", "BLINKIT", "ZEPTO", "DMART", "RELIANCE FRESH",
        "RELIANCE SMART", "MORE RETAIL", "SPENCERS", "NATURES BASKET", "INSTAMART",
        "GROFERS", "SUPERMARKET", "GROCERY", "MILK BASKET", "COUNTRY DELIGHT", "OTIPY", "BB NOW",
    ],
    "Electricity / Water / Gas": [
        "BBPS", "BESCOM", "MSEB", "MAHADISCOM", "TATA POWER", "ADANI ELECTRICITY",
        "INDANE", "HP GAS", "BHARAT GAS", "ELECTRICITY", "WATER BOARD",
        "IGL ", "MGL ", "GUJARAT GAS", "CESC", "KSEB", "TSSPDCL", "BWSSB", "DJB",
    ],
    "Internet / Mobile / Broadband": [
        "AIRTEL", "JIO", "VODAFONE", "VODAFONE IDEA", "VI POSTPAID", "VI PREPAID",
        "ACT FIBERNET", "BSNL",
        "TATA PLAY", "DTH", "SUN DIRECT", "DISH TV", "HATHWAY", "EXCITEL", "JIOFIBER",
    ],
    "Fuel": [
        "HPCL", "IOCL", "BPCL", "INDIAN OIL", "PETROLEUM", "SHELL", "AUTO FUEL", "NAYARA", "JIO-BP",
    ],
    "Metro / Bus / Toll / Parking": [
        "DMRC", "NMMT", "BEST", "FASTAG", "NHAI", "NCMC", "METRO", "PARKING", "NETC", "ICICI FASTAG", "PAYTM FASTAG",
    ],
    "Taxi": [
        "UBER", "OLA", "RAPIDO", "MERU", "BLUSMART", "CAB", "INDRIVE", "NAMMA YATRI",
    ],
    "Healthcare": [
        "APOLLO", "FORTIS", "MAX HEALTHCARE", "1MG", "TATA 1MG", "PHARMEASY",
        "NETMEDS", "MEDPLUS", "HOSPITAL", "CLINIC", "PHARMACY", "PATHKIND",
        "LAL PATH", "DIAGNOSTICS", "CULT.FIT", "CULTFIT", "THYROCARE", "METROPOLIS", "SRL DIAGNOSTICS",
    ],
    "Insurance": [
        "LIC", "STAR HEALTH", "NIVA BUPA", "ACKO", "DIGIT",
        "MEDICLAIM", "BAJAJ ALLI", "HDFC ERGO", "ICICI LOMBARD",
        "POLICYBAZAAR", "INSURANCE", "CARE HEALTH", "MAX LIFE", "TATA AIA", "SBI LIFE",
    ],
    "Education": [
        "BYJU", "UNACADEMY", "PHYSICS WALLAH", "VEDANTU", "EASEBUZZ",
        "SCHOOL", "COLLEGE", "UNIVERSITY", "TUITION", "FEE", "COURSERA", "UDEMY",
    ],
    # A card bill is a liability settlement, not an amortising loan instalment.
    # Leaving it in Loan / EMI put Rs 2,67,810 of SBI card repayments into the
    # EMI total -- 91% of that bank's entire reported EMI burden -- and made
    # one card look like three separate loans to the debt engine.
    "Credit Card Repayment": [
        "CREDIT CARD PAYMENT", "CC PAYMENT", "BILLDESK-CC", "CREDIT CARD BILL",
        "CARD PAYMENT", "CC BILL PAY", "AUTOPAY CC",
    ],
    "Loan / EMI": [
        "MUTHOOT", "MANAPPURAM", "BAJAJ FINANCE",
        "BAJAJ FINSERV", "CHOLAMANDALAM", "CHOLA", "HDB FINANCIAL", "HDBFS",
        "HOME CREDIT", "IDFC FIRST", "KREDITBEE", "MONEYVIEW", "NAVI",
        "POONAWALLA", "SLICE", "SIMPL", "LAZYPAY", "ZESTMONEY", "LOAN EMI",
        "FINANCE", "FINSERV", "CAPITAL", "LENDINGKART",
        # Housing finance companies. "LIC HFL"/"LIC HOUSING" must be listed
        # here so they outrank the bare "LIC" insurance keyword on length.
        "LIC HFL", "LIC HOUSING", "PNB HOUSING", "INDIABULLS HOUSING",
        "CAN FIN HOMES", "REPCO HOME", "SUNDARAM HOME", "ADITYA BIRLA FINANCE",
        "TATA CAPITAL", "L&T FINANCE", "SHRIRAM FINANCE", "MAHINDRA FINANCE",
        "EMI DEBIT", "EMI PAYMENT", "LOAN REPAY", "LOAN INSTAL", "TERM LOAN",
    ],
}

# ============================================================
# WANTS KEYWORDS — Discretionary spending
# ============================================================
WANTS_KEYWORDS: Dict[str, List[str]] = {
    "Food Delivery": [
        "SWIGGY", "BUNDL TECHNOLOGIES", "ZOMATO", "ETERNAL",
        "TATA STARBUCKS", "STARBUCKS", "CAFE", "DOMINOS", "JUBILANT",
        "MCDONALD", "KFC", "BURGER KING", "CHAAYOS", "CHAI POINT",
        "RESTAURANT", "EATS", "BAKERY", "PIZZA", "EATSURE", "DINE OUT", "BLUE TOKAI", "THIRD WAVE",
    ],
    "Entertainment": [
        "NETFLIX", "AMAZON PRIME", "DISNEY", "HOTSTAR", "SPOTIFY",
        "YOUTUBE PREMIUM", "SONY LIV", "ZEE5", "APPLE MUSIC", "JIOCINEMA", "AUDIBLE",
        # App-store billing; statements show the truncated "Google I".
        "GOOGLE INDIA", "GOOGLE PLAY", "PLAYSTORE",
    ],
    "Shopping": [
        "AMAZON", "ASSPL", "FLIPKART", "FKRT", "MYNTRA", "AJIO",
        "NYKAA", "FSN E-COMMERCE", "MEESHO", "FASHNEAR", "TATA CLIQ",
        "JIOMART", "SNAPDEAL", "TATA NEU", "SHOPPERS", "LIFESTYLE", "DECATHLON",
    ],
    "Courier / Logistics": [
        "XPRESSBEE", "XPRESSBEES", "DELHIVERY", "BLUEDART", "BLUE DART",
        "DTDC", "ECOM EXPRESS", "SHADOWFAX", "INDIA POST", "PROFESSIONAL COURIER",
    ],
    "Travel": [
        "MAKEMYTRIP", "MMT", "AIRBNB", "IRCTC", "INDIGO",
        "AIR INDIA", "VISTARA", "OYO", "AKASA", "SPICEJET", "GOIBIBO",
        "CLEARTRIP", "EASEMYTRIP", "YATRA", "HOTEL", "RESORT", "REDBUS", "ABHIBUS",
        # Indian tour operators. Without these, a Rs 3,30,750 holiday package
        # paid by cheque was labelled by its payment instrument ("Cheque"), and
        # the Travel subcategory held zero rows on every bank examined.
        "VEENA PATIL", "VEENA WORLD", "THOMAS COOK", "SOTC", "KESARI",
        "COX & KINGS", "TRAVELS", "TOURS", "TOURISM", "HOLIDAYS",
    ],
    "Leisure": [
        "BOOKMYSHOW", "PVR", "INOX", "STEAM", "PLAYSTATION",
        "IMAGICA", "CLUB", "GAMING", "RESORT", "CINEPOLIS", "XBOX",
    ],
    "Electronics": [
        # Bare "APPLE" matched fruit purchases ("apple", "1 kg ap") and booked
        # them as Electronics. Only unambiguous Apple Inc. forms are listed.
        "APPLE.COM", "APPLE STORE", "APPLE INDIA", "ITUNES",
        "SAMSUNG", "CROMA", "INFINITY RETAIL", "RELIANCE DIGITAL",
        "VIJAY SALES", "ONEPLUS", "XIAOMI", "DELL", "HP STORE",
    ],
    "Fashion": [
        "H&M", "ZARA", "LIFESTYLE", "SHOPPERS STOP", "WESTSIDE",
        "UNQLO", "UNIQLO", "TRENDS", "RELIANCE TRENDS",
    ],
    "Beauty": [
        "LAKME SALON", "LAKME", "PURPLLE", "SPA", "SALON", "PARLOUR",
    ],
    "Luxury": [
        "TANISHQ", "KALYAN JEWELLERS", "KALYAN", "TITAN", "TITAN COMPANY",
        "MALABAR", "JOYALUKKAS", "JEWEL",
    ],
}

# Truncated variants for Finacle banks (BOI / Union / BOB)
# .md Note #3: "use partial/fuzzy string matching"
TRUNCATED_WANTS_VARIANTS: Dict[str, str] = {
    "SWIGG": "Swiggy",
    "PRIME": "Amazon Prime",
    "YOUTUBE": "YouTube Premium",
}

# ============================================================
# INVESTMENT KEYWORDS
# ============================================================
INVESTMENT_KEYWORDS: Dict[str, List[str]] = {
    "Mutual Funds / SIP": [
        "SIP/", "BSE SMALLCASE", "NSE NMF", "CAMS", "KFINTECH",
        "BILLDESK-MF", "NACH-MF", "MUTUAL FUND", "MF DEPOSIT", "INFRA-MF",
        "NIPPON", "SBIMF", "HDFCMF", "ICICIMF", "AXISMF", "UTIMF", "DSPMF",
        "MIRAE", "PARAG PARIKH", "PPFAS", "SMALLCASE",
    ],
    "Zerodha": ["ZERODHA", "ZERODHA COIN"],
    "Groww": ["GROWW", "NEXTBILLION TECHNOLOGY", "NEXTBILLION"],
    "Upstox": ["UPSTOX", "RKSV SECURITIES", "RKSV"],
    "Angel One": ["ANGEL ONE", "ANGEL BROKING", "ANGELONE"],
    "5Paisa": ["5PAISA"],
    "Sharekhan": ["SHAREKHAN"],
    "Motilal Oswal": ["MOTILAL OSWAL", "MOTILAL"],
    "ICICI Direct": ["ICICI DIRECT", "ICICIDIRECT", "EBA/MFP", "EBA/EQ"],
    "HDFC Securities": ["HDFC SECURITIES", "HDFCSEC"],
    "Kotak Securities": ["KOTAK SECURITIES", "KOTAKSEC"],
    "INDmoney": ["INDMONEY"],
    "ET Money": ["ET MONEY", "BILLIONLOOP"],
    "Dhan": ["DHAN"],
    "Paytm Money": ["PAYTM MONEY"],
    "PPF": ["PPF DEPOSIT", "PPF SBI", "TO PPF A/C", "PPF"],
    "NPS": ["NPS TRUST", "NSDL-NPS", "PROTEAN NPS", "CRA-NPS", "NPS"],
    "FD / RD": ["FD BOOKED", "TD ACCOUNT", "RD INSTALLMENT", "TERM DEPOSIT", "FIXED DEPOSIT"],
    "Bonds / SGB": ["SGB", "RBI BOND", "SOVEREIGN GOLD BOND", "WINT WEALTH", "BOND"],
    "Equity Trading": ["EQ TRADE", "EQUITY", "SHARE TRADING"],
    "Dividend": ["DIVIDEND", "DIV CR"],
}

# ============================================================
# SAVINGS SIGNAL KEYWORDS
# ============================================================
SAVINGS_SIGNAL_KEYWORDS: List[str] = [
    "RD INSTALLMENT", "SWEEP-IN", "AUTO SWEEP", "TD ACCOUNT", "MOD BAL",
]

# ============================================================
# INCOME KEYWORDS — patterns that identify credit sources
# ============================================================
INCOME_KEYWORDS: Dict[str, List[str]] = {
    "Salary": [
        "SALARY", "SAL CREDIT", "SAL CR", "PAYROLL", "STIPEND",
        "REMUNERATION", "COMPENSATION", "SALARY FOR", "MONTHLY SAL",
    ],
    "Interest": [
        "Int.Pd:", "INTEREST PAID", "INT CREDIT", "INTEREST", "INT.PD",
    ],
    "Dividend": [
        "DIVIDEND", "DIV ", "DIVIDEND CREDIT",
    ],
    "Refund / Reversal": [
        "REFUND", "REVERSAL", "RVSL", "CASHBACK", "RETURN", "CHARGE REVERSAL",
    ],
    "Government": [
        "PMJJBY", "PMSBY", "DIRECT BENEFIT", "DBT/", "GOVT",
    ],
}

# ============================================================
# BANKING / TRANSFER KEYWORDS
# ============================================================
BANKING_KEYWORDS: Dict[str, List[str]] = {
    "ATM Withdrawal": [
        "ATW", "ATM-CASH", "CWDR", "CASH WDL", "NFS/CASH WDL",
    ],
    "Cash Deposit": [
        "CASH DEP", "CDM", "CASH DEPOSIT MACHINE",
    ],
    "Cheque": [
        "CHQ PAID", "CHEQUE", "CLG",
    ],
    "Bank Charges": [
        "DCardfee", "AdminCharge", "CGST", "SGST", "SERVICE CHARGE",
        "SMS CHARGE", "ANNUAL FEE", "CONSOLIDATED CHARGE", "MIN BAL CHG",
        "MINIMUM BALANCE CHARGE", "FOREX MARKUP", "CARD FEE",
        # ICICI bills SMS/OTP alerts as CMS/<ref>/SMSOTP__<id>
        "SMSOTP", "SMS OTP", "ATMCARD AMC", "CARD AMC", "STATEMENT CHRG",
        "PHY STATEMENT", "DCARDFEE", "ADMINCHARGE",
    ],
    # Penal and return charges. These narrations contain RETURN/BOUNCE, which
    # matched INCOME_KEYWORDS["Refund / Reversal"] first under the old
    # first-match-wins scan and booked a bounce *fee* as income.
    "Penal Charges": [
        "RETURN CHARGE", "RETURN CHRG", "BOUNCE CHARGE", "BOUNCE CHG",
        "PENAL CHARGE", "PENAL INTEREST", "INSUFFICIENT FUND", "CHEQUE RETURN",
        "ECS RETURN", "NACH RETURN", "ACH RETURN", "NACH_AD_RTN", "DISHONOUR",
        "LATE PAYMENT FEE", "OVERDUE CHARGE",
    ],
    "Online Payment": [
        "ECOM", "POS ECOM", "ONLINE",
        # Payment aggregators and gateways, not merchants in themselves, but
        # they identify the rail and stop these rows sitting in a catch-all.
        # BillDesk alone is 26 rows across two spellings in one statement.
        "BILLDESK", "BILLDESKT", "BILLDESKTEZ", "EURONET", "EURONETGPAY",
        "RAZORPAY", "CCAVENUE", "PAYU", "BILLAVENUE", "ATOM TECH", "WORLDLINE",
    ],
}

# ============================================================
# MERCHANT ENTITY MAP — keyword → canonical merchant name
# ============================================================
MERCHANT_ENTITY_MAP: Dict[str, str] = {
    # Food Delivery
    "SWIGGY": "Swiggy",
    "SWIGG": "Swiggy",
    "BUNDL TECHNOLOGIES": "Swiggy",
    "ZOMATO": "Zomato",
    "ETERNAL": "Zomato",
    "TATA STARBUCKS": "Starbucks",

    # Entertainment
    "NETFLIX": "Netflix",
    "AMAZON PRIME": "Amazon Prime",
    "DISNEY": "Disney+ Hotstar",
    "SPOTIFY": "Spotify",
    "YOUTUBE PREMIUM": "YouTube Premium",

    # Shopping
    "AMAZON": "Amazon",
    "ASSPL": "Amazon",
    "FLIPKART": "Flipkart",
    "FKRT": "Flipkart",
    "MYNTRA": "Myntra",
    "AJIO": "Ajio",
    "NYKAA": "Nykaa",
    "FSN E-COMMERCE": "Nykaa",

    # Travel
    "MAKEMYTRIP": "MakeMyTrip",
    "MMT": "MakeMyTrip",
    "AIRBNB": "Airbnb",
    "IRCTC": "IRCTC",
    "INDIGO": "IndiGo Airlines",
    "AIR INDIA": "Air India",
    "VISTARA": "Vistara",
    "OYO": "OYO",

    # Leisure
    "BOOKMYSHOW": "BookMyShow",
    "PVR": "PVR Cinemas",
    "INOX": "INOX Cinemas",

    # Grocery
    "BIGBASKET": "BigBasket",
    "BLINKIT": "Blinkit",
    "ZEPTO": "Zepto",
    "DMART": "DMart",
    "RELIANCE FRESH": "Reliance Fresh",
    "MORE RETAIL": "More Retail",
    "SPENCERS": "Spencer's",

    # Taxi
    "UBER": "Uber",
    "OLA": "Ola",
    "RAPIDO": "Rapido",
    "MERU": "Meru",

    # Fuel
    "HPCL": "HPCL",
    "IOCL": "IOCL",
    "BPCL": "BPCL",
    "INDIAN OIL": "Indian Oil",

    # Telecom
    "AIRTEL": "Airtel",
    "JIO": "Jio",
    "VODAFONE": "Vodafone",
    "ACT FIBERNET": "ACT Fibernet",
    "BSNL": "BSNL",

    # Healthcare
    "APOLLO": "Apollo",
    "FORTIS": "Fortis",
    "MAX HEALTHCARE": "Max Healthcare",
    "1MG": "1mg",
    "PHARMEASY": "PharmEasy",
    "NETMEDS": "Netmeds",
    "MEDPLUS": "MedPlus",

    # Insurance
    "LIC": "LIC",
    "STAR HEALTH": "Star Health",
    "NIVA BUPA": "Niva Bupa",
    "ACKO": "Acko",
    "DIGIT": "Digit Insurance",
    "BAJAJ ALLI": "Bajaj Allianz",

    # Electronics
    "CROMA": "Croma",
    "INFINITY RETAIL": "Croma",
    "RELIANCE DIGITAL": "Reliance Digital",
    "SAMSUNG": "Samsung",

    # Fashion
    "H&M": "H&M",
    "ZARA": "Zara",
    "LIFESTYLE": "Lifestyle",
    "SHOPPERS STOP": "Shoppers Stop",
    "WESTSIDE": "Westside",

    # Beauty
    "LAKME SALON": "Lakme Salon",
    "LAKME": "Lakme",
    "PURPLLE": "Purplle",

    # Luxury
    "TANISHQ": "Tanishq",
    "KALYAN JEWELLERS": "Kalyan Jewellers",
    "KALYAN": "Kalyan Jewellers",
    "TITAN": "Titan",
    "TITAN COMPANY": "Titan",

    # Rent
    "RENTPAY": "RentPay",
    "NOBROKER": "NoBroker",
    "CRED RENT": "CRED Rent",
    "HOUSING.COM": "Housing.com",

    # Investments
    "ZERODHA": "Zerodha",
    "ZERODHA COIN": "Zerodha",
    "GROWW": "Groww",
    "NEXTBILLION TECHNOLOGY": "Groww",
    "NEXTBILLION": "Groww",
    "UPSTOX": "Upstox",
    "RKSV SECURITIES": "Upstox",
    "RKSV": "Upstox",
    "ANGEL ONE": "Angel One",
    "ANGEL BROKING": "Angel One",
    "ANGELONE": "Angel One",
    "5PAISA": "5Paisa",
    "SHAREKHAN": "Sharekhan",
    "MOTILAL OSWAL": "Motilal Oswal",
    "ICICI DIRECT": "ICICI Direct",
    "HDFC SECURITIES": "HDFC Securities",
    "KOTAK SECURITIES": "Kotak Securities",
    "INDMONEY": "INDmoney",
    "ET MONEY": "ET Money",
    "BILLIONLOOP": "ET Money",
    "CAMS": "CAMS",
    "KFINTECH": "KFintech",

    # Loan & Credit Cards
    "MUTHOOT": "Muthoot Finance",
    "MANAPPURAM": "Manappuram Finance",
    "BAJAJ FINANCE": "Bajaj Finance",
    "BAJAJ FINSERV": "Bajaj Finance",
    "CHOLAMANDALAM": "Cholamandalam Finance",
    "CHOLA": "Cholamandalam Finance",
    "HDB FINANCIAL": "HDB Financial Services",
    "HDBFS": "HDB Financial Services",
    "HOME CREDIT": "Home Credit",
    "IDFC FIRST": "IDFC FIRST Bank",
    "KREDITBEE": "KreditBee",
    "MONEYVIEW": "MoneyView",
    "NAVI": "Navi",
    "POONAWALLA": "Poonawalla Fincorp",
    "CRED": "CRED",
    "PAYTM": "Paytm",
    "PHONEPE": "PhonePe",
    "GOOGLEPAY": "Google Pay",
    "GPAY": "Google Pay",

    # Education & EdTech
    "COURSERA": "Coursera",
    "UDEMY": "Udemy",
    "UPGRAD": "upGrad",
    "UNACADEMY": "Unacademy",
    "PHYSICS WALLAH": "Physics Wallah",
    "PHYSICSWALLAH": "Physics Wallah",
    "PW": "Physics Wallah",
    "BYJU": "BYJU'S",
    "VEDANTU": "Vedantu",
    "SIMPLILEARN": "Simplilearn",
    "SCALER": "Scaler Academy",
    "GREAT LEARNING": "Great Learning",
    "INTERNSHALA": "Internshala",
    "EASEBUZZ": "Easebuzz Education Fee",

    # Quick Commerce & Grocery
    "BLINKIT": "Blinkit",
    "ZEPTO": "Zepto",
    "INSTAMART": "Swiggy Instamart",
    "BB NOW": "BigBasket Now",
    "BIGBASKET": "BigBasket",
    "DMART": "DMart",
    "AVENUE SUPERMARTS": "DMart",
    "COUNTRY DELIGHT": "Country Delight",
    "LICKIOUS": "Licious",
    "OTIPY": "Otipy",

    # Fashion & Retail
    "MEESHO": "Meesho",
    "FASHNEAR": "Meesho",
    "DECATHLON": "Decathlon",
    "SNITCH": "Snitch",
    "BEWAKOOF": "Bewakoof",
    "URBANIC": "Urbanic",

    # Utilities
    "TATA POWER": "Tata Power",
    "ADANI ELECTRICITY": "Adani Electricity",
    "BESCOM": "BESCOM Electricity",
    "MAHANAGAR GAS": "MGL Gas",
    "MGL": "MGL Gas",
    "INDRAPRASTHA GAS": "IGL Gas",
    "IGL": "IGL Gas",

    # BNPL
    "SIMPL": "Simpl",
    "LAZYPAY": "LazyPay",
    "ZESTMONEY": "ZestMoney",
    "SLICE": "Slice",
    "AMAZON PAY LATER": "Amazon Pay Later",
    "FLIPKART PAY LATER": "Flipkart Pay Later",
    "RING": "Ring Pay",

    # Toll & Transit
    "FASTAG": "FASTag",
    "NETC": "NETC FASTag",
    "DMRC": "Delhi Metro",
    "NMMT": "NMMT Transit",
    "BEST": "BEST Transit",
}


def get_all_keywords_flat() -> List[str]:
    """Return a flat list of all keywords for fuzzy matching corpus."""
    keywords: List[str] = []
    for kw_dict in [NEEDS_KEYWORDS, WANTS_KEYWORDS, INVESTMENT_KEYWORDS,
                    INCOME_KEYWORDS, BANKING_KEYWORDS]:
        for kw_list in kw_dict.values():
            keywords.extend(kw_list)
    return list(set(keywords))


def find_merchant_entity(description: str) -> Optional[str]:
    """
    Look up the canonical merchant name for a description.

    Uses boundary-anchored, longest-match-wins lookup. The previous bare
    substring scan returned whichever key happened to sit earliest in a
    170-entry literal, so "SALARY CREDIT FROM ..." resolved to the CRED app and
    "NEFT DIGITAL PAYMENTS" to Digit Insurance.
    """
    if not description:
        return None
    best_kw = find_longest_match(list(MERCHANT_ENTITY_MAP.keys()), description)
    return MERCHANT_ENTITY_MAP[best_kw] if best_kw else None
