"""
Module 1 — Transaction Classification Engine

Hybrid 4-tier classification strategy:
    Tier 1: Bank-specific deterministic rules (rail prefix regex + bank keywords)
    Tier 2: Shared keyword matching (case-insensitive substring)
    Tier 3: Fuzzy merchant matching (RapidFuzz)
    Tier 4: DistilBERT / FinBERT fallback (zero-shot classification)

Supports all banks: SBI, ICICI, Axis, HDFC, Kotak, BOI, Union, BOB, Other.

The SLM is only invoked when all deterministic tiers fail to produce a
high-confidence classification.
"""

import re
import sys
import logging
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
from rapidfuzz import fuzz, process
from rapidfuzz import utils as rf_utils

from src.rules.bank_rules import (
    get_description_parser,
    get_rail_patterns,
    get_bank_specific_keywords,
    is_finacle_bank,
    BANK_RAIL_PATTERNS,
)
from src.engines.recurrence import detect_recurring_groups, IRREGULAR
from src.rules.counterparty import (
    annotate_self_transfer,
    build_counterparty_key,
    canonicalise_keys,
    get_registry,
    is_self_transfer,
)
from src.rules.vpa_registry import match_vpa_intelligence
from src.rules.merchant_rules import (
    NEEDS_KEYWORDS,
    WANTS_KEYWORDS,
    INVESTMENT_KEYWORDS,
    INCOME_KEYWORDS,
    BANKING_KEYWORDS,
    SAVINGS_SIGNAL_KEYWORDS,
    MERCHANT_ENTITY_MAP,
    TRUNCATED_WANTS_VARIANTS,
    find_merchant_entity,
    get_all_keywords_flat,
    find_longest_match,
    keyword_matches,
    classify_remark,
    find_truncated_match,
    REMARK_UNINFORMATIVE,
)

logger = logging.getLogger(__name__)


# ============================================================
# Classification result dataclass-like dict
# ============================================================

def _empty_classification() -> Dict[str, Any]:
    """Return an empty classification result."""
    return {
        "category": "",
        "subcategory": "",
        "merchant_entity": "",
        "needs_wants": "N/A",
        "tags": "",
        "confidence": 0.0,
        "classification_method": "",
    }


# ============================================================
# SLM Backend — pluggable model interface
# ============================================================

class SLMBackend:
    """
    Pluggable SLM backend for Tier 4 classification.
    Supports ONNX Runtime (3x-5x CPU acceleration with int8 quantization)
    and falls back gracefully to standard PyTorch DistilBERT.
    """

    def __init__(self, model_name: str = "typeform/distilbert-base-uncased-mnli",
                 confidence_threshold: float = 0.5,
                 device: str = "auto",
                 use_onnx: bool = True):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.use_onnx = use_onnx
        self._pipeline = None
        self._loaded = False
        self._load_attempted = False
        self.is_onnx_active = False
        self.resolved_device = -1

        # Candidate labels derived from our taxonomy
        self.candidate_labels = [
            "salary", "interest income", "dividend",
            "rent payment", "grocery shopping", "utility bill",
            "fuel expense", "taxi ride", "healthcare medical",
            "insurance premium", "education fee", "loan EMI payment",
            "food delivery", "entertainment subscription",
            "online shopping", "travel booking", "leisure",
            "investment SIP mutual fund", "PPF deposit", "NPS pension",
            "fixed deposit", "stock trading",
            "ATM cash withdrawal", "bank transfer", "cheque payment",
            "bank charge", "refund reversal",
        ]

    def _load_model(self):
        """Lazy-load the model with ONNX Runtime int8 optimization or PyTorch fallback."""
        if self._loaded or self._load_attempted:
            return

        self._load_attempted = True
        import os
        import sys
        from pathlib import Path

        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN_WARNING"] = "1"
        os.environ["USE_TF"] = "0"

        # On Windows, register torch/lib DLL directory to prevent cuDNN DLL resolution failures (WinError 126)
        if sys.platform == "win32":
            torch_lib = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages", "torch", "lib")
            if os.path.exists(torch_lib):
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(torch_lib)
                    except Exception:
                        pass
                os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")

        try:
            import torch
        except Exception as e:
            logger.warning(f"PyTorch could not be initialized ({e}). Operating in deterministic heuristic mode.")
            if "torch" in sys.modules and not hasattr(sys.modules["torch"], "__version__"):
                sys.modules.pop("torch", None)
            self._loaded = False
            self._pipeline = None
            return

        # Resolve device (GPU 0 if CUDA is available, else CPU)
        if self.device == "auto" or self.device is None:
            self.resolved_device = 0 if torch.cuda.is_available() else -1
        elif isinstance(self.device, str) and self.device.lower() in ["cuda", "gpu"]:
            self.resolved_device = 0 if torch.cuda.is_available() else -1
        elif isinstance(self.device, int):
            self.resolved_device = self.device
        else:
            self.resolved_device = -1

        device_desc = f"GPU ({torch.cuda.get_device_name(0)})" if self.resolved_device >= 0 else "CPU"

        # Resolve model path (prioritize bundled local model directory for 100% offline support)
        local_dir = Path(__file__).parent.parent / "models" / "distilbert-mnli"
        is_local = False
        target_model = self.model_name

        if (Path(self.model_name).exists() and (Path(self.model_name) / "config.json").exists()):
            target_model = str(Path(self.model_name).resolve())
            is_local = True
        elif local_dir.exists() and (local_dir / "config.json").exists():
            target_model = str(local_dir)
            is_local = True
        elif target_model == "distilbert-base-uncased":
            target_model = "typeform/distilbert-base-uncased-mnli"

        if is_local:
            logger.info(f"Using local pre-bundled SLM model on {device_desc}: {target_model}")

        if self.use_onnx and not is_local:
            try:
                import io
                from transformers import pipeline as hf_pipeline, AutoTokenizer
                from optimum.onnxruntime import ORTModelForSequenceClassification

                logger.info(f"Attempting ONNX Runtime model load: {target_model}")
                _real_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    model = ORTModelForSequenceClassification.from_pretrained(
                        target_model, export=True
                    )
                    tokenizer = AutoTokenizer.from_pretrained(target_model)
                    self._pipeline = hf_pipeline(
                        "zero-shot-classification",
                        model=model,
                        tokenizer=tokenizer,
                        device=self.resolved_device,
                    )
                finally:
                    sys.stdout = _real_stdout
                self.is_onnx_active = True
                self._loaded = True
                logger.info(f"ONNX Runtime SLM backend loaded successfully on {device_desc}")
                return
            except Exception as e:
                logger.warning(f"ONNX Runtime initialization unavailable ({e}); falling back to PyTorch model")

        try:
            from transformers import pipeline as hf_pipeline
            import io
            logger.info(f"Loading SLM model on {device_desc}: {target_model}")
            # Suppress noisy [transformers] model LOAD REPORT printed to stdout
            _real_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                # DistilBERT's forward() takes no `token_type_ids`, but this
                # tokenizer's saved config advertises them, so the pipeline
                # passes them straight through and the call dies with
                # "unexpected keyword argument 'token_type_ids'". It only
                # surfaces on transformers 4.x, which is the version
                # FinanceParam requires -- see param_adapter for why the
                # project is pinned there. Naming the inputs DistilBERT
                # actually accepts keeps this working on both.
                from transformers import AutoTokenizer as _AutoTok
                _tok = _AutoTok.from_pretrained(
                    target_model, **({"local_files_only": True} if is_local else {})
                )
                _tok.model_input_names = ["input_ids", "attention_mask"]

                kwargs = {
                    "task": "zero-shot-classification",
                    "model": target_model,
                    "tokenizer": _tok,
                    "device": self.resolved_device,
                }
                if self.resolved_device >= 0:
                    kwargs["torch_dtype"] = torch.float16
                if is_local:
                    kwargs["local_files_only"] = True
                self._pipeline = hf_pipeline(**kwargs)
            finally:
                sys.stdout = _real_stdout
            self._loaded = True
            logger.info(f"SLM model loaded successfully on {device_desc}")
        except Exception as e:
            logger.error(f"Failed to load SLM model: {e}")
            logger.warning("Tier 4 (SLM) classification will be unavailable")
            self._loaded = False

    def classify(self, description: str) -> Tuple[str, float]:
        """
        Classify a transaction description using zero-shot classification.

        Returns:
            Tuple of (best_label, confidence_score)
        """
        res = self.classify_batch([description])
        return res[0] if res else ("Unknown", 0.0)

    def classify_batch(self, descriptions: List[str], batch_size: int = 64) -> List[Tuple[str, float]]:
        """Classify a batch of descriptions using vectorized pipeline inference."""
        if not descriptions:
            return []

        if not self._loaded:
            self._load_model()

        if self._pipeline is None:
            return [("Unknown", 0.0)] * len(descriptions)

        try:
            results = self._pipeline(
                descriptions,
                candidate_labels=self.candidate_labels,
                multi_label=False,
                batch_size=batch_size,
            )
            # HuggingFace pipeline returns a dict for a single str or list of dicts for list of strs
            if isinstance(results, dict):
                results = [results]
            out = []
            for r in results:
                best_label = r["labels"][0]
                confidence = float(r["scores"][0])
                out.append((best_label, confidence))
            return out
        except Exception as e:
            logger.error(f"Batch SLM classification failed: {e}")
            return [("Unknown", 0.0)] * len(descriptions)


