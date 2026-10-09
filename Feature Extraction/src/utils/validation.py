"""
Data validation and cleaning utilities for bank statement CSVs.

Handles:
- Junk row detection and removal (PDF footer text, legends)
- Date parsing and normalization
- Numeric coercion (commas, currency symbols, empty strings)
- Column name mapping
- Missing value handling
- Duplicate detection
- Bank name inference from filename
"""

import re
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# Patterns that indicate junk/footer rows from PDF extraction.
#
# These must be narrow enough not to delete real transactions. Bare domain
# suffixes were previously listed here and destroyed legitimate rows before
# classification ever saw them -- "HOUSING.COM" is itself a Rent keyword, and
# any AMAZON.COM / PAYTM.IN narration was dropped. Footer URLs are still caught
# by the "www." and "https" patterns. Likewise PAVC/LNPY/CCWD/PAYC are bank
# transaction codes (CCWD = card cash withdrawal), not footer text.
JUNK_PATTERNS = [
    r"www\.",
    r"https?://",
    r"Legends? for",
    r"Dial your",
    r"Please\b.*share",
    r"CVV or password",
    r"registered mobile",
    r"do not share.*\bOTP\b",
    r"^\s*$",
]
JUNK_REGEX = re.compile("|".join(JUNK_PATTERNS), re.IGNORECASE)

# Bank name inference from filename
BANK_FILENAME_MAP = {
    "sbi": "SBI",
    "icici": "ICICI",
    "axis": "Axis",
    "hdfc": "HDFC",
    "kotak": "Kotak",
    "bank of india": "Bank Of India",
    "boi": "Bank Of India",
    "union": "Union",
    "bob": "BOB",
    "baroda": "BOB",
}


def load_settings(config_path: Optional[str] = None) -> dict:
    """Load settings from YAML config file."""
    if config_path is None:
        config_path = str(
            Path(__file__).parent.parent.parent / "configs" / "settings.yaml"
        )
    config_file = Path(config_path)
    if not config_file.exists():
        logger.warning(f"Config file not found at {config_path}, using defaults.")
        return {}

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def infer_bank_name(file_path: str) -> str:
    """
    Infer bank name from CSV filename.

    Examples:
        'ICICI_extracted.csv' → 'ICICI'
        'sbi_statement.csv' → 'SBI'
        'unknown_file.csv' → 'Other'
    """
    filename_lower = Path(file_path).stem.lower()

    for keyword, bank_name in BANK_FILENAME_MAP.items():
        if keyword in filename_lower:
            logger.info(f"Inferred bank '{bank_name}' from filename '{Path(file_path).name}'")
            return bank_name

    logger.warning(
        f"Could not infer bank from filename '{Path(file_path).name}'. "
        f"Defaulting to 'Other'. Use --bank flag to specify."
    )
    return "Other"


def get_bank_config(settings: dict, bank_name: str) -> dict:
    """Get bank-specific configuration from settings."""
    banks_config = settings.get("banks", {})
    bank_config = banks_config.get(bank_name, banks_config.get("Other", {}))
    return bank_config


# Currency prefixes/suffixes stripped as whole tokens, never as a character class.
_CURRENCY_RE = re.compile(r"(?:^|(?<=[\s\d]))(?:INR|RS\.?|₹|₹|\$)", re.IGNORECASE)
_DRCR_RE = re.compile(r"\b(DR|CR)\b\.?\s*$", re.IGNORECASE)


def clean_numeric(value, treat_dr_as_negative: bool = False) -> float:
    """
    Coerce a value to float, handling:
    - Commas in numbers (1,234.56)
    - Currency symbols (₹, Rs, INR)
    - Accounting negatives, i.e. "(500)" -> -500.0
    - Trailing Dr/Cr indicators
    - Empty strings and None
    - Already-numeric types

    Args:
        treat_dr_as_negative: when True a trailing "Dr" flips the sign. Only
            meaningful for a running-balance column, where "5,000.00 Dr" denotes
            an overdrawn balance. For dedicated debit/credit columns the suffix
            is redundant and is stripped without changing the sign.

    Previously the currency strip was written as the character class
    ``[₹RsINR\\s]``, which deleted every r/s/i/n anywhere in the string -- so
    "500 DR" became "500 D" and silently parsed as 0.0. Amounts are now parsed
    or explicitly reported as unparseable.
    """
    if isinstance(value, (int, float)):
        return float(value) if not np.isnan(value) else 0.0

    if value is None:
        return 0.0

    val_str = str(value).strip()
    if not val_str or val_str.lower() in ("nan", "none", "null", "-", ""):
        return 0.0

    negative = False

    # Accounting negative: (1,234.56)
    if val_str.startswith("(") and val_str.endswith(")"):
        negative = True
        val_str = val_str[1:-1].strip()

    # Trailing Dr/Cr indicator
    drcr = _DRCR_RE.search(val_str)
    if drcr:
        if treat_dr_as_negative and drcr.group(1).upper() == "DR":
            negative = True
        val_str = _DRCR_RE.sub("", val_str).strip()

    cleaned = _CURRENCY_RE.sub("", val_str)
    cleaned = cleaned.replace(",", "").replace(" ", "").strip()

    if cleaned.startswith("-"):
        negative = not negative
        cleaned = cleaned[1:].strip()
    elif cleaned.startswith("+"):
        cleaned = cleaned[1:].strip()

    if not cleaned:
        return 0.0

    try:
        result = float(cleaned)
    except ValueError:
        logger.warning(f"Could not parse numeric value: {value!r} -> treating as 0.0")
        return 0.0

    return -result if negative else result


