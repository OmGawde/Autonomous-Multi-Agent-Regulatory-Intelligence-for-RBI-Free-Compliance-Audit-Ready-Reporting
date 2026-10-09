"""
UPI VPA (Virtual Payment Address) & Merchant Intelligence Registry.

Provides deterministic Tier-2 matching for UPI narrations by extracting
and classifying the UPI ID / merchant handle (e.g., merchant@bank, payee@handle)
bypassing SLM latency and eliminating classification drift.
"""

import re
from typing import Optional, Dict, Any, Tuple

# VPA Pattern: matches standard Indian UPI identifiers (e.g. name@bank, merchant.123@okaxis)
VPA_REGEX = re.compile(r'([a-zA-Z0-9\.\-_]{2,50}@[a-zA-Z0-9\.\-_]{2,30})', re.IGNORECASE)

# Mapping of handle patterns, prefixes, or exact merchant strings to metadata
# Format: key -> (category, subcategory, needs_wants, canonical_merchant_name, confidence)
VPA_MERCHANT_DIRECTORY = {
    # -------------------------------------------------------------
    # Investments & Capital Markets (Wealth Building)
    # -------------------------------------------------------------
    "zerodha": ("Investment", "Stocks & Trading", "Not Applicable", "Zerodha", 0.95),
    "groww": ("Investment", "Mutual Funds & Stocks", "Not Applicable", "Groww", 0.95),
    "angelbroking": ("Investment", "Stocks & Trading", "Not Applicable", "Angel One", 0.95),
    "angelone": ("Investment", "Stocks & Trading", "Not Applicable", "Angel One", 0.95),
    "upstox": ("Investment", "Stocks & Trading", "Not Applicable", "Upstox", 0.95),
    "paytmmoney": ("Investment", "Mutual Funds", "Not Applicable", "Paytm Money", 0.95),
    "kuvera": ("Investment", "Mutual Funds", "Not Applicable", "Kuvera", 0.95),
    "camsonline": ("Investment", "Mutual Funds", "Not Applicable", "CAMS", 0.95),
    "kfintech": ("Investment", "Mutual Funds", "Not Applicable", "KFintech", 0.95),
    "npscams": ("Investment", "National Pension Scheme (NPS)", "Not Applicable", "NPS", 0.95),
    "npstrust": ("Investment", "National Pension Scheme (NPS)", "Not Applicable", "NPS", 0.95),
    "icicidirect": ("Investment", "Stocks & Trading", "Not Applicable", "ICICI Direct", 0.95),
    "motilaloswal": ("Investment", "Stocks & Trading", "Not Applicable", "Motilal Oswal", 0.95),
    "hdfcsec": ("Investment", "Stocks & Trading", "Not Applicable", "HDFC Securities", 0.95),
    "utimf": ("Investment", "Mutual Funds", "Not Applicable", "UTI Mutual Fund", 0.95),
    "uti.mf": ("Investment", "Mutual Funds", "Not Applicable", "UTI Mutual Fund", 0.95),
    "nippon": ("Investment", "Mutual Funds", "Not Applicable", "Nippon India Mutual Fund", 0.92),
    "sbi.mf": ("Investment", "Mutual Funds", "Not Applicable", "SBI Mutual Fund", 0.95),
    "hdfcmf": ("Investment", "Mutual Funds", "Not Applicable", "HDFC Mutual Fund", 0.95),
    "ppfas": ("Investment", "Mutual Funds", "Not Applicable", "Parag Parikh Mutual Fund", 0.95),

    # -------------------------------------------------------------
    # Credit Cards & Loan EMIs (Debt Obligations)
    # -------------------------------------------------------------
    "cred": ("Expense", "Credit Card Payment", "Need", "CRED", 0.96),
    "kreditbee": ("Expense", "Loan EMI", "Need", "KreditBee", 0.95),
    "fibe": ("Expense", "Loan EMI", "Need", "Fibe (EarlySalary)", 0.95),
    "earlysalary": ("Expense", "Loan EMI", "Need", "Fibe (EarlySalary)", 0.95),
    "moneyview": ("Expense", "Loan EMI", "Need", "Moneyview", 0.95),
    "navi": ("Expense", "Loan EMI", "Need", "Navi", 0.95),
    "bajajfinserv": ("Expense", "Loan EMI", "Need", "Bajaj Finance", 0.96),
    "bajajfinance": ("Expense", "Loan EMI", "Need", "Bajaj Finance", 0.96),
    "tatacapital": ("Expense", "Loan EMI", "Need", "Tata Capital", 0.95),
    "hdbfs": ("Expense", "Loan EMI", "Need", "HDB Financial Services", 0.95),
    "chola": ("Expense", "Loan EMI", "Need", "Cholamandalam Finance", 0.95),
    "muthoot": ("Expense", "Gold Loan EMI", "Need", "Muthoot Finance", 0.95),
    "manappuram": ("Expense", "Gold Loan EMI", "Need", "Manappuram Finance", 0.95),
    "sbicard": ("Expense", "Credit Card Payment", "Need", "SBI Card", 0.96),
    "hdfcbankcard": ("Expense", "Credit Card Payment", "Need", "HDFC Credit Card", 0.96),
    "axiscards": ("Expense", "Credit Card Payment", "Need", "Axis Bank Credit Card", 0.96),
    "icicibankcards": ("Expense", "Credit Card Payment", "Need", "ICICI Credit Card", 0.96),
    "kotakcards": ("Expense", "Credit Card Payment", "Need", "Kotak Credit Card", 0.96),
    "indusindcards": ("Expense", "Credit Card Payment", "Need", "IndusInd Credit Card", 0.96),
    "rblcards": ("Expense", "Credit Card Payment", "Need", "RBL Bank Credit Card", 0.96),
    "bobfinancial": ("Expense", "Credit Card Payment", "Need", "BOB Credit Card", 0.96),
    "slice": ("Expense", "Credit Card Payment", "Need", "Slice", 0.94),
    "unicard": ("Expense", "Credit Card Payment", "Need", "Uni Cards", 0.94),
    "uni.cards": ("Expense", "Credit Card Payment", "Need", "Uni Cards", 0.94),
    "onecard": ("Expense", "Credit Card Payment", "Need", "OneCard", 0.96),

    # -------------------------------------------------------------
    # Utilities & Essential Services (Needs)
    # -------------------------------------------------------------
    "tatapower": ("Expense", "Electricity", "Need", "Tata Power", 0.95),
    "bescom": ("Expense", "Electricity", "Need", "BESCOM", 0.95),
    "mahavitaran": ("Expense", "Electricity", "Need", "MSEDCL", 0.95),
    "mseb": ("Expense", "Electricity", "Need", "MSEDCL", 0.95),
    "adanielectricity": ("Expense", "Electricity", "Need", "Adani Electricity", 0.95),
    "torrentpower": ("Expense", "Electricity", "Need", "Torrent Power", 0.95),
    "cesc": ("Expense", "Electricity", "Need", "CESC", 0.95),
    "airtel": ("Expense", "Telecom & Internet", "Need", "Airtel", 0.95),
    "jio": ("Expense", "Telecom & Internet", "Need", "Jio", 0.95),
    "vodafone": ("Expense", "Telecom & Internet", "Need", "Vodafone Idea", 0.95),
    "myvi": ("Expense", "Telecom & Internet", "Need", "Vodafone Idea", 0.95),
    "bsnl": ("Expense", "Telecom & Internet", "Need", "BSNL", 0.95),
    "actcorp": ("Expense", "Broadband", "Need", "ACT Fibernet", 0.95),
    "indane": ("Expense", "LPG Gas", "Need", "Indane Gas", 0.95),
    "bharatgas": ("Expense", "LPG Gas", "Need", "Bharat Gas", 0.95),
    "hpgas": ("Expense", "LPG Gas", "Need", "HP Gas", 0.95),
    "billdesk": ("Expense", "Utility Bills", "Need", "BillDesk", 0.92),
    "bbps": ("Expense", "Utility Bills", "Need", "Bharat BillPay", 0.92),

    # -------------------------------------------------------------
    # Food, Groceries & Quick Commerce (Needs vs Wants)
    # -------------------------------------------------------------
    "swiggy": ("Expense", "Food Delivery", "Want", "Swiggy", 0.95),
    "zomato": ("Expense", "Food Delivery", "Want", "Zomato", 0.95),
    "zepto": ("Expense", "Groceries", "Need", "Zepto", 0.95),
    "blinkit": ("Expense", "Groceries", "Need", "Blinkit", 0.95),
    "grofers": ("Expense", "Groceries", "Need", "Blinkit", 0.95),
    "instamart": ("Expense", "Groceries", "Need", "Instamart", 0.95),
    "bbdaily": ("Expense", "Groceries", "Need", "BigBasket Daily", 0.95),
    "bigbasket": ("Expense", "Groceries", "Need", "BigBasket", 0.95),
    "dunzo": ("Expense", "Groceries", "Need", "Dunzo", 0.95),
    "dmart": ("Expense", "Groceries", "Need", "DMart", 0.95),
    "naturebasket": ("Expense", "Groceries", "Need", "Nature's Basket", 0.95),
    "starquik": ("Expense", "Groceries", "Need", "StarQuik", 0.95),

    # -------------------------------------------------------------
    # Commute, Mobility & Travel (Needs vs Wants)
    # -------------------------------------------------------------
    "uber": ("Expense", "Commute & Travel", "Need", "Uber", 0.95),
    "ola": ("Expense", "Commute & Travel", "Need", "Ola", 0.95),
    "rapido": ("Expense", "Commute & Travel", "Need", "Rapido", 0.95),
    "irctc": ("Expense", "Commute & Travel", "Need", "IRCTC", 0.95),
    "makemytrip": ("Expense", "Travel & Vacation", "Want", "MakeMyTrip", 0.95),
    "goibibo": ("Expense", "Travel & Vacation", "Want", "Goibibo", 0.95),
    "easemytrip": ("Expense", "Travel & Vacation", "Want", "EaseMyTrip", 0.95),
    "redbus": ("Expense", "Commute & Travel", "Need", "redBus", 0.95),
    "fastag": ("Expense", "Tolls & FASTag", "Need", "FASTag", 0.96),
    "netc": ("Expense", "Tolls & FASTag", "Need", "FASTag", 0.96),

    # -------------------------------------------------------------
    # Shopping & E-Commerce (Wants)
    # -------------------------------------------------------------
    "amazon": ("Expense", "Shopping", "Want", "Amazon", 0.95),
    "flipkart": ("Expense", "Shopping", "Want", "Flipkart", 0.95),
    "myntra": ("Expense", "Shopping", "Want", "Myntra", 0.95),
    "nykaa": ("Expense", "Shopping", "Want", "Nykaa", 0.95),
    "meesho": ("Expense", "Shopping", "Want", "Meesho", 0.95),
    "ajio": ("Expense", "Shopping", "Want", "Ajio", 0.95),
    "tatacliq": ("Expense", "Shopping", "Want", "Tata CLiQ", 0.95),
    "croma": ("Expense", "Electronics", "Want", "Croma", 0.95),
    "reliancedigital": ("Expense", "Electronics", "Want", "Reliance Digital", 0.95),
    "bookmyshow": ("Expense", "Entertainment", "Want", "BookMyShow", 0.95),
    "pvrcinemas": ("Expense", "Entertainment", "Want", "PVR Cinemas", 0.95),
    "inoxcinemas": ("Expense", "Entertainment", "Want", "INOX Cinemas", 0.95),
    "netflix": ("Expense", "Entertainment", "Want", "Netflix", 0.96),
    "spotify": ("Expense", "Entertainment", "Want", "Spotify", 0.96),
    "hotstar": ("Expense", "Entertainment", "Want", "Disney+ Hotstar", 0.96),
}


