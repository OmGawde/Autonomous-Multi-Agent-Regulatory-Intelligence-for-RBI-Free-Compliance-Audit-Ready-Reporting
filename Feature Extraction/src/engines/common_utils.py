import os
import json
import re
import math
import logging
import threading
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BSA_CommonUtils")

class ConfigManager:
    """Loads and manages versioned rule configuration and taxonomies."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, config_path=None):
        # Double-checked locking. The instance is only published to cls._instance
        # after load_config() has completed, so a concurrent thread can never
        # observe a half-initialised object (the engines construct this from
        # several pipeline worker threads at once).
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super(ConfigManager, cls).__new__(cls)
                    inst.config_path = config_path or os.path.join(os.path.dirname(__file__), "rules_config.json")
                    inst.load_config()
                    cls._instance = inst
        return cls._instance

    def load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        logger.info(f"Loaded rules configuration version: {self.config.get('version', 'unknown')}")

    def get(self, key, default=None):
        return self.config.get(key, default)


class DataSufficiencyEvaluator:
    """Calculates data sufficiency score based on bank statement duration."""
    
    @staticmethod
    def evaluate(df: pd.DataFrame, date_col: str = "date") -> dict:
        if df.empty or date_col not in df.columns:
            return {
                "duration_days": 0,
                "duration_months": 0.0,
                "sufficiency_category": "<6 months",
                "sufficiency_score": 0.0,
                "confidence_multiplier": 0.5
            }
        
        dates = pd.to_datetime(df[date_col]).sort_values()
        start_date = dates.iloc[0]
        end_date = dates.iloc[-1]
        duration_days = (end_date - start_date).days + 1
        duration_months = round(duration_days / 30.4375, 2)
        
        if duration_months < 6.0:
            category = "<6 months"
            score = round(min(1.0, max(0.1, duration_months / 6.0)), 2)
            multiplier = 0.70
        elif 6.0 <= duration_months <= 24.0:
            category = "6-24 months"
            score = 1.0
            multiplier = 1.0
        else:
            category = ">24 months"
            score = 1.0
            multiplier = 1.0

        return {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "duration_days": duration_days,
            "duration_months": duration_months,
            "sufficiency_category": category,
            "sufficiency_score": score,
            "confidence_multiplier": multiplier
        }


class BankStatementParser:
    """Standardizes bank statement CSV data and parses payee names, rails, and entity types."""

    def __init__(self, bank_code: str = "ICICI"):
        self.bank_code = bank_code.upper()
        self.config = ConfigManager().config

    def parse_csv(self, file_path_or_df) -> pd.DataFrame:
        if isinstance(file_path_or_df, pd.DataFrame):
            df = file_path_or_df.copy()
        else:
            df = pd.read_csv(file_path_or_df)

        # Standardize column headers
        col_map = {}
        for col in df.columns:
            clean_col = str(col).strip().lower()
            if "date" in clean_col:
                col_map[col] = "date"
            elif "desc" in clean_col or "narration" in clean_col or "particular" in clean_col:
                col_map[col] = "description"
            elif "debit" in clean_col or "dr" in clean_col:
                col_map[col] = "debit"
            elif "credit" in clean_col or "cr" in clean_col:
                col_map[col] = "credit"
            elif "balance" in clean_col or "bal" in clean_col:
                col_map[col] = "balance"

        df = df.rename(columns=col_map)
        
        # Clean numerical columns
        for num_col in ["debit", "credit", "balance"]:
            if num_col in df.columns:
                df[num_col] = df[num_col].astype(str).str.replace(",", "").str.replace(" ", "")
                df[num_col] = pd.to_numeric(df[num_col], errors="coerce").fillna(0.0)

        # Ensure date format
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        df["txn_id"] = [f"TXN_{i+1:04d}" for i in range(len(df))]

        # Extract parsed payee and rail details
        df["parsed_payee"] = df["description"].apply(self._extract_payee)
        df["rail_type"] = df["description"].apply(self._extract_rail)

        return df

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add the derived columns the behaviour and fraud engines depend on,
        without touching row order, dtypes or any existing column.

        Use this instead of parse_csv() inside the pipeline: parse_csv re-sorts
        by date (destroying the intra-day order recovered from the running
        balance) and re-coerces the numeric columns with a weaker parser.

        Adds: parsed_payee, rail_type, txn_id.
        """
        if df.empty or "description" not in df.columns:
            return df

        out = df.copy()
        out["parsed_payee"] = out["description"].apply(self._extract_payee)
        out["rail_type"] = out["description"].apply(self._extract_rail)
        if "txn_id" not in out.columns:
            out["txn_id"] = [f"TXN_{i + 1:04d}" for i in range(len(out))]
        return out

    def _extract_rail(self, desc: str) -> str:
        desc_upper = str(desc).upper()
        if "UPI" in desc_upper:
            return "UPI"
        elif "ACH" in desc_upper or "NACH" in desc_upper:
            return "ACH/NACH"
        elif "NEFT" in desc_upper:
            return "NEFT"
        elif "IMPS" in desc_upper or "MMT/IMPS" in desc_upper:
            return "IMPS"
        elif "RTGS" in desc_upper:
            return "RTGS"
        elif "CAM/" in desc_upper or "CASH WDL" in desc_upper or "CWDR" in desc_upper or "ATW" in desc_upper:
            return "ATM_CASH"
        elif "CLG/" in desc_upper or "CHEQUE" in desc_upper:
            return "CHEQUE"
        elif "EBA/" in desc_upper:
            return "DIRECT_BROKER"
        else:
            return "OTHER"

    def _extract_payee(self, desc: str) -> str:
        desc_str = str(desc).strip()
        
        # Handle SBI format: TO TRANSFER-UPI/DR/<Ref>/<Payee Name>/...
        sbi_match = re.search(r'(?:TO|BY)\s+TRANSFER-UPI/(?:DR|CR)/[^/]+/([^/]+)', desc_str, re.IGNORECASE)
        if sbi_match:
            return sbi_match.group(1).upper()

        # Handle Axis P2M/P2A: UPI/P2M/<Ref>/<Merchant>/... or UPI/P2A/<Ref>/<Payee>/...
        axis_match = re.search(r'UPI/(?:P2M|P2A)/[^/]+/([^/]+)', desc_str, re.IGNORECASE)
        if axis_match:
            return axis_match.group(1).upper()

        # Handle ICICI/Standard UPI pattern: UPI/<payee_or_vpa>/... or UPI/<ref>/<payee>/...
        if desc_str.startswith("UPI/"):
            parts = desc_str.split("/")
            if len(parts) > 1:
                candidate = parts[1]
                if not candidate.replace(".", "").isdigit() and len(candidate) > 2:
                    return candidate.upper()
                elif len(parts) > 2:
                    return parts[2].upper()

        # Handle BOI format: UPI-PAYEE-VPA-REF
        if desc_str.startswith("UPI-"):
            parts = desc_str.split("-")
            if len(parts) > 1:
                return parts[1].upper()

        # Handle ACH/NACH: ACH/<payee>/...
        if desc_str.startswith("ACH/"):
            parts = desc_str.split("/")
            if len(parts) > 1:
                return parts[1].upper()

        # Handle BIL/NEFT/.../PAYEE/BANK
        if "NEFT/" in desc_str or "IMPS/" in desc_str:
            parts = desc_str.split("/")
            if len(parts) >= 4:
                return parts[3].upper()

        # Handle EBA (ICICI Direct / Broker)
        if desc_str.startswith("EBA/"):
            parts = desc_str.split("-")
            return f"EBA_{parts[0].replace('EBA/', '')}"

        # Fallback clean string (first 30 chars)
        clean = re.sub(r'[/_:-]', ' ', desc_str)
        return clean[:30].strip().upper()


