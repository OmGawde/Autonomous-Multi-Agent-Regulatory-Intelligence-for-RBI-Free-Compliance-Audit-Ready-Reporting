"""
Bank-specific rules — rail patterns, description parsers, and keyword overrides.

Source: bank_statement_parsing_reference.md
Each bank has unique description/narration formats (rail prefixes, delimiters).
Merchant keywords are shared (merchant_rules.py); only the structural parsing
differs per bank.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Description parser functions — extract payee / VPA / ref
# ============================================================

def _safe_split(description: str, delimiter: str, max_parts: int = 10) -> List[str]:
    """Split description safely, returning empty strings for missing parts."""
    parts = description.split(delimiter, max_parts)
    return parts + [""] * (max_parts - len(parts))


# Bank / PSP names as they appear in a UPI narration's counterparty-bank field,
# including the truncated forms banks emit ("Union Ban", "Paytm Pay", "Bank of M").
_BANK_FIELD_RE = re.compile(
    r"bank|paytm|ybl|okaxis|okhdfc|okicici|oksbi|okbizaxis|apl|ibl|axl|"
    r"airtel|jio|fino|equitas|au small|idfc|indusind|federal|kotak|canara|"
    r"union|baroda|maharashtra|saraswat|cosmos|abhyudaya|district cent|"
    r"\bsbi\b|\bhdfc\b|\bicici\b|\baxis\b|\byes\b|\bpnb\b|\bboi\b|\bbob\b|"
    r"punjab|indian ban|central ban|uco|iob|karnataka|karur|tamilnad|"
    r"dbs|citi|hsbc|standard char|rbl|bandhan|ujjivan|jana |suryoday",
    re.IGNORECASE,
)


def looks_like_bank(value: str) -> bool:
    """True if a UPI narration field holds a bank/PSP name rather than a remark."""
    v = (value or "").strip()
    if not v:
        return False
    return bool(_BANK_FIELD_RE.search(v))


def sbi_parse_description(description: str) -> Dict[str, str]:
    """
    SBI rail format:
    TO TRANSFER-UPI/DR/<Ref>/<Payee Name>/<Bank>/<VPA>/<Remarks>
    BY TRANSFER-UPI/CR/<Ref>/<Payee Name>/<Bank>/<VPA>/<Remarks>
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": "",
              "is_p2m": False}
    desc_upper = description.upper()

    # Real SBI CBS narrations, which the "TRANSFER-UPI" pattern below never
    # matched. 45% of a real SBI statement fell through to the SLM at 0.3
    # confidence because none of these forms were handled:
    #   WDL TFR UPI/DR/<ref>/<payee>/<bank>/<vpa>/UPI <trailing branch text>
    #   DEP TFR UPI/CR/<ref>/<payee>/<bank>/<vpa>/UPI <trailing branch text>
    #   DEP TFR NEFT*<IFSC>*<ref>*<PAYER NAME> <trailing branch text>
    #   DEBIT ACHDr <mandate no> <PAYEE>
    #   DEBIT CMP MANDATE DEBIT <Lender> - DD
    m = re.search(r"(?:WDL|DEP)\s+TFR\s+UPI/(DR|CR)/([^/]*)/([^/]*)/([^/]*)/([^/]*)",
                  description, re.IGNORECASE)
    if m:
        result["rail"] = "UPI"
        result["ref"] = m.group(2).strip()
        result["payee"] = m.group(3).strip()
        result["vpa"] = m.group(5).strip()
        return result

    m = re.search(r"(?:WDL|DEP)\s+TFR\s+NEFT\*([^*]*)\*([^*]*)\*([^0-9]*)",
                  description, re.IGNORECASE)
    if m:
        result["rail"] = "NEFT"
        result["ref"] = m.group(2).strip()
        result["payee"] = m.group(3).strip()
        return result

    m = re.search(r"\bACHDr\s+\d*\s*(.+)$", description, re.IGNORECASE)
    if m:
        result["rail"] = "ACH"
        result["payee"] = m.group(1).strip()
        return result

    m = re.search(r"CMP\s+MANDATE\s+DEBIT\s+(.+?)(?:\s*-\s*DD)?$", description, re.IGNORECASE)
    if m:
        result["rail"] = "NACH"
        result["payee"] = m.group(1).strip()
        return result

    if "TRANSFER-UPI" in desc_upper:
        result["rail"] = "UPI"
        parts = _safe_split(description, "/")
        if len(parts) >= 4:
            result["ref"] = parts[2] if len(parts) > 2 else ""
            result["payee"] = parts[3] if len(parts) > 3 else ""
            result["vpa"] = parts[5] if len(parts) > 5 else ""
            result["remarks"] = parts[6] if len(parts) > 6 else ""
    elif desc_upper.startswith("NEFT"):
        result["rail"] = "NEFT"
    elif desc_upper.startswith("ECS") or "ECS DR" in desc_upper or "ECS CR" in desc_upper:
        result["rail"] = "ECS"
    elif "NACH" in desc_upper:
        result["rail"] = "NACH"
    elif "IMPS" in desc_upper:
        result["rail"] = "IMPS"
    elif desc_upper.startswith("ATW") or "ATM" in desc_upper:
        result["rail"] = "ATM"

    return result