def extract_vpa_from_text(text: str) -> Optional[str]:
    """Extracts the first valid UPI VPA / handle from description text."""
    if not text or "@" not in text:
        return None
    match = VPA_REGEX.search(text)
    if match:
        return match.group(1).strip()
    return None


def match_vpa_intelligence(description: str, debit: float, credit: float) -> Optional[Dict[str, Any]]:
    """
    Analyzes transaction description for UPI VPA and matches against merchant directory.
    Returns standard classification dict if high-confidence match found, else None.
    """
    vpa = extract_vpa_from_text(description)
    if not vpa:
        return None

    vpa_lower = vpa.lower()
    vpa_user, _, vpa_handle = vpa_lower.partition('@')

    for key, (category, subcategory, needs_wants, merchant, conf) in VPA_MERCHANT_DIRECTORY.items():
        # Check if key matches user portion or handle portion
        if key in vpa_user or key in vpa_handle:
            # Handle credit adjustments: if credit, and it's a shopping/dining merchant, it's a refund
            if credit > 0 and category == "Expense":
                return {
                    "category": "Income",
                    "subcategory": f"{merchant} Refund",
                    "merchant_entity": merchant,
                    "needs_wants": "Not Applicable",
                    "confidence": conf,
                    "classification_method": "vpa_merchant_intelligence",
                    "matched_rule": f"vpa_refund:{key}",
                    "matched_keyword": key,
                }

            return {
                "category": category,
                "subcategory": subcategory,
                "merchant_entity": merchant,
                "needs_wants": needs_wants,
                "confidence": conf,
                "classification_method": "vpa_merchant_intelligence",
                "matched_rule": f"vpa_match:{key}",
                "matched_keyword": key,
            }

    return None