class EvidencePackager:
    """Helper class to build audit-friendly, regulator-compliant evidence objects."""

    @staticmethod
    def create_evidence(flag_id: str, rule_name: str, severity: str, confidence: float, explanation: str, supporting_txns: list) -> dict:
        txns_summary = []
        for t in supporting_txns:
            txns_summary.append({
                "txn_id": t.get("txn_id"),
                "date": str(t.get("date"))[:10] if t.get("date") else None,
                "description": t.get("description"),
                "amount": float(t.get("debit") or t.get("credit") or 0.0),
                "type": "DEBIT" if float(t.get("debit", 0.0)) > 0 else "CREDIT"
            })

        return {
            "flag_id": flag_id,
            "rule_name": rule_name,
            "severity": severity,  # LOW, MEDIUM, HIGH, CRITICAL
            "confidence": round(float(confidence), 2),
            "explanation": explanation,
            "timestamp": datetime.now().isoformat(),
            "supporting_transactions_count": len(txns_summary),
            "supporting_transactions": txns_summary
        }


class FeatureFormatter:
    """Helper class to format ML features with value, confidence, window, version, and missing reason."""

    @staticmethod
    def format_feature(val, confidence: float = 1.0, window: str = "365D", version: str = "1.0.0", missing_reason: str = None) -> dict:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return {
                "value": None,
                "confidence": 0.0,
                "calculation_window": window,
                "version": version,
                "missing_reason": missing_reason or "DATA_NOT_AVAILABLE"
            }
        
        # Format numerical precision where appropriate
        if isinstance(val, (float, np.floating)):
            val_formatted = round(float(val), 4)
        elif isinstance(val, (int, np.integer)):
            val_formatted = int(val)
        elif isinstance(val, (bool, np.bool_)):
            val_formatted = bool(val)
        else:
            val_formatted = val

        return {
            "value": val_formatted,
            "confidence": round(float(confidence), 2),
            "calculation_window": window,
            "version": version,
            "missing_reason": None
        }

    @staticmethod
    def missing_feature(reason: str, window: str = "365D", version: str = "1.0.0") -> dict:
        return FeatureFormatter.format_feature(None, confidence=0.0, window=window, version=version, missing_reason=reason)