def icici_parse_description(description: str) -> Dict[str, str]:
    """
    ICICI rail formats:
    UPI/<Ref No>/<Remarks>/<Payee VPA>/<Payee Bank>
    UPI/<Payee Name>/<Ref>
    BIL/NEFT/<NEFT Ref>/<Payee>/<Payee Bank>
    MMT/IMPS/<Ref>/<Payee>/<IFSC>
    ACH/<Lender>/<Account>/<Ref>
    EBA/MFP-<Parent Ref>-<Sub Ref>-S-<...>  (ICICI Direct MF/SIP)
    EBA/EQ Trade <Date>/<Timestamp>          (ICICI Direct Equity)
    CAM/<Branch>/<Type>/<Date>               (ATM)
    CMS/<Ref>/<Details>                      (Auto-debit)
    CLG/<Payee>/<Bank - Cheque No>           (Clearing/Cheque)
    NFS/CASH WDL/<Ref>/<...>                 (Other bank ATM)
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": ""}
    desc_upper = description.upper()

    if desc_upper.startswith("UPI/"):
        result["rail"] = "UPI"
        parts = _safe_split(description, "/")
        if len(parts) >= 3:
            result["ref"] = parts[1] if len(parts) > 1 else ""
            result["payee"] = parts[1] if len(parts) > 1 else ""
            result["remarks"] = parts[2] if len(parts) > 2 else ""
            result["vpa"] = parts[3] if len(parts) > 3 else ""
    elif desc_upper.startswith("BIL/NEFT/"):
        result["rail"] = "NEFT"
        parts = _safe_split(description, "/")
        if len(parts) >= 4:
            result["ref"] = parts[2] if len(parts) > 2 else ""
            result["payee"] = parts[3] if len(parts) > 3 else ""
    elif desc_upper.startswith("MMT/IMPS/"):
        result["rail"] = "IMPS"
        parts = _safe_split(description, "/")
        if len(parts) >= 4:
            result["ref"] = parts[2] if len(parts) > 2 else ""
            result["payee"] = parts[3] if len(parts) > 3 else ""
    elif desc_upper.startswith("ACH/"):
        result["rail"] = "ACH"
        parts = _safe_split(description, "/")
        if len(parts) >= 2:
            result["payee"] = parts[1] if len(parts) > 1 else ""
            result["ref"] = parts[2] if len(parts) > 2 else ""
    elif desc_upper.startswith("EBA/MFP-"):
        result["rail"] = "EBA_MF"
        result["ref"] = description
    elif desc_upper.startswith("EBA/EQ TRADE"):
        result["rail"] = "EBA_EQ"
        result["ref"] = description
    elif desc_upper.startswith("CAM/") or desc_upper.startswith("NFS/CASH WDL"):
        result["rail"] = "ATM"
    elif desc_upper.startswith("CMS/"):
        result["rail"] = "CMS"
        parts = _safe_split(description, "/")
        if len(parts) >= 2:
            result["ref"] = parts[1] if len(parts) > 1 else ""
    elif desc_upper.startswith("CLG/"):
        result["rail"] = "CLG"
        parts = _safe_split(description, "/")
        if len(parts) >= 2:
            result["payee"] = parts[1] if len(parts) > 1 else ""
    elif desc_upper.startswith("BIL/ONL/"):
        result["rail"] = "ONLINE"
        parts = _safe_split(description, "/")
        if len(parts) >= 4:
            result["ref"] = parts[2] if len(parts) > 2 else ""
            result["payee"] = parts[3] if len(parts) > 3 else ""
    elif desc_upper.startswith("NEFT-"):
        result["rail"] = "NEFT"
        parts = description.split("-", 3)
        if len(parts) >= 3:
            result["ref"] = parts[1] if len(parts) > 1 else ""
            result["payee"] = parts[2] if len(parts) > 2 else ""
    elif "INT.PD:" in desc_upper or "INTEREST" in desc_upper:
        result["rail"] = "INTEREST"
    elif "PMJJBY" in desc_upper or "PMSBY" in desc_upper:
        result["rail"] = "GOVT_SCHEME"

    return result


def axis_parse_description(description: str) -> Dict[str, str]:
    """
    Axis rail format:
    UPI/P2M/<Ref>/<Merchant Name>/<VPA>    (merchant payment)
    UPI/<Ref>/<Payee Name>/<VPA>            (P2A — person transfer)
    NACH DR-<Lender>                        (loan EMI)
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": "",
              "is_p2m": False}
    desc_upper = description.upper()

    # Real Axis UPI narration is six slash-delimited fields, with the payee,
    # counterparty bank and remark each truncated:
    #   UPI/<P2A|P2M>/<ref>/<payee>/<bank>/<remark>
    # The old code had no P2A branch, so P2A rows fell into the generic "UPI/"
    # branch and every field shifted by one -- payee came back as the numeric
    # reference. 148 of 373 populated Axis merchant entities were bare RRNs.
    if desc_upper.startswith("UPI/P2M/") or desc_upper.startswith("UPI/P2A/"):
        result["rail"] = "UPI"
        result["is_p2m"] = desc_upper.startswith("UPI/P2M/")
        result["is_p2a"] = desc_upper.startswith("UPI/P2A/")
        parts = _safe_split(description, "/")
        result["ref"] = parts[2].strip() if len(parts) > 2 else ""
        result["payee"] = parts[3].strip() if len(parts) > 3 else ""

        # Fields 4 and 5 are the counterparty bank and the payer's remark, but
        # Axis emits them in EITHER order -- measured on one statement: 214 rows
        # are payee/remark/BANK and 161 are payee/BANK/remark. Assuming a single
        # layout swapped the two on roughly 40% of rows, so merchant_entity and
        # the remark were both unreliable. Identify the bank field by content.
        f4 = parts[4].strip() if len(parts) > 4 else ""
        f5 = parts[5].strip() if len(parts) > 5 else ""
        f4_is_bank, f5_is_bank = looks_like_bank(f4), looks_like_bank(f5)

        if f4_is_bank and not f5_is_bank:
            result["counterparty_bank"], result["remarks"] = f4, f5
        elif f5_is_bank and not f4_is_bank:
            result["counterparty_bank"], result["remarks"] = f5, f4
        else:
            # Both or neither look like a bank; fall back to the commoner
            # layout and leave the remark empty rather than guess wrong.
            result["counterparty_bank"], result["remarks"] = f4, ("" if f4_is_bank else f5)
    elif desc_upper.startswith("UPI/"):
        result["rail"] = "UPI"
        parts = _safe_split(description, "/")
        if len(parts) >= 3:
            result["ref"] = parts[1] if len(parts) > 1 else ""
            result["payee"] = parts[2] if len(parts) > 2 else ""
            result["vpa"] = parts[3] if len(parts) > 3 else ""
    elif desc_upper.startswith("NACH DR-"):
        result["rail"] = "NACH"
        result["payee"] = description[8:].strip()
    # ACH-CR-<EMPLOYER>-NACH-<ref>. Axis salary credits arrive on this rail;
    # "COSAL" in the trailing reference is the company-salary marker.
    elif desc_upper.startswith("ACH-CR-"):
        result["rail"] = "ACH"
        result["is_credit_rail"] = True
        body = description[7:]
        result["payee"] = body.split("-")[0].strip()
        result["remarks"] = body
    elif desc_upper.startswith("ACH-DR-"):
        result["rail"] = "ACH"
        result["payee"] = description[7:].split("-")[0].strip()
    elif "ATM" in desc_upper or desc_upper.startswith("ATW"):
        result["rail"] = "ATM"

    return result