# ============================================================
# SLM label → our taxonomy mapping
# ============================================================

SLM_LABEL_MAP: Dict[str, Dict[str, str]] = {
    "salary": {"category": "Income", "subcategory": "Salary", "needs_wants": "N/A"},
    "interest income": {"category": "Income", "subcategory": "Interest", "needs_wants": "N/A"},
    "dividend": {"category": "Income", "subcategory": "Dividend", "needs_wants": "N/A"},
    "rent payment": {"category": "Expense", "subcategory": "Rent", "needs_wants": "Need"},
    "grocery shopping": {"category": "Expense", "subcategory": "Grocery / Supermarket", "needs_wants": "Need"},
    "utility bill": {"category": "Expense", "subcategory": "Electricity / Water / Gas", "needs_wants": "Need"},
    "fuel expense": {"category": "Expense", "subcategory": "Fuel", "needs_wants": "Need"},
    "taxi ride": {"category": "Expense", "subcategory": "Taxi", "needs_wants": "Need"},
    "healthcare medical": {"category": "Expense", "subcategory": "Healthcare", "needs_wants": "Need"},
    "insurance premium": {"category": "Expense", "subcategory": "Insurance", "needs_wants": "Need"},
    "education fee": {"category": "Expense", "subcategory": "Education", "needs_wants": "Need"},
    "loan EMI payment": {"category": "Expense", "subcategory": "Loan / EMI", "needs_wants": "Need"},
    "food delivery": {"category": "Expense", "subcategory": "Food Delivery", "needs_wants": "Want"},
    "entertainment subscription": {"category": "Expense", "subcategory": "Entertainment", "needs_wants": "Want"},
    "online shopping": {"category": "Expense", "subcategory": "Shopping", "needs_wants": "Want"},
    "travel booking": {"category": "Expense", "subcategory": "Travel", "needs_wants": "Want"},
    "leisure": {"category": "Expense", "subcategory": "Leisure", "needs_wants": "Want"},
    "investment SIP mutual fund": {"category": "Investment", "subcategory": "Mutual Funds / SIP", "needs_wants": "N/A"},
    "PPF deposit": {"category": "Investment", "subcategory": "PPF", "needs_wants": "N/A"},
    "NPS pension": {"category": "Investment", "subcategory": "NPS", "needs_wants": "N/A"},
    "fixed deposit": {"category": "Investment", "subcategory": "FD / RD", "needs_wants": "N/A"},
    "stock trading": {"category": "Investment", "subcategory": "Equity Trading", "needs_wants": "N/A"},
    "ATM cash withdrawal": {"category": "Banking", "subcategory": "ATM Withdrawal", "needs_wants": "N/A"},
    "bank transfer": {"category": "Transfer", "subcategory": "Transfer", "needs_wants": "N/A"},
    "cheque payment": {"category": "Banking", "subcategory": "Cheque", "needs_wants": "N/A"},
    "bank charge": {"category": "Banking", "subcategory": "Bank Charges", "needs_wants": "N/A"},
    "refund reversal": {"category": "Income", "subcategory": "Refund / Reversal", "needs_wants": "N/A"},
}


# ============================================================
# Main Classifier
# ============================================================