class StorageUtils:
    """Utility for exporting outputs to JSON and Parquet formats."""

    class _NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, pd.DataFrame):
                return obj.to_dict(orient="records")
            elif isinstance(obj, pd.Series):
                return obj.tolist()
            elif isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, (np.ndarray,)):
                return obj.tolist()
            elif isinstance(obj, (pd.Timestamp, datetime)):
                return obj.isoformat()
            return super().default(obj)

    @classmethod
    def save_json(cls, data: dict, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, cls=cls._NumpyEncoder)
        logger.info(f"Saved JSON artifact to {output_path}")

    @classmethod
    def save_parquet(cls, df_or_dict, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if isinstance(df_or_dict, pd.DataFrame):
            df = df_or_dict.copy()
        elif isinstance(df_or_dict, dict):
            df = pd.DataFrame([df_or_dict])
        elif isinstance(df_or_dict, list):
            df = pd.DataFrame(df_or_dict)
        else:
            raise ValueError("Input data must be a DataFrame, dict, or list of dicts")

        # Convert complex list/dict object columns to string representation for parquet safety
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                df[col] = df[col].apply(lambda x: json.dumps(x, cls=cls._NumpyEncoder) if x is not None else None)
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

        try:
            df.to_parquet(output_path, index=False)
            logger.info(f"Saved Parquet artifact to {output_path}")
        except Exception as e:
            logger.warning(f"Parquet save failed ({e}), creating CSV fallback at {output_path.replace('.parquet', '.csv')}")
            df.to_csv(output_path.replace('.parquet', '.csv'), index=False)