def reorder_intraday_by_balance_chain(df: pd.DataFrame, tolerance: float = 0.5) -> tuple:
    """
    Restore true statement order within each date using the running balance.

    PDF extraction preserves statement order, but that order is lost as soon as
    the frame is sorted by date alone: rows sharing a date come back in an
    arbitrary sequence. Every balance-derived metric then reads the wrong
    end-of-day figure, and the fraud engine reports the resulting arithmetic
    breaks as "running balance mismatch -- potential document tampering".

    For each date, this greedily picks the ordering that satisfies
    ``balance[i] == balance[i-1] - debit[i] + credit[i]``, carrying the previous
    day's closing balance in as the opening balance. A day that cannot be
    chained is left in its original order.

    Returns:
        (reordered_df, mismatches_remaining)
    """
    if df.empty or not {"date", "debit", "credit", "balance"}.issubset(df.columns):
        return df, 0

    # Opening balance implied by the first row.
    first = df.iloc[0]
    running = float(first["balance"]) + float(first["debit"]) - float(first["credit"])

    ordered_parts = []
    for _, day_rows in df.groupby(df["date"].dt.normalize(), sort=True):
        remaining = day_rows.to_dict("records")
        chained = []

        # Greedily pick, at each step, the row whose net movement lands on its
        # own printed balance given the running balance so far.
        while remaining:
            match_idx = None
            for i, row in enumerate(remaining):
                expected = running - float(row["debit"]) + float(row["credit"])
                if abs(expected - float(row["balance"])) <= tolerance:
                    match_idx = i
                    break
            if match_idx is None:
                break
            row = remaining.pop(match_idx)
            running = float(row["balance"])
            chained.append(row)

        if remaining:
            # Could not fully chain this day -- keep the original order for the
            # remainder and resynchronise on the last printed balance.
            chained.extend(remaining)
            running = float(chained[-1]["balance"])

        ordered_parts.append(pd.DataFrame(chained, columns=day_rows.columns))

    if not ordered_parts:
        return df, 0

    out = pd.concat(ordered_parts, ignore_index=True)

    expected = out["balance"].shift(1) - out["debit"] + out["credit"]
    mismatches = int((out["balance"] - expected).abs().gt(tolerance).iloc[1:].sum())
    return out, mismatches


def parse_date(value, formats: Optional[List[str]] = None) -> Optional[pd.Timestamp]:
    """
    Parse a date value with multiple format fallbacks.
    Returns pd.NaT if unparseable.
    """
    if pd.isna(value) or value is None:
        return pd.NaT

    if isinstance(value, (pd.Timestamp,)):
        return value

    if formats is None:
        formats = [
            "%Y-%m-%d",      # ISO (standardized CSV)
            "%d/%m/%Y",      # SBI, ICICI, Kotak
            "%d-%m-%Y",      # Axis, BOI
            "%d/%m/%y",      # HDFC
            "%Y-%m-%d %H:%M:%S",
        ]

    value_str = str(value).strip()
    if not value_str:
        return pd.NaT

    for fmt in formats:
        try:
            return pd.Timestamp(pd.to_datetime(value_str, format=fmt))
        except (ValueError, TypeError):
            continue

    # Final fallback — let pandas infer
    try:
        return pd.Timestamp(pd.to_datetime(value_str, dayfirst=True))
    except (ValueError, TypeError):
        return pd.NaT


def is_junk_row(row: pd.Series) -> bool:
    """
    Detect junk/footer rows from PDF extraction artifacts.

    A row is junk if:
    - Date is empty/unparseable
    - Description contains website URLs, legends text, disclaimers
    - All numeric columns are 0
    """
    # Check if date is empty or NaT
    date_val = row.get("date", None)
    if pd.isna(date_val) or (isinstance(date_val, str) and not date_val.strip()):
        return True

    # Check description for junk patterns
    desc = str(row.get("description", ""))
    if JUNK_REGEX.search(desc):
        return True

    return False