def boi_parse_description(description: str) -> Dict[str, str]:
    """
    BOI rail format (Finacle — terser strings, ~20-25 chars truncation):
    UPI-<Payee Name>-<VPA>-<Ref>
    UPI/<Ref>/<Remarks>
    ECS/<Lender>/<Loan No>
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": ""}
    desc_upper = description.upper()

    if desc_upper.startswith("UPI-"):
        result["rail"] = "UPI"
        parts = description.split("-", 4)
        if len(parts) >= 3:
            result["payee"] = parts[1] if len(parts) > 1 else ""
            result["vpa"] = parts[2] if len(parts) > 2 else ""
            result["ref"] = parts[3] if len(parts) > 3 else ""
    elif desc_upper.startswith("UPI/"):
        result["rail"] = "UPI"
        parts = _safe_split(description, "/")
        if len(parts) >= 2:
            result["ref"] = parts[1] if len(parts) > 1 else ""
            result["remarks"] = parts[2] if len(parts) > 2 else ""
    elif desc_upper.startswith("ECS/"):
        result["rail"] = "ECS"
        parts = _safe_split(description, "/")
        if len(parts) >= 2:
            result["payee"] = parts[1] if len(parts) > 1 else ""
    # Real BOI narrations. This is a Finacle statement that predates UPI
    # entirely, so the UPI branches above never fire; the file is terse free
    # text and hyphen-delimited codes.
    #   CWDR//<seq>/<terminal>   ATM cash withdrawal
    #   ECS-MCGM<MMYYYY> A13     monthly municipal direct debit (hyphen, not slash)
    #   Loan Reco. For <acct>    loan recovery
    #   BY CASH / TO CLG         teller and clearing
    #   bare tokens: DHFL, LIC, BEST, ICICI BANK CC
    elif desc_upper.startswith("CWDR"):
        result["rail"] = "ATM"
        parts = [p for p in description.split("/") if p.strip()]
        result["ref"] = parts[1].strip() if len(parts) > 1 else ""
    elif desc_upper.startswith("ECS-"):
        result["rail"] = "ECS"
        body = description[4:].strip()
        # "MCGM032010 A13" -> the payee is the alphabetic prefix.
        m = re.match(r"([A-Za-z]+)", body)
        result["payee"] = m.group(1) if m else body
        result["remarks"] = body
    elif desc_upper.startswith("LOAN RECO"):
        result["rail"] = "LOAN"
        result["remarks"] = description.strip()
    elif desc_upper.startswith("BY CASH") or desc_upper.startswith("TO CASH"):
        result["rail"] = "CASH"
    elif desc_upper.startswith("BY CLG") or desc_upper.startswith("TO CLG"):
        result["rail"] = "CHEQUE"
    elif "INT CREDIT" in desc_upper or "INT.PD" in desc_upper:
        result["rail"] = "INTEREST"
    elif "CHARGES" in desc_upper:
        result["rail"] = "CHARGES"
    elif "ATM" in desc_upper or desc_upper.startswith("ATW"):
        result["rail"] = "ATM"
    elif description.strip() and len(description.strip()) <= 30:
        # A bare merchant/lender token is the whole narration on this bank
        # (DHFL, LIC, BEST, "ICICI BANK CC").
        result["payee"] = description.strip()

    return result


def union_parse_description(description: str) -> Dict[str, str]:
    """
    Union Bank rail format:
    UPI/<Ref>/<Payee Name>/<Remarks>
    NACH-<Lender>-EMI
    Legacy Andhra/Corp Bank formats may co-exist.
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": ""}
    desc_upper = description.upper()

    # Union's real prefixes differ from the documented ones: the UPI rail is
    # "UPIAB/" (with a direction flag in slot 3), the ACH equivalent is "APB/"
    # rather than "NACH-", and NEFT uses a colon. None of the previous branches
    # matched a single row of a real statement.
    #   UPIAB/<ref>/<CR|DR>/<payee 8ch>/<IFSC>/<VPA>
    #   NEFT:<branch> <UTR>
    #   APB/<code>/<ref>/<remark>
    #   <account>:Int.Pd:<period>
    if desc_upper.startswith("UPIAB/") or desc_upper.startswith("UPI/"):
        result["rail"] = "UPI"
        parts = _safe_split(description, "/")
        result["ref"] = parts[1].strip() if len(parts) > 1 else ""
        if desc_upper.startswith("UPIAB/"):
            result["direction"] = parts[2].strip().upper() if len(parts) > 2 else ""
            result["payee"] = parts[3].strip() if len(parts) > 3 else ""
            result["vpa"] = parts[5].strip() if len(parts) > 5 else ""
        else:
            result["payee"] = parts[2].strip() if len(parts) > 2 else ""
            result["remarks"] = parts[3].strip() if len(parts) > 3 else ""
    elif desc_upper.startswith("NEFT:") or desc_upper.startswith("NEFT-"):
        result["rail"] = "NEFT"
        result["remarks"] = description[5:].strip()
    elif desc_upper.startswith("APB/"):
        # Union's ACH/direct-debit rail.
        result["rail"] = "ACH"
        parts = _safe_split(description, "/")
        result["ref"] = parts[2].strip() if len(parts) > 2 else ""
        result["remarks"] = parts[3].strip() if len(parts) > 3 else ""
    elif desc_upper.startswith("NACH-"):
        result["rail"] = "NACH"
        parts = description.split("-")
        if len(parts) >= 2:
            result["payee"] = parts[1] if len(parts) > 1 else ""
    elif ":INT.PD:" in desc_upper:
        result["rail"] = "INTEREST"
    elif "SMS CHARGE" in desc_upper or "CHARGES" in desc_upper:
        result["rail"] = "CHARGES"
    elif "ATM" in desc_upper or desc_upper.startswith("ATW"):
        result["rail"] = "ATM"

    return result