class TransactionClassifier:
    """
    Multi-bank hybrid transaction classifier.

    Priority:
        1. Bank-specific deterministic rules
        2. Shared keyword matching
        3. Fuzzy merchant matching
        4. SLM fallback
    """

    def __init__(self, settings: Optional[dict] = None):
        self.settings = settings or {}
        model_config = self.settings.get("model", {})
        fuzzy_config = self.settings.get("fuzzy", {})

        self.fuzzy_default_threshold = fuzzy_config.get("default_threshold", 80)
        self.fuzzy_finacle_threshold = fuzzy_config.get("finacle_threshold", 70)

        # SLM backend — lazy loaded
        self._slm = SLMBackend(
            model_name=model_config.get("name", "typeform/distilbert-base-uncased-mnli"),
            confidence_threshold=model_config.get("confidence_threshold", 0.5),
            device=model_config.get("device", "auto"),
        )

        # Optional applicant context: lets an applicant-scoped counterparty
        # override win over a global one.
        self.applicant_id = (self.settings or {}).get("applicant_id")
        # Name of the person the statement belongs to, used to tell a transfer
        # between their own accounts apart from a payment to someone else.
        self.account_holder_name = (self.settings or {}).get("account_holder_name", "")
        self._recurrence_config = (self.settings or {}).get("recurrence", {})

        # Pre-build fuzzy matching corpus
        # Match against the category keyword vocabulary as well as the merchant
        # map. The corpus used to be merchant keys alone, so even a successful
        # fuzzy hit on e.g. "PAYTM" fell through _lookup_keyword_category to the
        # default ("Expense", "Other") because that key is not in any keyword dict.
        _seen = set()
        self._fuzzy_corpus = [
            k for k in (get_all_keywords_flat() + list(MERCHANT_ENTITY_MAP.keys()))
            if not (k in _seen or _seen.add(k))
        ]

        logger.info("TransactionClassifier initialized")

    def classify_dataframe(self, df: pd.DataFrame, bank_name: str) -> pd.DataFrame:
        """
        Classify all transactions in a DataFrame.

        Args:
            df: DataFrame with columns: date, description, debit, credit, balance, bank_name
            bank_name: Bank identifier for rule selection

        Returns:
            DataFrame with added classification columns
        """
        logger.info(f"Classifying {len(df)} transactions for bank: {bank_name}")

        # Get bank-specific components
        parse_description = get_description_parser(bank_name)
        rail_patterns = get_rail_patterns(bank_name)
        bank_keywords = get_bank_specific_keywords(bank_name)
        use_finacle_fuzzy = is_finacle_bank(bank_name)

        # Get per-bank fuzzy threshold from config
        bank_config = self.settings.get("banks", {}).get(bank_name, {})
        fuzzy_threshold = bank_config.get(
            "fuzzy_match_threshold",
            self.fuzzy_finacle_threshold if use_finacle_fuzzy else self.fuzzy_default_threshold
        )

        # Initialize classification columns
        classification_cols = [
            "category", "subcategory",
            "merchant_entity", "needs_wants", "tags", "confidence",
            "classification_method",
            # Audit trail: which specific rule and which keyword produced the
            # label. "classification_method" alone says "keyword" but not which
            # one, which made misclassifications undiagnosable from the CSV.
            "matched_rule", "matched_keyword",
            # Counterparty identity and shape-derived annotation.
            "counterparty_key", "recurrence_group", "recurrence_type",
            "is_self_transfer",
            "suggested_subcategory", "suggestion_reason",
        ]
        for col in classification_cols:
            df[col] = ""
        df["transaction_type"] = ""
        df["confidence"] = 0.0

        # Track SLM candidates (batch later)
        slm_indices: List[int] = []

        salary_payers = self._find_salary_payers(df, parse_description)

        for idx, row in df.iterrows():
            description = str(row.get("description", "")).strip()
            debit = float(row.get("debit", 0))
            credit = float(row.get("credit", 0))

            # Determine transaction type
            txn_type = "Credit" if credit > 0 else "Debit"
            df.at[idx, "transaction_type"] = txn_type

            # Parse description for structural info
            parsed = parse_description(description)

            # --- Tier 1: Bank-specific deterministic rules ---
            result = self._tier1_bank_rules(
                description, debit, credit, parsed,
                rail_patterns, bank_keywords, bank_name
            )
            if result["confidence"] > 0:
                for k, v in result.items():
                    df.at[idx, k] = v
                continue

            # --- Tier 1.5: UPI VPA & Merchant Intelligence ---
            vpa_result = match_vpa_intelligence(description, debit, credit)
            if vpa_result and vpa_result.get("confidence", 0) > 0:
                for k, v in vpa_result.items():
                    df.at[idx, k] = v
                continue

            # --- Tier 2: Shared keyword matching ---
            result = self._tier2_keyword_match(description, debit, credit)
            if result["confidence"] > 0:
                for k, v in result.items():
                    df.at[idx, k] = v
                continue

            # --- Tier 3: Fuzzy matching ---
            result = self._tier3_fuzzy_match(
                description, debit, credit, fuzzy_threshold
            )
            if result["confidence"] > 0:
                for k, v in result.items():
                    df.at[idx, k] = v
                continue

            # --- Tier 3.5: Rail transfer fallback (before SLM) ---
            #
            # A payment rail says how money moved, not what it was for. This
            # tier used to stamp "Other Expense"/"Other Income" at a hardcoded
            # 0.85 -- on Axis that was 361 of 422 rows reported as
            # high-confidence when nothing had actually been identified.
            #
            # Person-to-person transfers are now given their own real category
            # rather than being booked as consumer spending, and the residual
            # rail-only rows carry a confidence that reflects what is known.
            desc_upper = description.upper()

            # Investment and pension collection handles arrive on the UPI rail,
            # so the rail rule claimed them as person-to-person transfers --
            # e.g. Rs 10,000 to "npscams.bdpg@ic" was booked as a P2P transfer
            # even though the label map already knows NPS is an investment.
            if any(h in desc_upper for h in ("NPSCAMS", "NPS TRUST", "NSDL-NPS", "PROTEAN",
                                             "CAMSONLINE", "KFINTECH", "CAMS ")):
                df.at[idx, "category"] = "Investment"
                df.at[idx, "subcategory"] = "NPS" if "NPS" in desc_upper else "Mutual Funds / SIP"
                df.at[idx, "needs_wants"] = "Not Applicable"
                df.at[idx, "confidence"] = 0.92
                df.at[idx, "classification_method"] = "bank_rule"
                df.at[idx, "matched_rule"] = "investment_handle"
                continue

            # A credit from an employer we have already seen paying salary is
            # income, whichever rail it arrives on. Without this a Rs 12,000
            # NEFT from the same employer as 19 ACH salary rows sat in Transfer.
            if credit > 0 and salary_payers:
                if any(p and p in desc_upper for p in salary_payers):
                    df.at[idx, "category"] = "Income"
                    df.at[idx, "subcategory"] = "Salary"
                    df.at[idx, "merchant_entity"] = (parsed.get("payee") or "").strip()
                    df.at[idx, "needs_wants"] = "Not Applicable"
                    df.at[idx, "confidence"] = 0.88
                    df.at[idx, "classification_method"] = "bank_rule"
                    df.at[idx, "matched_rule"] = "known_salary_payer"
                    continue

            transfer_prefixes = ("BIL/NEFT/", "NEFT/", "NEFT-", "MMT/IMPS/", "IMPS/", "RTGS/", "INF/", "BIL/ONL/", "UPI/")
            is_rail_row = desc_upper.startswith(transfer_prefixes) or "TRANSFER-UPI" in desc_upper \
                or bool(re.match(r"^(?:WDL|DEP)\s+TFR\s+", desc_upper))

            if is_rail_row:
                payee = (parsed.get("payee") or "").strip()

                # The payer's own remark is the only statement of purpose these
                # rows carry. Consult it before falling back to the rail.
                remark = (parsed.get("remarks") or "").strip()
                remark_subcat = self._subcategory_from_remark(remark)
                remark_nw = classify_remark(remark)

                # A recognisable merchant in the payee field is a purchase, not
                # a person-to-person transfer -- banks that do not emit a P2M
                # marker (SBI) would otherwise route "Google I" to P2P.
                if payee and debit > 0:
                    payee_match = self._tier2_keyword_match(payee, debit, credit)
                    if payee_match["confidence"] > 0 and payee_match["category"] == "Expense":
                        for k, v in payee_match.items():
                            df.at[idx, k] = v
                        df.at[idx, "classification_method"] = "rail_transfer_rule"
                        df.at[idx, "matched_rule"] = "upi_payee_merchant"
                        continue

                    # The payee field is clipped by the bank, so a full merchant
                    # name cannot match it directly ("Google I" for Google India).
                    trunc = find_truncated_match(self._fuzzy_corpus, payee)
                    if trunc:
                        cat, subcat, nw = self._lookup_keyword_category(trunc)
                        if cat == "Expense" and subcat != "Other":
                            df.at[idx, "category"] = cat
                            df.at[idx, "subcategory"] = subcat
                            df.at[idx, "needs_wants"] = nw
                            df.at[idx, "merchant_entity"] = MERCHANT_ENTITY_MAP.get(trunc, trunc)
                            df.at[idx, "confidence"] = 0.70
                            df.at[idx, "classification_method"] = "rail_transfer_rule"
                            df.at[idx, "matched_rule"] = f"upi_payee_truncated:{trunc}"
                            continue

                if parsed.get("is_p2a") or (parsed.get("rail") == "UPI" and not parsed.get("is_p2m")
                                            and payee and not payee.replace(".", "").isdigit()):
                    # UPI person-to-person. Usually a transfer between
                    # individuals rather than a purchase -- but many carry an
                    # explicit purchase remark ("medici", "cable", "taxi"),
                    # which makes them real spending against an individual
                    # payee (the local chemist, the cable operator).
                    if debit > 0 and remark_subcat:
                        df.at[idx, "category"] = "Expense"
                        df.at[idx, "subcategory"] = remark_subcat
                        df.at[idx, "needs_wants"] = remark_nw
                        df.at[idx, "confidence"] = 0.72
                        df.at[idx, "matched_rule"] = f"upi_p2a_remark:{remark[:12]}"
                    else:
                        df.at[idx, "category"] = "Transfer"
                        df.at[idx, "subcategory"] = "P2P Transfer In" if credit > 0 else "P2P Transfer Out"
                        df.at[idx, "needs_wants"] = "Not Applicable"
                        df.at[idx, "confidence"] = 0.80
                        df.at[idx, "matched_rule"] = "upi_p2a_rail"
                    df.at[idx, "merchant_entity"] = payee
                    df.at[idx, "classification_method"] = "rail_transfer_rule"
                    continue

                if parsed.get("is_p2m"):
                    # UPI merchant payment. The payee is usually a small local
                    # trader absent from every dictionary, but the rail
                    # establishes this is a retail purchase and the remark often
                    # establishes what for.
                    #
                    # needs_wants used to be hardcoded "Want" here, which on one
                    # statement mislabelled 155 rows -- oil, milk, dettol,
                    # medicine and bus fares booked as discretionary spend.
                    df.at[idx, "category"] = "Expense"
                    df.at[idx, "subcategory"] = remark_subcat or "Merchant Payment (UPI)"
                    df.at[idx, "merchant_entity"] = payee
                    df.at[idx, "needs_wants"] = remark_nw
                    df.at[idx, "confidence"] = 0.75 if remark_subcat else 0.60
                    df.at[idx, "classification_method"] = "rail_transfer_rule"
                    df.at[idx, "matched_rule"] = (
                        f"upi_p2m_remark:{remark[:12]}" if remark_subcat else "upi_p2m_rail"
                    )
                    continue

                if payee and not payee.replace(".", "").replace(" ", "").isdigit():
                    # NEFT/IMPS/RTGS to or from a named counterparty that no
                    # rule matched: a bank transfer, not consumer spending.
                    df.at[idx, "category"] = "Transfer"
                    df.at[idx, "subcategory"] = "Bank Transfer In" if credit > 0 else "Bank Transfer Out"
                    df.at[idx, "merchant_entity"] = payee
                    df.at[idx, "needs_wants"] = "N/A"
                    df.at[idx, "confidence"] = 0.70
                    df.at[idx, "classification_method"] = "rail_transfer_rule"
                    continue

                cat = "Income" if credit > 0 else "Expense"
                subcat = "Other Income" if credit > 0 else "Other Expense"
                df.at[idx, "category"] = cat
                df.at[idx, "subcategory"] = subcat
                df.at[idx, "merchant_entity"] = payee
                df.at[idx, "needs_wants"] = "N/A"
                # Rail-only: direction is certain, purpose is not.
                df.at[idx, "confidence"] = 0.35
                df.at[idx, "classification_method"] = "rail_transfer_rule"
                continue

            # --- Tier 4: Queue for SLM ---
            slm_indices.append(idx)

        # --- Batch SLM classification for remaining ---
        if slm_indices:
            logger.info(f"Running SLM on {len(slm_indices)} unresolved transactions")
            self._tier4_slm_batch(df, slm_indices)

        # Fill any remaining unclassified & assign multi-label tags
        for idx, row in df.iterrows():
            if not df.at[idx, "category"]:
                df.at[idx, "category"] = "Uncategorized"
                df.at[idx, "subcategory"] = "Unknown"
                df.at[idx, "confidence"] = 0.0
                df.at[idx, "classification_method"] = "none"
            
            # Multi-label additive tag assignment
            desc = str(row.get("description", ""))
            cat = str(df.at[idx, "category"])
            subcat = str(df.at[idx, "subcategory"])
            ttype = str(df.at[idx, "transaction_type"])
            entity = str(df.at[idx, "merchant_entity"])
            tags_list = self._assign_tags(desc, cat, subcat, ttype, entity)
            df.at[idx, "tags"] = ", ".join(tags_list)

        # Normalise needs/wants after all tiers have run, so the value depends on
        # the final subcategory rather than on whichever tier happened to fire.
        # Counterparty identity, then the two passes that depend on it. Order
        # matters: overrides and recurrence can change category/subcategory, so
        # both run BEFORE needs/wants is finalised from the subcategory.
        df = self._assign_counterparty_keys(df, parse_description)
        df = self._mark_self_transfers(df, parse_description)
        df = self._apply_counterparty_overrides(df)
        df = self._label_recurring_obligations(df)

        df = self._finalise_needs_wants(df)
        # NOTE: merchant-entity normalisation is deliberately NOT applied here.
        # Collapsing truncated spellings ("GIRISH BABAJI G" / "GIRISH B") is
        # economically right but destroys the amount-consistency signal that
        # _detect_recurring_salary depends on: merging a regular monthly credit
        # with ad-hoc transfers from the same person pushes the group's
        # coefficient of variation past the salary threshold. On a real SBI
        # statement that dropped detected income from Rs 1,20,766 to Rs 766 and
        # sent DTI from 1.63 to 146.9. _normalise_merchant_entities is retained
        # below for reporting-level aggregation (merchant diversity,
        # counterparty concentration), where it is safe, but it must not run
        # before income detection.

        classified_count = len(df[df["category"] != "Uncategorized"])
        logger.info(
            f"Classification complete: {classified_count}/{len(df)} classified "
            f"({len(slm_indices)} required SLM)"
        )

        return df

    # Subcategories whose needs/wants is knowable from the label alone.
    _SUBCATEGORY_NEEDS_WANTS = {
        # Essentials
        "Rent": "Need", "Home Loan EMI": "Need", "Society / Property Tax": "Need",
        "Grocery / Supermarket": "Need", "Electricity / Water / Gas": "Need",
        "Internet / Mobile / Broadband": "Need", "Fuel": "Need",
        "Metro / Bus / Toll / Parking": "Need", "Taxi": "Need",
        "Healthcare": "Need", "Insurance": "Need", "Education": "Need",
        "Loan / EMI": "Need",
        # Discretionary
        "Food Delivery": "Want", "Entertainment": "Want", "Shopping": "Want",
        "Travel": "Want", "Leisure": "Want", "Electronics": "Want",
        "Fashion": "Want", "Beauty": "Want", "Luxury": "Want",
        # A liability settlement, not consumption -- the underlying spend was
        # categorised when it happened on the card, which this statement cannot see.
        "Credit Card Repayment": "Unknown",
    }

    # Labels that state a rail or an instrument but no purpose. These are the
    # rows recurrence and overrides are allowed to overwrite; anything the
    # deterministic tiers actually identified is left alone.
    _UNRESOLVED_SUBCATS = {
        "Bank Transfer In", "Bank Transfer Out", "P2P Transfer In", "P2P Transfer Out",
        "Merchant Payment (UPI)", "Cheque", "Other Expense", "Other Income", "Other",
        "Uncategorized", "Unknown",
    }

    @staticmethod
    def _assign_counterparty_keys(df: pd.DataFrame, parse_description) -> pd.DataFrame:
        """
        Add a normalised `counterparty_key`, distinct from `merchant_entity`.

        Kept separate on purpose. Normalising `merchant_entity` itself merged a
        payer's regular monthly credit with their ad-hoc transfers and pushed the
        group past the salary detector's variance gate -- detected income on one
        statement fell from Rs 1,20,766 to Rs 766. Grouping and overrides use
        this key; income detection keeps reading merchant_entity untouched.
        """
        if df.empty:
            return df

        keys = []
        for _, row in df.iterrows():
            desc = str(row.get("description", ""))
            parsed = parse_description(desc)
            keys.append(build_counterparty_key(
                payee=parsed.get("payee", "") or "",
                description=desc,
                merchant_entity=str(row.get("merchant_entity", "") or ""),
                counterparty_bank=parsed.get("counterparty_bank", "") or "",
            ))

        # Collapse truncation variants onto their longest spelling: Axis emits
        # the same person as "FAIZ AQEE" (9 chars) and "FAIZ AQEEL QURESHI" (21)
        # depending on which of its two UPI schemas wrote the row.
        canonical = canonicalise_keys(keys)
        df["counterparty_key"] = [canonical.get(k, k) for k in keys]
        return df

    def _mark_self_transfers(self, df: pd.DataFrame, parse_description) -> pd.DataFrame:
        """
        Flag movements between the account holder's own accounts.

        Money you move from your own savings account to your own current account
        is neither income nor spending, and counting it as either distorts both.
        On one real statement every rupee of detected income was a recurring NEFT
        from a counterparty sharing the holder's surname.

        Requires the account-holder name, which the web app captures at upload
        and the CLI takes via --account-holder. Without it nothing is marked --
        a shared surname is a relative at least as often as a second account.
        """
        df["is_self_transfer"] = False
        holder = (self.account_holder_name or "").strip()
        if df.empty or not holder:
            return df

        marked = 0
        for idx in df.index:
            desc = str(df.at[idx, "description"] or "")
            parsed = parse_description(desc)
            is_self, reason = is_self_transfer(
                account_holder=holder,
                payee=parsed.get("payee", "") or "",
                description=desc,
                counterparty_key=str(df.at[idx, "counterparty_key"] or ""),
            )
            if not is_self:
                continue

            df.at[idx, "is_self_transfer"] = True
            df.at[idx, "category"] = "Transfer"
            df.at[idx, "subcategory"] = annotate_self_transfer(
                df.at[idx, "subcategory"] or
                ("P2P Transfer In" if float(df.at[idx, "credit"] or 0) > 0 else "P2P Transfer Out")
            )
            df.at[idx, "needs_wants"] = "Not Applicable"
            df.at[idx, "classification_method"] = "self_transfer"
            df.at[idx, "matched_rule"] = f"self_transfer:{reason}"
            marked += 1

        if marked:
            logger.info(
                f"Self-transfer detection: {marked} transactions matched account "
                f"holder '{holder}' and were excluded from income and expenses"
            )
        return df

    def _apply_counterparty_overrides(self, df: pd.DataFrame,
                                      applicant_id: Optional[str] = None) -> pd.DataFrame:
        """
        Apply human-supplied counterparty labels.

        Highest authority in the pipeline, per the specification's
        "Entity Override Layer overrides Tier 1" -- a person who has told us what
        a counterparty is outranks every heuristic. Only rows whose current label
        states no purpose are overwritten, so a confident rule result is never
        silently replaced.
        """
        if df.empty or "counterparty_key" not in df.columns:
            return df

        registry = get_registry()
        applied = 0
        for idx in df.index:
            key = str(df.at[idx, "counterparty_key"] or "")
            if not key:
                continue
            subcat = str(df.at[idx, "subcategory"] or "")
            if subcat and subcat not in self._UNRESOLVED_SUBCATS:
                continue

            entry = registry.lookup(key, applicant_id=applicant_id or self.applicant_id)
            if not entry:
                continue

            df.at[idx, "category"] = entry["category"]
            df.at[idx, "subcategory"] = entry["subcategory"]
            df.at[idx, "needs_wants"] = entry.get("needs_wants", "Unknown")
            df.at[idx, "confidence"] = 0.99
            df.at[idx, "classification_method"] = "counterparty_override"
            df.at[idx, "matched_rule"] = f"override:{entry.get('scope', 'global')}"
            applied += 1

        if applied:
            logger.info(f"Counterparty overrides applied to {applied} transactions")
        return df

    def _label_recurring_obligations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Describe unresolved transactions by their repeating shape.

        Where a narration names nothing, twelve payments of the same amount 31
        days apart still say "standing obligation" -- and that is the fact a
        lender needs. 79.9% of unresolved debit value sits in a group of three or
        more payments to one counterparty.

        This annotates rather than asserts a purpose: the subcategory becomes
        "Recurring Obligation", and the suggestion fields carry a proposed
        category for a human to confirm.
        """
        if df.empty or "counterparty_key" not in df.columns:
            return df

        for col in ("recurrence_group", "recurrence_type", "recurrence_confidence",
                    "suggested_subcategory", "suggestion_confidence", "suggestion_reason"):
            if col not in df.columns:
                df[col] = "" if col != "recurrence_confidence" else 0.0

        labelled = 0
        for amount_col in ("debit", "credit"):
            if amount_col not in df.columns:
                continue
            groups = detect_recurring_groups(
                df, key_col="counterparty_key", amount_col=amount_col,
                config=self._recurrence_config,
            )
            for group in groups:
                if group.cadence == IRREGULAR and not group.is_fixed:
                    continue
                for idx in group.indices:
                    df.at[idx, "recurrence_group"] = group.key
                    df.at[idx, "recurrence_type"] = group.cadence
                    df.at[idx, "recurrence_confidence"] = group.confidence

                    subcat = str(df.at[idx, "subcategory"] or "")
                    if subcat not in self._UNRESOLVED_SUBCATS:
                        continue
                    if not (group.is_fixed and group.cadence != IRREGULAR):
                        continue

                    df.at[idx, "subcategory"] = "Recurring Obligation"
                    df.at[idx, "confidence"] = max(
                        float(df.at[idx, "confidence"] or 0), group.confidence)
                    df.at[idx, "classification_method"] = "recurrence"
                    df.at[idx, "matched_rule"] = f"recurring:{group.cadence.lower()}"
                    df.at[idx, "suggestion_reason"] = group.describe()
                    df.at[idx, "suggestion_confidence"] = group.confidence
                    labelled += 1

        if labelled:
            logger.info(f"Recurring obligations identified on {labelled} transactions")
        return df

    @staticmethod
    def _find_salary_payers(df: pd.DataFrame, parse_description) -> List[str]:
        """
        Names of counterparties that pay this account recurring salary.

        A single pre-pass over the credits: a payer seen on an ACH/NACH credit
        (or with an explicit salary word) at least twice is treated as an
        employer. Used to recognise the same employer when it later pays over a
        different rail, which the rail fallback would otherwise book as a
        transfer.
        """
        if df.empty or "credit" not in df.columns:
            return []

        counts: Dict[str, int] = {}
        for _, row in df[df["credit"] > 0].iterrows():
            desc = str(row.get("description", ""))
            desc_u = desc.upper()
            is_salary_ish = (
                any(k in desc_u for k in ("SALARY", "PAYROLL", "COSAL", "STIPEND"))
                or desc_u.startswith(("ACH/", "ACH-CR-", "NACH"))
            )
            if not is_salary_ish:
                continue
            payee = (parse_description(desc).get("payee") or "").strip().upper()
            # Long enough to be a distinctive name, not a reference number.
            if len(payee) >= 6 and not payee.replace(" ", "").isdigit():
                counts[payee] = counts.get(payee, 0) + 1

        return [name for name, n in counts.items() if n >= 2]

    @staticmethod
    def _normalise_merchant_entities(df: pd.DataFrame, threshold: int = 88) -> pd.DataFrame:
        """
        Collapse truncated spellings of the same counterparty.

        Banks clip the payee field at differing widths, so one person appears as
        "GIRISH BAB", "GIRISH B" and "GIRISHGIDAYE*NE" across two statements,
        and "V V TRADE" / "V V TRADERS" within one. Counting those as distinct
        counterparties inflates merchant diversity and understates concentration,
        so any per-merchant aggregate is wrong before it is computed.

        Names are grouped when one is a prefix of another or they match above
        `threshold`, and the longest spelling in each group becomes canonical.
        """
        if df.empty or "merchant_entity" not in df.columns:
            return df

        names = sorted(
            {str(v).strip() for v in df["merchant_entity"] if str(v).strip()},
            key=len,
            reverse=True,
        )
        canonical: Dict[str, str] = {}
        for name in names:
            upper = name.upper()
            match = None
            for existing in canonical.values():
                e_upper = existing.upper()
                if e_upper.startswith(upper) or upper.startswith(e_upper):
                    match = existing
                    break
                if fuzz.ratio(upper, e_upper) >= threshold:
                    match = existing
                    break
            canonical[name] = match or name

        merged = sum(1 for k, v in canonical.items() if k != v)
        if merged:
            logger.info(f"Merchant normalisation: merged {merged} truncated spellings")
            df["merchant_entity"] = df["merchant_entity"].apply(
                lambda v: canonical.get(str(v).strip(), v) if str(v).strip() else v
            )
        return df

    def _finalise_needs_wants(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Guarantee every row carries a meaningful needs/wants value.

        Three problems this fixes:
          * the literal "N/A" was written for both "not applicable" and "not
            determined", and pandas reads it back as NaN, so downstream code
            could not tell them apart -- 476 of 720 debits were affected
          * the value came from whichever tier matched, so two rows with the
            same final subcategory could disagree
          * non-expense rows (transfers, investments, income) were left blank
            rather than explicitly marked not applicable
        """
        if df.empty or "category" not in df.columns:
            return df

        for idx in df.index:
            category = str(df.at[idx, "category"] or "")
            subcat = str(df.at[idx, "subcategory"] or "")
            current = df.at[idx, "needs_wants"]
            current = "" if pd.isna(current) else str(current).strip()

            # Needs/wants is only meaningful for consumption.
            if category != "Expense":
                df.at[idx, "needs_wants"] = "Not Applicable"
                continue

            mapped = self._SUBCATEGORY_NEEDS_WANTS.get(subcat)
            if mapped:
                df.at[idx, "needs_wants"] = mapped
            elif current in ("Need", "Want", "Unknown"):
                df.at[idx, "needs_wants"] = current
            else:
                # An expense we could not place. Say so, rather than defaulting
                # it into the discretionary bucket.
                df.at[idx, "needs_wants"] = "Unknown"

        return df

    def _assign_tags(
        self,
        description: str,
        category: str,
        subcategory: str,
        txn_type: str,
        merchant_entity: str,
    ) -> List[str]:
        """Generate additive, multi-label system tags for a transaction."""
        tags: List[str] = []
        desc_upper = description.upper()

        # Payment rails
        if "UPI" in desc_upper or "TRANSFER-UPI" in desc_upper:
            tags.append("UPI")
            if any(h in desc_upper for h in ["@BHARATPE", "@RAZORPAY", "@HDFCBANKSMARTPAY", "@PAYTMQR", "@BILLDESK"]) or "P2M" in desc_upper:
                tags.append("UPI/P2M")
            elif any(h in desc_upper for h in ["@YBL", "@PAYTM", "@OKSBI", "@OKHDFCBANK", "@OKAXIS", "@OKICICI"]) or "P2P" in desc_upper:
                tags.append("UPI/P2P")

        if "NEFT" in desc_upper:
            tags.append("NEFT")
        if "IMPS" in desc_upper or "MMT/" in desc_upper:
            tags.append("IMPS")
        if "RTGS" in desc_upper:
            tags.append("RTGS")
        if "NACH" in desc_upper:
            tags.append("NACH")
        if "ECS" in desc_upper:
            tags.append("ECS")
            tags.append("NACH")

        # Instruments & Operations
        if any(k in desc_upper for k in ["CLG", "CHEQUE", "CHQ", "BY CLG", "TO CLG"]):
            tags.append("Cheque")
        if "ATM" in desc_upper or "ATW" in desc_upper or "NFS/" in desc_upper:
            tags.append("ATM")
            tags.append("Cash")
        if "CASH DEP" in desc_upper or "BY CASH" in desc_upper or "CDM" in desc_upper:
            tags.append("Cash")

        # Financial Purpose
        if "LOAN" in desc_upper or subcategory in ["Loan / EMI", "Home Loan EMI", "Personal Loan"]:
            tags.append("Loan")
            if txn_type.lower() == "debit" or "EMI" in desc_upper or "NACH" in desc_upper or "ECS" in desc_upper:
                tags.append("EMI")
        if "SALARY" in desc_upper or subcategory == "Salary":
            tags.append("Salary")
        if "INSURANCE" in desc_upper or "LIC" in desc_upper or subcategory == "Insurance":
            tags.append("Insurance")
        if any(k in desc_upper for k in ["TAX", "INCOME TAX", "GST", "CBIC", "INTERNET TAX PAYMENT"]):
            tags.append("Tax")
        if any(k in desc_upper for k in ["RETURN", "BOUNCE", "REVERSAL", "RVSL", "INSUFFICIENT FUNDS"]):
            tags.append("Return")
        if any(k in desc_upper for k in ["CHARGE", "FEE", "MIN BAL", "PENAL", "CHG"]):
            tags.append("Bank Charges")

        return list(dict.fromkeys(tags))

    # --------------------------------------------------------
    # Tier 1: Bank-specific deterministic rules
    # --------------------------------------------------------
    def _tier1_bank_rules(
        self,
        description: str,
        debit: float,
        credit: float,
        parsed: Dict[str, str],
        rail_patterns: Dict[str, Any],
        bank_keywords: Dict[str, List[str]],
        bank_name: str,
    ) -> Dict[str, Any]:
        """Apply bank-specific rail patterns and keywords."""
        result = _empty_classification()
        desc_upper = description.upper()

        # --- ICICI-specific: EBA/MFP = Mutual Fund / SIP ---
        if bank_name == "ICICI":
            if desc_upper.startswith("EBA/MFP-"):
                result.update({
                    "category": "Investment",
                    "subcategory": "Mutual Funds / SIP",
                    "merchant_entity": "ICICI Direct",
                    "needs_wants": "N/A",
                    "confidence": 0.98,
                    "classification_method": "bank_rule",
                })
                return result

            if desc_upper.startswith("EBA/EQ TRADE"):
                result.update({
                    "category": "Investment",
                    "subcategory": "Equity Trading",
                    "merchant_entity": "ICICI Direct",
                    "needs_wants": "N/A",
                    "confidence": 0.98,
                    "classification_method": "bank_rule",
                })
                return result

        # --- Axis-specific: P2M flag ---
        if bank_name == "Axis" and parsed.get("is_p2m"):
            # P2M = confirmed merchant payment, try keyword on payee
            payee = parsed.get("payee", "")
            if payee:
                keyword_result = self._tier2_keyword_match(payee, debit, credit)
                if keyword_result["confidence"] > 0:
                    keyword_result["confidence"] = min(keyword_result["confidence"] + 0.05, 1.0)
                    keyword_result["classification_method"] = "bank_rule"
                    return keyword_result

        # --- ACH transactions (all banks) ---
        # ACH credits = salary/income, ACH debits = recurring payments (EMI, insurance, mandates)
        if parsed.get("rail") == "ACH":
            payee = parsed.get("payee", "")
            if credit > 0:
                # ACH credit = salary / employer deposit
                result.update({
                    "category": "Income",
                    "subcategory": "Salary",
                    "merchant_entity": payee.strip() if payee else "",
                    "needs_wants": "N/A",
                    "confidence": 0.95,
                    "classification_method": "bank_rule",
                })
                return result
            elif debit > 0 and payee:
                # ACH debit = recurring mandate (EMI, insurance, etc.)
                keyword_result = self._tier2_keyword_match(payee, debit, credit)
                if keyword_result["confidence"] > 0:
                    keyword_result["confidence"] = min(keyword_result["confidence"] + 0.05, 1.0)
                    keyword_result["classification_method"] = "bank_rule"
                    keyword_result["merchant_entity"] = payee.strip()
                    return keyword_result
                # Fall through if no keyword match on payee

        # --- ATM patterns (all banks) ---
        atm_pattern = rail_patterns.get("atm") or rail_patterns.get("cam_cash")
        if atm_pattern and atm_pattern.search(description):
            result.update({
                "category": "Banking",
                "subcategory": "ATM Withdrawal",
                "needs_wants": "N/A",
                "confidence": 0.99,
                "classification_method": "bank_rule",
            })
            return result

        # Also check for generic ATM patterns not in bank-specific regex
        if parsed.get("rail") == "ATM":
            result.update({
                "category": "Banking",
                "subcategory": "ATM Withdrawal",
                "needs_wants": "N/A",
                "confidence": 0.97,
                "classification_method": "bank_rule",
            })
            return result

        # --- FASTag (all banks with fastag pattern) ---
        fastag_pattern = rail_patterns.get("fastag")
        if fastag_pattern and fastag_pattern.search(description):
            result.update({
                "category": "Expense",
                "subcategory": "Metro / Bus / Toll / Parking",
                "merchant_entity": "FASTag",
                "needs_wants": "Need",
                "confidence": 0.98,
                "classification_method": "bank_rule",
            })
            return result

        # --- Interest credit ---
        interest_pattern = rail_patterns.get("interest")
        if interest_pattern and interest_pattern.search(description):
            result.update({
                "category": "Income",
                "subcategory": "Interest",
                "needs_wants": "N/A",
                "confidence": 0.99,
                "classification_method": "bank_rule",
            })
            return result

        # --- Bank charges ---
        charge_pattern = rail_patterns.get("bank_charge")
        if charge_pattern and charge_pattern.search(description):
            result.update({
                "category": "Banking",
                "subcategory": "Bank Charges",
                "needs_wants": "N/A",
                "confidence": 0.97,
                "classification_method": "bank_rule",
            })
            return result

        # --- Government schemes ---
        govt_pattern = rail_patterns.get("govt_scheme")
        if govt_pattern and govt_pattern.search(description):
            result.update({
                "category": "Expense",
                "subcategory": "Insurance",
                "needs_wants": "Need",
                "confidence": 0.97,
                "classification_method": "bank_rule",
            })
            return result

        # --- NEFT return/reversal ---
        neft_return = rail_patterns.get("neft_return")
        if neft_return and neft_return.search(description):
            result.update({
                "category": "Income",
                "subcategory": "Refund / Reversal",
                "needs_wants": "N/A",
                "confidence": 0.97,
                "classification_method": "bank_rule",
            })
            return result

        # --- Forex ---
        forex_pattern = rail_patterns.get("forex")
        if forex_pattern and forex_pattern.search(description):
            result.update({
                "category": "Income" if credit > 0 else "Expense",
                "subcategory": "Forex",
                "needs_wants": "N/A",
                "confidence": 0.95,
                "classification_method": "bank_rule",
            })
            return result

        # --- BIL/ONL — extract payee and classify by keyword ---
        bil_onl_pattern = rail_patterns.get("bil_onl")
        if bil_onl_pattern and bil_onl_pattern.search(description):
            # Try to classify based on payee/remarks in the description
            keyword_result = self._tier2_keyword_match(description, debit, credit)
            if keyword_result["confidence"] > 0:
                keyword_result["confidence"] = min(keyword_result["confidence"] + 0.05, 1.0)
                keyword_result["classification_method"] = "bank_rule"
                return keyword_result
            # If no keyword match, fall through to other tiers

        # --- CLG / Cheque (ICICI) ---
        clg_pattern = rail_patterns.get("clg")
        if clg_pattern and clg_pattern.search(description):
            # A cheque is a payment *instrument*, not a spending category.
            # Returning "Cheque" here hid what the money was actually for --
            # Rs 3,30,750 to a tour operator was filed under Cheque while the
            # Travel subcategory stayed empty. Classify by payee when we can,
            # and keep the instrument in the tags (_assign_tags adds "Cheque").
            payee_result = self._tier2_keyword_match(description, debit, credit)
            if payee_result["confidence"] > 0:
                payee_result["classification_method"] = "bank_rule"
                payee_result["matched_rule"] = "clg_cheque_payee"
                if parsed.get("payee"):
                    payee_result["merchant_entity"] = parsed["payee"].strip()
                return payee_result

            result.update({
                "category": "Expense" if debit > 0 else "Income",
                "subcategory": "Cheque",
                "needs_wants": "Unknown" if debit > 0 else "Not Applicable",
                "confidence": 0.95,
                "classification_method": "bank_rule",
                "matched_rule": "clg_cheque_rail",
            })
            # Try to extract payee for entity
            if parsed.get("payee"):
                result["merchant_entity"] = parsed["payee"].strip()
            return result

        # --- Bank-specific keywords (HL EMI, insurance, CC, etc.) ---
        # Uses the same boundary-anchored matcher as tier 2. A bare substring
        # test here let a counterparty's bank name imply a loan, so an ordinary
        # UPI payment narrated ".../MOHAMMED /HDFC BANK/taxi" was classified as
        # a home loan EMI at 0.96 confidence.
        for keyword_type, keywords in bank_keywords.items():
            for kw in keywords:
                if keyword_matches(kw, description):
                    if keyword_type in ("hl_emi", "pl"):
                        result.update({
                            "category": "Expense",
                            "subcategory": "Loan / EMI",
                            "needs_wants": "Need",
                            "confidence": 0.96,
                            "classification_method": "bank_rule",
                        })
                    elif keyword_type == "insurance":
                        result.update({
                            "category": "Expense",
                            "subcategory": "Insurance",
                            "needs_wants": "Need",
                            "confidence": 0.96,
                            "classification_method": "bank_rule",
                        })
                    elif keyword_type == "cc_payment":
                        result.update({
                            "category": "Expense",
                            "subcategory": "Loan / EMI",
                            "merchant_entity": kw,
                            "needs_wants": "Need",
                            "confidence": 0.96,
                            "classification_method": "bank_rule",
                        })
                    elif keyword_type == "investment":
                        result.update({
                            "category": "Investment",
                            "subcategory": "Equity Trading",
                            "merchant_entity": kw,
                            "needs_wants": "N/A",
                            "confidence": 0.96,
                            "classification_method": "bank_rule",
                        })
                    if result["confidence"] > 0:
                        return result

        return result

    # --------------------------------------------------------
    # Tier 2: Shared keyword matching
    # --------------------------------------------------------
    # Dictionary scan order is only used to break ties between equally-specific
    # keywords. Specificity (longest match) decides first.
    _KEYWORD_SOURCES = [
        ("Investment", INVESTMENT_KEYWORDS, "N/A"),
        ("Income", INCOME_KEYWORDS, "N/A"),
        ("Banking", BANKING_KEYWORDS, "N/A"),
        ("Expense", NEEDS_KEYWORDS, "Need"),
        ("Expense", WANTS_KEYWORDS, "Want"),
    ]

    @staticmethod
    def _direction_allows(category: str, debit: float, credit: float) -> bool:
        """
        Reject category/direction combinations that cannot be true.

        Tier 2 accepted debit and credit but never read them, so a credit could
        be booked as an Expense. That is how 13 monthly ACH salary credits
        (Rs 6,55,838) were classified "Expense / Society / Property Tax" while
        the income engine simultaneously counted them as income.
        """
        is_credit = credit and credit > 0
        is_debit = debit and debit > 0
        if is_credit and not is_debit and category == "Expense":
            return False
        if is_debit and not is_credit and category == "Income":
            return False
        return True

    # Remark prefix -> an existing taxonomy subcategory. Only groups specific
    # enough to name a category are listed; anything vaguer resolves to the
    # generic merchant bucket with its needs/wants taken from classify_remark.
    _REMARK_SUBCATEGORY = [
        (("milk", "curd", "dahi", "oil", "ghee", "butter", "bread", "wheat", "atta",
          "rice", "dal", "sugar", "salt", "banana", "fruit", "veg", "sabzi", "kirana",
          "grocer", "chees", "lassi", "paneer", "egg", "masala", "coconu", "olive",
          "1 kg", "2 kg", "dettol", "soap", "shampo", "towel", "detergen", "det pd",
          "hand w", "paste", "tissue", "harpic", "phenyl"), "Grocery / Supermarket"),
        (("medici", "medicin", "tablet", "eye dr", "eye do", "specs", "spectac",
          "arthre", "arthrel", "doctor", "clinic", "hospit", "pharma", "chemist",
          "nepa ey", "xray", "scan"), "Healthcare"),
        (("taxi", "auto", "rickshaw", "maruti", "parking", "toll"), "Taxi"),
        (("railwa", "train", "ticket", "bus", "payvia"), "Metro / Bus / Toll / Parking"),
        (("petrol", "diesel", "fuel"), "Fuel"),
        (("cable", "cabale", "electric", "water", "gas cyl"), "Electricity / Water / Gas"),
        (("wifi", "broadb", "recharg"), "Internet / Mobile / Broadband"),
        (("societ", "maint"), "Society / Property Tax"),
        (("rent",), "Rent"),
        (("fee", "tuition", "school", "colleg", "zerox", "xerox", "print", "photoco",
          "stationer", "book", "notebook"), "Education"),
        (("lunch", "dinner", "breakfa", "tea", "coffee", "snack", "sandwic", "bhel",
          "biryan", "pizza", "burger", "cake", "sweet", "laddu", "icecrea", "ice cr",
          "juice", "cold dr", "restau", "canteen", "cater", "hotel"), "Food Delivery"),
        (("shirt", "t shirt", "dress", "sadra", "tailor", "cloth", "jean", "saree",
          "kurta", "shoe", "chappal", "bag"), "Fashion"),
        (("salon", "parlour", "haircut"), "Beauty"),
        (("movie", "cinema", "game", "toy", "party", "picnic", "buke", "bouque",
          "flower", "gift", "lyric"), "Entertainment"),
    ]

    @classmethod
    def _subcategory_from_remark(cls, remark: str) -> Optional[str]:
        """Longest-prefix map from a UPI remark to a taxonomy subcategory."""
        r = (remark or "").strip().lower()
        if not r or r in REMARK_UNINFORMATIVE:
            return None
        best_len, best = 0, None
        for prefixes, subcat in cls._REMARK_SUBCATEGORY:
            for p in prefixes:
                if r.startswith(p) and len(p) > best_len:
                    best_len, best = len(p), subcat
        return best

    def _tier2_keyword_match(
        self, description: str, debit: float, credit: float
    ) -> Dict[str, Any]:
        """Match against the shared master keyword dictionaries.

        Collects every candidate across all dictionaries and keeps the most
        specific one, instead of returning the first hit in dict-insertion
        order. That ordering meant "LIC" beat "Loan / EMI" on an
        "EMI PAYMENT LIC HFL" narration, and "RETURN" in the Income dictionary
        turned "NACH RETURN CHARGES" into income.
        """
        result = _empty_classification()

        candidates = []
        for category, kw_dict, needs_wants in self._KEYWORD_SOURCES:
            if not self._direction_allows(category, debit, credit):
                continue
            for subcategory, keywords in kw_dict.items():
                matched = find_longest_match(keywords, description)
                if matched:
                    candidates.append((len(matched), category, subcategory, needs_wants, matched))

        if not candidates:
            return result

        # Most specific keyword wins; ties fall back to dictionary order.
        candidates.sort(key=lambda c: -c[0])
        _, category, subcategory, needs_wants, matched_kw = candidates[0]

        result.update({
            "category": category,
            "subcategory": subcategory,
            "merchant_entity": "" if category == "Banking" else (find_merchant_entity(description) or ""),
            "needs_wants": needs_wants,
            "confidence": 0.90,
            "classification_method": "keyword",
            "matched_keyword": matched_kw,
        })
        return result

    # --------------------------------------------------------
    # Tier 3: Fuzzy merchant matching
    # --------------------------------------------------------
    def _tier3_fuzzy_match(
        self, description: str, debit: float, credit: float,
        threshold: int = 80,
    ) -> Dict[str, Any]:
        """Fuzzy match description against merchant corpus."""
        result = _empty_classification()

        if not self._fuzzy_corpus:
            return result

        # Use token_set_ratio for better partial matching.
        # processor=default_process is essential: token_set_ratio splits on
        # whitespace only, so a slash-delimited narration such as
        # "UPI/402/ZOMATO LTD/zomato@ybl" collapses into a single token and
        # never matches a short merchant key. Without it this tier matched
        # nothing at all on real Indian narrations.
        match = process.extractOne(
            description.upper(),
            self._fuzzy_corpus,
            scorer=fuzz.token_set_ratio,
            score_cutoff=threshold,
            processor=rf_utils.default_process,
        )

        if match is None:
            return result

        matched_keyword, score, _ = match
        if matched_keyword.upper() == "MMT" and (description.upper().startswith("MMT/") or "MMT/IMPS" in description.upper()):
            return result

        # Fuzzy matching bypasses the exclusion and required-context rules that
        # tiers 1 and 2 apply, so a counterparty's bank name could still be
        # fuzzy-matched into a loan category here. Re-apply the same guard.
        if not keyword_matches(matched_keyword, description):
            return result

        # Direction must hold for a fuzzy hit too.
        provisional_cat, provisional_sub, _ = self._lookup_keyword_category(matched_keyword)
        if not self._direction_allows(provisional_cat, debit, credit):
            return result

        # A fuzzy hit whose keyword resolves to the ("Expense", "Other")
        # fallback has not actually identified anything -- the matched token is
        # in the merchant map but in no category dictionary. Claiming the row
        # here blocked the rail/remark rules that could classify it, and
        # produced a second undifferentiated bucket: 75 Axis rows sat in
        # "Expense / Other" at 0.85 confidence. Decline and let later tiers run.
        if provisional_cat == "Expense" and provisional_sub == "Other":
            return result


        merchant_entity = MERCHANT_ENTITY_MAP.get(matched_keyword, matched_keyword)

        # Determine category from which dictionary the keyword belongs to
        category, subcategory, needs_wants = self._lookup_keyword_category(matched_keyword)

        confidence = round(score / 100.0, 2)
        # Scale confidence to Tier 3 range (0.70 – 0.85)
        confidence = 0.70 + (confidence - threshold / 100.0) * 0.75
        confidence = round(min(max(confidence, 0.70), 0.85), 2)

        result.update({
            "category": category,
            "subcategory": subcategory,
            "merchant_entity": merchant_entity,
            "needs_wants": needs_wants,
            "confidence": confidence,
            "classification_method": "fuzzy",
        })

        return result

    def _lookup_keyword_category(self, keyword: str) -> Tuple[str, str, str]:
        """Look up which category dictionary a keyword belongs to."""
        kw_upper = keyword.upper()

        for subcat, kws in NEEDS_KEYWORDS.items():
            if any(k.upper() == kw_upper for k in kws):
                return ("Expense", subcat, "Need")

        for subcat, kws in WANTS_KEYWORDS.items():
            if any(k.upper() == kw_upper for k in kws):
                return ("Expense", subcat, "Want")

        for subcat, kws in INVESTMENT_KEYWORDS.items():
            if any(k.upper() == kw_upper for k in kws):
                return ("Investment", subcat, "N/A")

        for subcat, kws in INCOME_KEYWORDS.items():
            if any(k.upper() == kw_upper for k in kws):
                return ("Income", subcat, "N/A")

        for subcat, kws in BANKING_KEYWORDS.items():
            if any(k.upper() == kw_upper for k in kws):
                return ("Banking", subcat, "N/A")

        return ("Expense", "Other", "N/A")

    # --------------------------------------------------------
    # Tier 4: SLM batch classification
    # --------------------------------------------------------
    def _tier4_slm_batch(self, df: pd.DataFrame, indices: List[int]):
        """Run SLM on unresolved transactions using vectorized batch inference."""
        if not indices:
            return

        descriptions = [str(df.at[idx, "description"]) for idx in indices]
        batch_size = self.settings.get("model", {}).get("batch_size", 64)

        logger.info(f"Running vectorized SLM batch classification on {len(descriptions)} items (batch_size={batch_size})")
        results = self._slm.classify_batch(descriptions, batch_size=batch_size)

        for idx, (label, confidence) in zip(indices, results):
            description = str(df.at[idx, "description"])
            debit_val = df.at[idx, "debit"]
            credit_val = df.at[idx, "credit"]
            debit = float(debit_val) if (pd.notnull(debit_val) and debit_val is not None) else 0.0
            credit = float(credit_val) if (pd.notnull(credit_val) and credit_val is not None) else 0.0

            mapping = SLM_LABEL_MAP.get(label, {})
            if mapping and confidence >= self._slm.confidence_threshold:
                df.at[idx, "category"] = mapping.get("category", "Uncategorized")
                df.at[idx, "subcategory"] = mapping.get("subcategory", "Unknown")
                df.at[idx, "needs_wants"] = mapping.get("needs_wants", "N/A")
                df.at[idx, "merchant_entity"] = find_merchant_entity(description) or ""
                df.at[idx, "confidence"] = round(confidence, 2)
                df.at[idx, "classification_method"] = "slm"
            else:
                # SLM also couldn't classify — mark as Transfer or Uncategorized
                if credit > 0:
                    df.at[idx, "category"] = "Income"
                    df.at[idx, "subcategory"] = "Other Income"
                elif debit > 0:
                    df.at[idx, "category"] = "Expense"
                    df.at[idx, "subcategory"] = "Other Expense"
                else:
                    df.at[idx, "category"] = "Uncategorized"
                    df.at[idx, "subcategory"] = "Unknown"
                df.at[idx, "needs_wants"] = "N/A"
                df.at[idx, "confidence"] = round(max(confidence, 0.3), 2)
                df.at[idx, "classification_method"] = "slm_low_confidence"

        # Tier 4.5: BharatGen Param-Finance Fallback for unresolved / low-confidence rows
        low_conf_indices = [
            idx for idx in indices
            if df.at[idx, "classification_method"] == "slm_low_confidence"
        ]
        if low_conf_indices:
            try:
                from src.model.param_adapter import ParamAdapter
                adapter = ParamAdapter.get_instance()
                param_batch = [
                    {
                        "index": idx,
                        "narration": str(df.at[idx, "description"]),
                        "debit": float(df.at[idx, "debit"]) if pd.notnull(df.at[idx, "debit"]) else 0.0,
                        "credit": float(df.at[idx, "credit"]) if pd.notnull(df.at[idx, "credit"]) else 0.0,
                    }
                    for idx in low_conf_indices
                ]
                enriched = adapter.classify_unresolved_batch(param_batch)
                for res in enriched:
                    idx = res["index"]
                    if res.get("category") and res.get("subcategory") not in ["Other Income", "Other Expense", "Unknown"]:
                        df.at[idx, "category"] = res["category"]
                        df.at[idx, "subcategory"] = res["subcategory"]
                        df.at[idx, "merchant_entity"] = res.get("counterparty") or df.at[idx, "merchant_entity"]
                        df.at[idx, "needs_wants"] = res.get("needs_wants") or "N/A"
                        df.at[idx, "confidence"] = res.get("confidence", 0.90)
                        df.at[idx, "classification_method"] = "param_finance"
            except Exception as e:
                logger.warning(f"Tier 4.5 Param-Finance fallback encountered non-fatal error: {e}")