def validate_and_clean(
    df: pd.DataFrame,
    bank_name: str = "Other",
    settings: Optional[dict] = None,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """
    Validate and clean a bank statement DataFrame.

    Args:
        df: Raw DataFrame from CSV
        bank_name: Detected or specified bank name
        settings: Configuration settings dict

    Returns:
        Tuple of (cleaned DataFrame, stats dict with counts)
    """
    if settings is None:
        settings = {}

    stats = {
        "total_rows": len(df),
        "junk_rows_removed": 0,
        "duplicates_removed": 0,
        "dates_fixed": 0,
        "numerics_fixed": 0,
        "balance_chain_mismatches": 0,
    }

    original_len = len(df)

    # --- Step 1: Column name normalization ---
    col_mapping = settings.get("column_mapping", {})
    # The post-extraction CSV should already use standardized names,
    # but handle minor variations
    df.columns = df.columns.str.strip().str.lower()

    # Common column name variants
    col_aliases = {
        "narration": "description",
        "transaction remarks": "description",
        "particulars": "description",
        "remarks": "description",
        "txn date": "date",
        "transaction date": "date",
        "tran date": "date",
        "withdrawal amt.": "debit",
        "withdrawal amount (inr )": "debit",
        "deposit amt.": "credit",
        "deposit amount (inr )": "credit",
        "closing balance": "balance",
        "balance (inr )": "balance",
    }
    df = df.rename(columns={k: v for k, v in col_aliases.items() if k in df.columns})

    # Ensure required columns exist
    required_cols = ["date", "description", "debit", "credit", "balance"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Available columns: {list(df.columns)}"
        )

    # --- Step 2: Remove junk rows ---
    if df.empty:
        # df.apply(..., axis=1) returns an empty DataFrame rather than a Series
        # on an empty frame, which makes the ~mask below raise.
        logger.warning("No rows to validate after column normalisation")
        return df, stats
    junk_mask = df.apply(is_junk_row, axis=1)
    junk_count = junk_mask.sum()
    if junk_count > 0:
        logger.info(f"Removing {junk_count} junk/footer rows")
        df = df[~junk_mask].reset_index(drop=True)
        stats["junk_rows_removed"] = int(junk_count)

    # --- Step 3: Date normalization ---
    dates_before_na = df["date"].isna().sum()
    df["date"] = df["date"].apply(parse_date)
    dates_after_na = df["date"].isna().sum()
    dates_fixed = int(dates_before_na - dates_after_na) if dates_before_na > dates_after_na else 0
    stats["dates_fixed"] = dates_fixed

    # Remove rows where date couldn't be parsed
    unparsed_dates = df["date"].isna().sum()
    if unparsed_dates > 0:
        logger.warning(f"Dropping {unparsed_dates} rows with unparseable dates")
        df = df.dropna(subset=["date"]).reset_index(drop=True)
        stats["junk_rows_removed"] += int(unparsed_dates)

    # Sort by date. mergesort is stable, so rows sharing a date keep the order
    # the extractor read them off the statement in; the default quicksort
    # reshuffles them nondeterministically and corrupts the running balance.
    df = df.sort_values("date", kind="mergesort").reset_index(drop=True)

    # --- Step 4: Numeric coercion ---
    for col in ["debit", "credit", "balance"]:
        original_na = df[col].isna().sum()
        df[col] = df[col].apply(clean_numeric, treat_dr_as_negative=(col == "balance"))
        fixed = int(original_na - df[col].isna().sum()) if original_na > 0 else 0
        stats["numerics_fixed"] += fixed

    # --- Step 4b: Restore intra-day order from the running balance ---
    # Runs after numeric coercion because it needs floats to chain on.
    df, chain_mismatches = reorder_intraday_by_balance_chain(df)
    stats["balance_chain_mismatches"] = chain_mismatches
    if chain_mismatches:
        logger.warning(
            f"{chain_mismatches} rows still break the running-balance chain after "
            f"intra-day reordering -- statement data may be incomplete"
        )

    # --- Step 5: Description cleanup ---
    df["description"] = df["description"].astype(str).str.strip()

    # --- Step 6: Duplicate detection ---
    # Exact duplicate rows (same date, description, debit, credit, balance)
    dup_mask = df.duplicated(subset=["date", "description", "debit", "credit", "balance"],
                             keep="first")
    dup_count = dup_mask.sum()
    if dup_count > 0:
        logger.info(f"Found {dup_count} exact duplicate rows (keeping first occurrence)")
        df = df[~dup_mask].reset_index(drop=True)
        stats["duplicates_removed"] = int(dup_count)

    # --- Step 7: Add bank_name column ---
    df["bank_name"] = bank_name

    # --- Step 8: Add helper columns ---
    df["year_month"] = df["date"].dt.to_period("M").astype(str)

    logger.info(
        f"Validation complete: {stats['total_rows']} → {len(df)} rows "
        f"(removed {stats['junk_rows_removed']} junk, "
        f"{stats['duplicates_removed']} duplicates)"
    )

    return df, stats