def bob_parse_description(description: str) -> Dict[str, str]:
    """
    Bank of Baroda rail formats, taken from a real statement:

        UPI/<ref>/<HH:MM:SS>/UPI/<VPA>/<remark>
        NEFT-<UTR>-<PAYEE>-<BANK>
        RTGS-<UTR>-<PAYEE>
        ATM/CASH/<ref>/<masked card>
        <account>:Int.Pd:<period>

    Note there is **no payee name on the UPI rail at all** -- BOB carries only
    the VPA, and slot 3 holds a time of day. The previous implementation
    expected `UPI/<ref>/<remarks>/<payee>`, which put the timestamp into
    `remarks` and the literal string "UPI" into `payee` on every UPI row. That
    failed silently with a plausible-looking value, which is worse than not
    matching at all.
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": ""}
    desc_upper = description.upper()

    if desc_upper.startswith("UPI/"):
        result["rail"] = "UPI"
        parts = _safe_split(description, "/")
        result["ref"] = parts[1].strip() if len(parts) > 1 else ""
        # parts[2] is a timestamp and parts[3] the literal "UPI"; the VPA follows.
        for candidate in parts[3:6]:
            if "@" in str(candidate):
                result["vpa"] = str(candidate).strip()
                break
        result["remarks"] = parts[5].strip() if len(parts) > 5 else ""

        # The VPA local part is the only identity BOB gives on this rail. The
        # whole narration is capped at 50 characters, so the VPA is often cut
        # before its "@" -- fall back to the raw field rather than losing the
        # counterparty entirely.
        if result["vpa"]:
            result["payee"] = result["vpa"].split("@")[0]
        else:
            candidate = parts[4].strip() if len(parts) > 4 else ""
            if candidate and candidate.upper() != "UPI" and ":" not in candidate:
                result["vpa"] = candidate
                result["payee"] = candidate
    elif desc_upper.startswith(("NEFT-", "RTGS-")):
        result["rail"] = "NEFT" if desc_upper.startswith("NEFT-") else "RTGS"
        parts = description.split("-")
        if len(parts) > 2:
            result["ref"] = parts[1].strip()
            result["payee"] = parts[2].strip()
    elif desc_upper.startswith("ATM/") or "ATM/CASH" in desc_upper:
        result["rail"] = "ATM"
    elif desc_upper.startswith("ECS DR-"):
        result["rail"] = "ECS"
        result["payee"] = description[7:].strip()
    elif ":INT.PD:" in desc_upper:
        result["rail"] = "INTEREST"
    elif "SMS CHARGE" in desc_upper:
        result["rail"] = "CHARGES"
    elif "ATM" in desc_upper or desc_upper.startswith("ATW"):
        result["rail"] = "ATM"

    return result


# Rail tokens, longest first so "CASH WDL" is tested before "CASH" and
# "UPIAB" before "UPI". These are national payment-system names, not bank
# branding: NPCI defines UPI/IMPS/NACH, RBI defines NEFT/RTGS, and Finacle
# emits CWDR/EBA wherever it is deployed. That is why a token-driven parser
# generalises to a bank we have never seen, while a merchant dictionary does not.
_RAIL_TOKENS = [
    ("UPIAB", "UPI"), ("UPI", "UPI"),
    ("NEFT", "NEFT"), ("RTGS", "RTGS"), ("IMPS", "IMPS"),
    ("NACH", "NACH"), ("ACH", "ACH"), ("ECS", "ECS"), ("APB", "ACH"),
    ("CWDR", "ATM"), ("CASH WDL", "ATM"), ("ATW", "ATM"), ("ATM", "ATM"),
    ("CLG", "CHEQUE"), ("CHQ", "CHEQUE"), ("CHEQUE", "CHEQUE"),
    ("EBA", "EBA"), ("MFP", "EBA"),
    ("INT.PD", "INTEREST"), ("INT CREDIT", "INTEREST"), ("INTEREST", "INTEREST"),
    ("SMS CHARGE", "CHARGES"), ("CHARGES", "CHARGES"),
    ("REV-", "REVERSAL"), ("REV/", "REVERSAL"), ("REVERSAL", "REVERSAL"),
    ("SWEEP TRF", "SAVINGS_SWEEP"), ("MOD TRF", "SAVINGS_SWEEP"), ("SWEEP", "SAVINGS_SWEEP"),
    ("CEMTEX", "TAX_REFUND"),
    ("INF/", "INTERNAL_TRANSFER"), ("INF", "INTERNAL_TRANSFER"),
    ("TPC/", "INTERNAL_TRANSFER"), ("TPC", "INTERNAL_TRANSFER"),
    ("BIL/ONL", "BILL_PAYMENT"), ("BIL/", "BILL_PAYMENT"),
    ("POS ", "POS_CARD"), ("IPS ", "POS_CARD"),
    ("BY CASH", "CASH"), ("TO CASH", "CASH"),
]

# A UPI handle: the one reliable identity token in an Indian narration, and
# already implemented properly in rules/counterparty.py. The per-bank parsers
# each rolled their own or ignored it.
_VPA_TOKEN = re.compile(r"\b([A-Za-z0-9._-]{2,})@([A-Za-z]{2,})\b")

# A 12-digit UPI RRN / reference number.
_REF_TOKEN = re.compile(r"\b(\d{10,16})\b")

_NOT_A_PAYEE = re.compile(
    r"^(UPI|UPIAB|NEFT|RTGS|IMPS|NACH|ACH|ECS|CLG|CHQ|CHEQUE|ATM|ATW|CWDR|"
    r"EBA|MFP|APB|DR|CR|P2P|P2M|P2A|WDL|DEP|TFR|TO|BY|REF|BIL|ONL|MMT|CMS|"
    r"CAM|NFS|INT|SMS|TRF|TRANSFER)$",
    re.IGNORECASE,
)


def token_parse_description(description: str) -> Dict[str, str]:
    """
    Parse a narration by the tokens present, not by a per-bank slot layout.

    The six hand-written parsers above are ~85% the same three-step recipe:
    uppercase, test a prefix, split on a delimiter, read fixed slot indices.
    Only the delimiter (`/`, `-`, `*`, `:`), the prefix spelling (`UPI/` vs
    `UPI-` vs `UPIAB/` vs `WDL TFR UPI/`) and the slot order actually differ --
    which is precisely what makes them useless on a bank nobody has written a
    parser for. HDFC, Kotak and every unrecognised bank had no rail, no payee
    and no VPA at all, so Tier 1 was a complete no-op for them.

    This finds the rail token wherever it sits, takes the VPA and reference by
    shape rather than position, and picks the payee as the most name-like
    remaining field.
    """
    result = {"payee": "", "vpa": "", "ref": "", "remarks": "", "rail": ""}
    text = (description or "").strip()
    if not text:
        return result

    upper = text.upper()

    for token, rail in _RAIL_TOKENS:
        if token in upper:
            result["rail"] = rail
            break

    # Split on whichever delimiter the bank happens to use.
    delimiter = max(("/", "-", "*", ":"), key=lambda d: text.count(d))
    fields = [f.strip() for f in text.split(delimiter)] if text.count(delimiter) >= 2 else [text]

    # Match the handle inside a single field, never across the whole narration.
    # A VPA local part may legally contain a hyphen, so searching the raw string
    # of a hyphen-delimited narration swallows everything to its left:
    # "UPI-SWIGGY-swiggy@ybl" comes back whole instead of "swiggy@ybl".
    for field in fields:
        vpa_match = _VPA_TOKEN.search(field)
        if vpa_match:
            result["vpa"] = vpa_match.group(0)
            break

    for field in fields:
        m = _REF_TOKEN.fullmatch(field.strip())
        if m:
            result["ref"] = m.group(1)
            break

    # The payee is the longest field that reads like a name: mostly letters,
    # not a rail token, not a pure number, not a bank name (that is the
    # counterparty bank, which several banks place in a slot of its own).
    candidates = []
    for field in fields:
        f = field.strip()
        if len(f) < 3 or _NOT_A_PAYEE.match(f) or f.replace(" ", "").isdigit():
            continue
        if "@" in f or looks_like_bank(f):
            continue
        letters = sum(ch.isalpha() for ch in f)
        if letters >= 3 and letters / len(f) > 0.5:
            candidates.append(f)

    if candidates:
        # The FIRST name-like field, not the longest. Indian narrations put the
        # counterparty before the free-text remark, so on
        # "UPI-SWIGGY-swiggy@ybl-...-Food order" the longest candidate is the
        # remark ("Food order") and the first is the merchant ("SWIGGY").
        result["payee"] = candidates[0][:40]
        if len(candidates) > 1:
            result["remarks"] = candidates[-1][:40]
    elif result["vpa"]:
        # Bank of Baroda carries no payee on the UPI rail at all; the handle's
        # local part is the only identity available.
        result["payee"] = result["vpa"].split("@")[0][:40]
    elif len(text) <= 30:
        # Terse Finacle narrations are the merchant token themselves ("DHFL",
        # "LIC", "ICICI BANK CC").
        result["payee"] = text

    return result


def generic_parse_description(description: str) -> Dict[str, str]:
    """
    Parser for banks with no hand-written rules (HDFC, Kotak, Other, and any
    bank added by calibration). Delegates to the token parser.
    """
    return token_parse_description(description)


# ============================================================
# BANK RULES REGISTRY
# ============================================================

# Rail pattern regex for deterministic Tier-1 classification
# Key = pattern name, Value = compiled regex
# These are checked BEFORE the shared keyword dictionary

BANK_RAIL_PATTERNS: Dict[str, Dict[str, re.Pattern]] = {
    "SBI": {
        "upi_debit": re.compile(r"TO TRANSFER-UPI/DR/", re.IGNORECASE),
        "upi_credit": re.compile(r"BY TRANSFER-UPI/CR/", re.IGNORECASE),
        "ecs": re.compile(r"ECS-SBI", re.IGNORECASE),
        "nach": re.compile(r"NACH-", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-SBI", re.IGNORECASE),
        "atm": re.compile(r"(ATW|ATM-CASH|CWDR|SBI ATM)", re.IGNORECASE),
    },
    "ICICI": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "ach": re.compile(r"^ACH/", re.IGNORECASE),
        "bil_neft": re.compile(r"^BIL/NEFT/", re.IGNORECASE),
        "bil_onl": re.compile(r"^BIL/ONL/", re.IGNORECASE),
        "mmt_imps": re.compile(r"^MMT/IMPS/", re.IGNORECASE),
        "eba_mf": re.compile(r"^EBA/MFP-", re.IGNORECASE),
        "eba_eq": re.compile(r"^EBA/EQ Trade", re.IGNORECASE),
        "cms": re.compile(r"^CMS/", re.IGNORECASE),
        "cam_cash": re.compile(r"^CAM/.*/CASH WDL", re.IGNORECASE),
        "nfs_cash": re.compile(r"^NFS/CASH WDL/", re.IGNORECASE),
        "clg": re.compile(r"^CLG/", re.IGNORECASE),
        "neft": re.compile(r"^NEFT-", re.IGNORECASE),
        "neft_return": re.compile(r"^NEFT-RETURN-", re.IGNORECASE),
        "interest": re.compile(r"Int\.Pd:", re.IGNORECASE),
        "forex": re.compile(r"^[A-Z]{3}SXR\d+:", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-ICIC", re.IGNORECASE),
        "govt_scheme": re.compile(r"(PMJJBY|PMSBY)", re.IGNORECASE),
        "bank_charge": re.compile(r"(DCardfee|AdminCharge|CGST|SGST)", re.IGNORECASE),
    },
    "Axis": {
        "upi_p2m": re.compile(r"^UPI/P2M/", re.IGNORECASE),
        "upi_p2a": re.compile(r"^UPI/(?!P2M)", re.IGNORECASE),
        "nach": re.compile(r"^NACH DR-", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-UTIB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|ATM-CASH|AXIS ATM)", re.IGNORECASE),
    },
    "Bank Of India": {
        "upi_dash": re.compile(r"^UPI-", re.IGNORECASE),
        "upi_slash": re.compile(r"^UPI/", re.IGNORECASE),
        "ecs": re.compile(r"^ECS/", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-BKID", re.IGNORECASE),
        "atm": re.compile(r"(ATW|BOI ATM|CWDR)", re.IGNORECASE),
    },
    "Union": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "nach": re.compile(r"^NACH-.*-EMI", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-UBIN", re.IGNORECASE),
        "atm": re.compile(r"(ATW|UNION ATM|CWDR)", re.IGNORECASE),
    },
    "BOB": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "ecs": re.compile(r"^ECS DR-", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-BARB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|BOB ATM|CWDR)", re.IGNORECASE),
    },
    "HDFC": {},
    "Kotak": {},
    "Punjab National Bank": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-PUNB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|PUNB ATM|CWDR)", re.IGNORECASE),
        "nach": re.compile(r"^NACH-", re.IGNORECASE),
    },
    "YES Bank": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-YESB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|CSW|ATD|ATI|YES BANK ATM)", re.IGNORECASE),
    },
    "Bank Of Maharashtra": {
        "fastag": re.compile(r"NETC FASTAG-MAHB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|MAHB ATM|CWDR)", re.IGNORECASE),
        "neft": re.compile(r"^NEFT MAHB", re.IGNORECASE),
    },
    "Federal Bank": {
        "fastag": re.compile(r"NETC FASTAG-FDRL", re.IGNORECASE),
        "atm": re.compile(r"(ATW|FEDERAL ATM)", re.IGNORECASE),
        "neft": re.compile(r"^NFT/", re.IGNORECASE),
    },
    "Indian Overseas Bank": {
        "fastag": re.compile(r"NETC FASTAG-IOBA", re.IGNORECASE),
        "atm": re.compile(r"(ATW|ATM-IOB)", re.IGNORECASE),
        "nach": re.compile(r"^NACH", re.IGNORECASE),
    },
    "IndusInd Bank": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-INDB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|INDUSIND ATM)", re.IGNORECASE),
    },
    "Canara Bank": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-CNRB", re.IGNORECASE),
        "atm": re.compile(r"(ATW|CANARA ATM)", re.IGNORECASE),
    },
    "IDBI Bank": {
        "upi": re.compile(r"^UPI/", re.IGNORECASE),
        "fastag": re.compile(r"NETC FASTAG-IBKL", re.IGNORECASE),
        "atm": re.compile(r"(ATW|IDBI ATM)", re.IGNORECASE),
    },
    "Other": {},
}

# Bank-specific keyword additions that DIFFER from the shared master dict
BANK_SPECIFIC_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "SBI": {
        "hl_emi": ["SBIHLEMI", "ECS-SBIHOME"],
        "insurance": ["SBI LIFE"],
        "cc_payment": ["SBICARD", "CREDIT CARD BILL"],
        "atm": ["SBI ATM"],
        "savings": ["RD INSTALLMENT", "SWEEP-IN", "AUTO SWEEP", "TD ACCOUNT"],
        "pl": ["ECS-SBI PL"],
        "investment": ["BILLDESK-MF", "NACH-MF"],
    },
    "ICICI": {
        "hl_emi": ["ICICIHLEMI", "ACH DEBIT-ICICI HFC"],
        "insurance": ["ICICI PRU LIFE", "ICICI LOMBARD"],
        "cc_payment": ["ICICI CREDIT CARD"],
        "investment": ["ICICI DIRECT", "ICICI SECURITIES", "ICICI DIRECT MF"],
        "savings": ["ICICI FLEXI RD", "RD INSTALLMENT", "SWEEP-IN",
                     "AUTO SWEEP", "TD ACCOUNT"],
        "atm": ["ICICI ATM"],
    },
    "Axis": {
        "hl_emi": ["NACH DR-AXIS HL"],
        "insurance": ["MAX LIFE"],
        "cc_payment": ["AXIS CREDIT CARD"],
        "pl": ["NACH DR-AXIS PL"],
        "atm": ["AXIS ATM"],
        "savings": ["RD INSTALLMENT", "SWEEP-IN", "AUTO SWEEP", "TD ACCOUNT"],
    },
    "HDFC": {},
    "Kotak": {},
    "Bank Of India": {
        "hl_emi": ["ECS/BOI HL"],
        "cc_payment": ["BOI CREDIT CARD"],
        "pl": ["ECS/BOI PL"],
        "atm": ["BOI ATM"],
        "savings": ["RD INSTALLMENT", "SWEEP-IN", "TD ACCOUNT"],
    },
    "Union": {
        "hl_emi": ["NACH-UNION HL"],
        "cc_payment": ["UNION CREDIT CARD"],
        "pl": ["NACH-UNION PL"],
        "atm": ["UNION ATM"],
        "savings": ["RD INSTALLMENT", "SWEEP-IN", "TD ACCOUNT"],
    },
    "BOB": {
        "hl_emi": ["ECS DR-BOB HL"],
        "cc_payment": ["BOB CREDIT CARD"],
        "pl": ["ECS DR-BOB PL"],
        "atm": ["BOB ATM"],
        "savings": ["RD INSTALLMENT", "SWEEP-IN", "TD ACCOUNT"],
    },
    "Punjab National Bank": {
        "cc_payment": ["PNB CREDIT CARD"],
        "hl_emi": ["PNB HOUSING"],
        "atm": ["PUNB ATM"],
    },
    "YES Bank": {
        "cc_payment": ["YES BANK CREDIT CARD"],
        "atm": ["YES BANK ATM"],
    },
    "Bank Of Maharashtra": {
        "atm": ["MAHB ATM"],
    },
    "Federal Bank": {
        "atm": ["FEDERAL ATM"],
    },
    "Indian Overseas Bank": {
        "atm": ["ATM-IOB"],
    },
    "IndusInd Bank": {
        "cc_payment": ["INDUSIND CREDIT CARD"],
        "atm": ["INDUSIND ATM"],
    },
    "Canara Bank": {
        "atm": ["CANARA ATM"],
    },
    "IDBI Bank": {
        "atm": ["IDBI ATM"],
    },
    "Other": {},
}

# Description parser dispatch
DESCRIPTION_PARSERS = {
    "SBI": sbi_parse_description,
    "ICICI": icici_parse_description,
    "Axis": axis_parse_description,
    "HDFC": generic_parse_description,
    "Kotak": generic_parse_description,
    "Bank Of India": boi_parse_description,
    "Union": union_parse_description,
    "BOB": bob_parse_description,
    "Punjab National Bank": generic_parse_description,
    "YES Bank": generic_parse_description,
    "Bank Of Maharashtra": generic_parse_description,
    "Federal Bank": generic_parse_description,
    "Indian Overseas Bank": generic_parse_description,
    "IndusInd Bank": generic_parse_description,
    "Canara Bank": generic_parse_description,
    "IDBI Bank": generic_parse_description,
    "Other": generic_parse_description,
}

# Banks that use Finacle core banking (truncated descriptions)
FINACLE_BANKS = {"Bank Of India", "Union", "BOB", "Punjab National Bank", "Canara Bank", "Indian Overseas Bank"}

# Banks with legacy merged-bank format variations
LEGACY_FORMAT_BANKS = {"Union", "BOB"}


def get_description_parser(bank_name: str):
    """
    Return the description parser for a bank.

    A bank with hand-written rules keeps them -- they encode real format
    knowledge and are pinned by the accuracy tests -- but anything they cannot
    parse now falls through to the token parser instead of returning empty.
    The hand-written parsers only recognise the prefixes someone thought to
    write down, so a narration in an unanticipated shape produced no rail, no
    payee and no VPA, and skipped Tier 1 entirely.
    """
    specific = DESCRIPTION_PARSERS.get(bank_name)
    if specific is None or specific is generic_parse_description:
        return generic_parse_description

    def parse_with_fallback(description: str) -> Dict[str, str]:
        result = specific(description)
        if result.get("rail") and result.get("payee"):
            return result

        # Fill only what the bank parser left empty -- never overwrite a value
        # it produced, because its slot knowledge beats a generic guess.
        fallback = token_parse_description(description)
        for key, value in fallback.items():
            if value and not result.get(key):
                result[key] = value
        return result

    parse_with_fallback.__name__ = f"{getattr(specific, '__name__', 'bank')}_with_token_fallback"
    return parse_with_fallback


def get_rail_patterns(bank_name: str) -> Dict[str, re.Pattern]:
    """Return compiled rail regex patterns for a given bank."""
    return BANK_RAIL_PATTERNS.get(bank_name, {})


def get_bank_specific_keywords(bank_name: str) -> Dict[str, List[str]]:
    """Return bank-specific keyword overrides."""
    return BANK_SPECIFIC_KEYWORDS.get(bank_name, {})


def is_finacle_bank(bank_name: str) -> bool:
    """Check if a bank uses Finacle core banking (truncated descriptions)."""
    return bank_name in FINACLE_BANKS


def has_legacy_format(bank_name: str) -> bool:
    """Check if a bank may have legacy merged-bank format strings."""
    return bank_name in LEGACY_FORMAT_BANKS


if __name__ == "__main__":
    # A quick way to see what a narration parses to, for any bank.
    #   python -m src.rules.bank_rules ICICI "UPI/P2M/123/Chalo/ICICI Bank/ride"
    import sys

    bank = sys.argv[1] if len(sys.argv) > 2 else "Other"
    narration = sys.argv[-1] if len(sys.argv) > 1 else ""
    print(f"{bank}: {get_description_parser(bank)(narration)}")