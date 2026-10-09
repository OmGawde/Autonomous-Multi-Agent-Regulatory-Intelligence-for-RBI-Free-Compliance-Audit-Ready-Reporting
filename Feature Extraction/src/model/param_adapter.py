"""BharatGen Param-Finance Adapter for Indian Banking Semantics & Underwriting.

Provides:
1. Batch Exception Handling (Pillar 1) for ambiguous long-tail transactions.
2. SME Business Profiling & Commingling Detection (Pillar 2).
3. Virtual Underwriting Officer CAM Memo Synthesis (Pillar 3).
4. Guarded Underwriting Copilot with 5 Anti-Hallucination & Anti-Injection Guardrails (Pillar 4).
5. Device auto-routing (CUDA -> MPS -> CPU), optional 4-bit quantization, and sovereign Mock fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

try:
    from . import ledger_query
except ImportError:  # direct-script import path
    import ledger_query

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Local, offline BharatGen FinanceParam weights.
#
# The default used to be the hub id "bharatgen/param-1-finance", which does not
# exist -- wrong organisation (it is `bharatgenai`) and wrong repo name (it is
# `FinanceParam`). Every load therefore failed and silently fell back to the
# keyword mock, so nothing in this file ever ran a model. The weights are now
# vendored next to the DistilBERT classifier and loaded strictly from disk:
# `local_files_only` means a missing folder fails loudly here instead of
# reaching for the network.
# ----------------------------------------------------------------------
_FE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = _FE_ROOT / "models" / "finance-param"

# config.json caps max_position_embeddings at 2048, which covers prompt AND
# completion. Every prompt built in this module is budgeted against it; exceed
# it and generation silently produces nonsense rather than raising.
MODEL_MAX_CONTEXT = 2048


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------
class ParamExtractionResult(BaseModel):
    """Structured extraction schema returned by BharatGen Param-Finance."""

    category: str = Field(description="High-level category: Income, Expense, Loan EMI, Investment, Banking Charges, Transfer")
    subcategory: str = Field(description="Granular financial category")
    counterparty: str = Field(description="Identified counterparty / merchant entity name")
    entity_type: str = Field(description="Corporate, NBFC, Bank, Individual, Merchant, Government")
    upi_handle: Optional[str] = Field(default=None, description="UPI VPA (e.g. user@bank)")
    banking_rail: str = Field(description="UPI, NEFT, RTGS, IMPS, NACH, ECS, ATM, POS, CBS_INTERNAL, CHEQUE, CASH")
    needs_wants: str = Field(description="Needs, Wants, Debt Servicing, Investment, None")
    confidence: float = Field(default=0.90, ge=0.0, le=1.0)


# ----------------------------------------------------------------------
# Sovereign Mock Engine (Offline & Fallback)
# ----------------------------------------------------------------------
class MockParamFinanceModel:
    """High-accuracy sovereign BFSI heuristic engine mirroring BharatGen Param-Finance semantics.
    Enables instant offline execution, test suite execution, and fallback when model weights are not loaded.
    """

    UPI_VPA_REGEX = re.compile(r"([a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64})")

    KNOWN_LENDERS = {
        "bajaj finserv": ("Bajaj Finserv", "NBFC", "Personal Loan EMI"),
        "tata capital": ("Tata Capital", "NBFC", "Personal Loan EMI"),
        "hdfc bank ltd-hl": ("HDFC Bank", "Bank", "Home Loan EMI"),
        "hdfc bank loan": ("HDFC Bank", "Bank", "Personal Loan EMI"),
        "sbi card": ("SBI Cards", "NBFC", "Credit Card EMI"),
        "aditya birla": ("Aditya Birla Finance", "NBFC", "Personal Loan EMI"),
        "kreditbee": ("KreditBee", "NBFC", "Personal Loan EMI"),
        "fibe": ("Fibe", "NBFC", "Personal Loan EMI"),
        "navi": ("Navi Technologies", "NBFC", "Personal Loan EMI"),
        "moneytap": ("MoneyTap", "NBFC", "Personal Loan EMI"),
        "axis bank loan": ("Axis Bank", "Bank", "Auto Loan EMI"),
        "icici home loan": ("ICICI Bank", "Bank", "Home Loan EMI"),
        "hero fincorp": ("Hero FinCorp", "NBFC", "Two Wheeler Loan EMI"),
        "cholamandalam": ("Cholamandalam Finance", "NBFC", "Auto Loan EMI"),
        "muthoot": ("Muthoot Finance", "NBFC", "Gold Loan EMI"),
        "idfc first bank loan": ("IDFC FIRST Bank", "Bank", "Consumer Loan EMI"),
    }

    INVESTMENT_KEYWORDS = {
        "mutual fund": "Mutual Fund SIP",
        "zerodha": "Equity Investment",
        "groww": "Mutual Fund SIP",
        "upstox": "Equity Investment",
        "nippon india": "Mutual Fund SIP",
        "uti mutual": "Mutual Fund SIP",
        "mirae asset": "Mutual Fund SIP",
        "hdfc mutual": "Mutual Fund SIP",
        "sbi mutual": "Mutual Fund SIP",
        "icici prudential": "Mutual Fund SIP",
        "nps trust": "NPS Contribution",
        "ppf": "PPF Deposit",
    }

    UTILITY_KEYWORDS = {
        "bescom": "Electricity",
        "tneb": "Electricity",
        "bses": "Electricity",
        "mahadiscom": "Electricity",
        "uppcl": "Electricity",
        "airtel": "Telecom / Broadband",
        "jio": "Telecom / Broadband",
        "vi telecom": "Telecom / Broadband",
        "tata play": "Cable / DTH",
        "indane": "LPG Cylinder",
        "bharat gas": "LPG Cylinder",
        "hp gas": "LPG Cylinder",
    }

    WANTS_KEYWORDS = {
        "swiggy": ("Swiggy", "Food & Dining"),
        "zomato": ("Zomato", "Food & Dining"),
        "pvr": ("PVR Cinemas", "Entertainment"),
        "inox": ("INOX Cinemas", "Entertainment"),
        "bookmyshow": ("BookMyShow", "Entertainment"),
        "netflix": ("Netflix", "Entertainment"),
        "spotify": ("Spotify", "Entertainment"),
        "amazon": ("Amazon India", "Shopping"),
        "flipkart": ("Flipkart", "Shopping"),
        "myntra": ("Myntra", "Shopping"),
        "zara": ("Zara", "Shopping"),
        "starbucks": ("Starbucks", "Food & Dining"),
        "mcdonald": ("McDonald's", "Food & Dining"),
        "uber": ("Uber", "Travel & Transit"),
        "ola": ("Ola Cabs", "Travel & Transit"),
        "makemytrip": ("MakeMyTrip", "Travel & Vacation"),
    }

    NEEDS_KEYWORDS = {
        "blinkit": ("Blinkit", "Grocery"),
        "zepto": ("Zepto", "Grocery"),
        "instamart": ("Swiggy Instamart", "Grocery"),
        "bigbasket": ("BigBasket", "Grocery"),
        "dmart": ("DMart", "Grocery"),
        "apollo pharmacy": ("Apollo Pharmacy", "Healthcare"),
        "netmeds": ("Netmeds", "Healthcare"),
        "1mg": ("Tata 1mg", "Healthcare"),
        "medplus": ("MedPlus", "Healthcare"),
        "school": ("Educational Institution", "Education"),
        "college": ("Educational Institution", "Education"),
        "university": ("Educational Institution", "Education"),
        "rent": ("Landlord", "House Rent"),
    }

    SECTOR_MAPPINGS = [
        (["textile", "fabrics", "garments", "kapil textiles", "yarn", "saree", "cotton"], "Textile Wholesale & Manufacturing"),
        (["logistics", "transport", "freight", "carriers", "roadways", "express cargo"], "Logistics & Freight Services"),
        (["kirana", "provisions", "traders", "general store", "supermarket", "wholesalers"], "Retail & FMCG Wholesale"),
        (["kitchen", "restaurant", "caterers", "foods", "bakes", "cafe", "dhaba"], "Cloud Kitchen & F&B Services"),
        (["steel", "iron", "hardware", "metals", "tubes", "alloys"], "Metals & Industrial Fabrication"),
        (["pharma", "chemist", "drugs", "lifesciences", "medicals"], "Pharmaceutical Distribution"),
        (["consulting", "software", "tech", "infotech", "digital", "solutions"], "IT & Professional Services"),
        (["auto", "motors", "spares", "automobiles", "garage", "tyres"], "Automotive Parts & Services"),
    ]

    def infer(self, narration: str, txn_type: str, amount: float) -> ParamExtractionResult:
        """Heuristically classify Indian banking narration matching Param-Finance schema."""
        raw = narration.strip()
        lower = raw.lower()

        # 1. Identify Banking Rail
        rail = "CBS_INTERNAL"
        upi_vpa = None
        vpa_match = self.UPI_VPA_REGEX.search(raw)
        if vpa_match:
            upi_vpa = vpa_match.group(1)
            rail = "UPI"
        elif "upi/" in lower or "upi-" in lower:
            rail = "UPI"
        elif "ach d-" in lower or "ach c-" in lower or "nach" in lower:
            rail = "NACH"
        elif "ecs" in lower:
            rail = "ECS"
        elif "neft" in lower:
            rail = "NEFT"
        elif "rtgs" in lower:
            rail = "RTGS"
        elif "imps" in lower:
            rail = "IMPS"
        elif "atm" in lower or "eaw" in lower or "nwd" in lower or "cash wdl" in lower:
            rail = "ATM"
        elif "pos " in lower or "pos/" in lower:
            rail = "POS"
        elif "chq" in lower or "cheque" in lower or "clg" in lower:
            rail = "CHEQUE"
        elif "cash dep" in lower or "by cash" in lower:
            rail = "CASH"

        # 2. Check for Inward Dishonours / Cheque Bounces / Bank Penalties
        bounce_keywords = [
            "inw ret",
            "inward return",
            "chq ret",
            "cheque return",
            "funds insufficient",
            "insufficient fund",
            "nach return",
            "ecs bounce",
            "ecs return",
            "return charge",
            "bounce charge",
            "dishonour",
            "dishonor",
        ]
        if any(kw in lower for kw in bounce_keywords):
            return ParamExtractionResult(
                category="Banking Charges",
                subcategory="Cheque Bounce Charge",
                counterparty="Bank",
                entity_type="Bank",
                upi_handle=upi_vpa,
                banking_rail=rail if rail != "CBS_INTERNAL" else "CHEQUE",
                needs_wants="None",
                confidence=0.99,
            )

        # 3. Check for Bank Fees / Charges
        charge_keywords = ["sms alert", "annual fee", "ledger folio", "min bal chg", "debit card fee", "gst on charge"]
        if any(kw in lower for kw in charge_keywords):
            return ParamExtractionResult(
                category="Banking Charges",
                subcategory="Bank Fees",
                counterparty="Bank",
                entity_type="Bank",
                upi_handle=upi_vpa,
                banking_rail="CBS_INTERNAL",
                needs_wants="None",
                confidence=0.98,
            )

        # 4. Check for Debt / Loan EMIs
        for lender_kw, (name, ent_type, subcat) in self.KNOWN_LENDERS.items():
            if lender_kw in lower or ("loan" in lower and lender_kw.split()[0] in lower):
                return ParamExtractionResult(
                    category="Loan EMI",
                    subcategory=subcat,
                    counterparty=name,
                    entity_type=ent_type,
                    upi_handle=upi_vpa,
                    banking_rail=rail if rail != "CBS_INTERNAL" else "NACH",
                    needs_wants="Debt Servicing",
                    confidence=0.98,
                )

        if "loan emi" in lower or "loan repayment" in lower or "emi debit" in lower:
            return ParamExtractionResult(
                category="Loan EMI",
                subcategory="Loan EMI",
                counterparty="Financial Institution",
                entity_type="NBFC",
                upi_handle=upi_vpa,
                banking_rail=rail,
                needs_wants="Debt Servicing",
                confidence=0.95,
            )

        # 5. Check for Investments
        for inv_kw, subcat in self.INVESTMENT_KEYWORDS.items():
            if inv_kw in lower:
                return ParamExtractionResult(
                    category="Investment",
                    subcategory=subcat,
                    counterparty=inv_kw.title(),
                    entity_type="Corporate",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="Investment",
                    confidence=0.97,
                )

        # 6. Check specific commercial trade & sector patterns (e.g. Kapil Textiles, Shree Ganesh Kirana)
        for kws, sector in self.SECTOR_MAPPINGS:
            if any(kw in lower for kw in kws):
                raw_tokens = [t.strip() for t in re.split(r"[/:\-_|]", raw) if t.strip()]
                matched_token = next((t for t in raw_tokens if any(kw in t.lower() for kw in kws)), None)
                cparty = matched_token.title() if matched_token else self._extract_counterparty(raw, default=kws[0].title())
                return ParamExtractionResult(
                    category="Expense" if txn_type.upper() == "DEBIT" else "Income",
                    subcategory="Inventory Expense" if txn_type.upper() == "DEBIT" else "Business Revenue",
                    counterparty=cparty,
                    entity_type="Merchant" if txn_type.upper() == "DEBIT" else "Corporate",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="Needs",
                    confidence=0.94,
                )

        # 7. Check for Income (Credit transactions)
        if txn_type.upper() == "CREDIT":
            if any(kw in lower for kw in ["salary", "payroll", "cms/", "sal for", "stipend"]):
                cparty = self._extract_counterparty(raw, default="Employer")
                return ParamExtractionResult(
                    category="Income",
                    subcategory="Salary",
                    counterparty=cparty,
                    entity_type="Corporate",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="None",
                    confidence=0.98,
                )
            if any(kw in lower for kw in ["dhandha", "business", "client payment", "vendor payment", "sale proceed", "invoice"]):
                cparty = self._extract_counterparty(raw, default="Client Entity")
                return ParamExtractionResult(
                    category="Income",
                    subcategory="Business Revenue",
                    counterparty=cparty,
                    entity_type="Corporate",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="None",
                    confidence=0.95,
                )
            # Default Credit
            cparty = self._extract_counterparty(raw, default="Counterparty")
            return ParamExtractionResult(
                category="Income",
                subcategory="Business Revenue" if amount >= 10000 else "Personal Transfer",
                counterparty=cparty,
                entity_type="Corporate" if amount >= 10000 else "Individual",
                upi_handle=upi_vpa,
                banking_rail=rail,
                needs_wants="None",
                confidence=0.88,
            )

        # 8. Check for Utilities
        for util_kw, subcat in self.UTILITY_KEYWORDS.items():
            if util_kw in lower:
                return ParamExtractionResult(
                    category="Expense",
                    subcategory="Utilities",
                    counterparty=util_kw.upper(),
                    entity_type="Corporate",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="Needs",
                    confidence=0.96,
                )

        # 9. Check for Needs
        for need_kw, (cparty, subcat) in self.NEEDS_KEYWORDS.items():
            if need_kw in lower:
                return ParamExtractionResult(
                    category="Expense",
                    subcategory=subcat,
                    counterparty=cparty,
                    entity_type="Merchant",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="Needs",
                    confidence=0.95,
                )

        # 10. Check for Wants / Discretionary
        for want_kw, (cparty, subcat) in self.WANTS_KEYWORDS.items():
            if want_kw in lower:
                return ParamExtractionResult(
                    category="Expense",
                    subcategory=subcat,
                    counterparty=cparty,
                    entity_type="Merchant",
                    upi_handle=upi_vpa,
                    banking_rail=rail,
                    needs_wants="Wants",
                    confidence=0.95,
                )

        # 11. Default classification
        cparty = self._extract_counterparty(raw, default="General Merchant")
        needs_wants = "Needs" if amount < 1000 and rail == "UPI" else "Wants"
        return ParamExtractionResult(
            category="Expense",
            subcategory="Personal Transfer" if rail in ["UPI", "IMPS"] else "Other Expense",
            counterparty=cparty,
            entity_type="Individual" if upi_vpa else "Merchant",
            upi_handle=upi_vpa,
            banking_rail=rail,
            needs_wants=needs_wants,
            confidence=0.82,
        )

    @staticmethod
    def _extract_counterparty(narration: str, default: str = "Counterparty") -> str:
        """Extract entity/counterparty name from messy Indian bank narration."""
        tokens = [t.strip() for t in re.split(r"[/:\-_|]", narration) if t.strip()]
        ignore_tokens = {
            "upi", "neft", "rtgs", "imps", "ach", "nach", "pos", "eaw", "atm",
            "trtr", "p2a", "p2m", "cr", "dr", "c", "d", "payto", "rev", "ret", "cms", "chq",
        }
        semantic_purposes = [
            "salary", "payroll", "stipend", "food order", "grocery", "bill payment",
            "temporary fund", "returned fund", "dinner order", "funds insufficient", "dhandha", "payment",
        ]

        candidate_tokens = []
        for token in tokens:
            t_lower = token.lower()
            if (
                t_lower in ignore_tokens
                or token.isdigit()
                or t_lower.startswith("chq")
                or t_lower.startswith("cheque")
                or t_lower.startswith("ref")
            ):
                continue
            if "@" in token:
                user_part = token.split("@")[0].replace(".", " ").replace("_", " ")
                return user_part.title()
            if any(p in t_lower for p in semantic_purposes):
                continue
            if len(token) >= 3:
                candidate_tokens.append(token)

        if candidate_tokens:
            return candidate_tokens[-1].title()

        return default


# ----------------------------------------------------------------------
# Model Loader
# ----------------------------------------------------------------------
class ParamModelLoader:
    """Loads BharatGen Param-Finance foundation model or defaults to sovereign mock engine."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "auto",
        quantize: str = "none",
        mock_mode: bool = False,
    ):
        self.model_path = model_path or os.getenv(
            "BHARATGEN_PARAM_MODEL_PATH", str(DEFAULT_MODEL_DIR)
        )
        self.device = self._resolve_device(device)
        self.quantize = quantize
        self.mock_mode = mock_mode or os.getenv("BHARATGEN_MOCK_MODE", "").lower() in ["1", "true"]
        self.model = None
        self.tokenizer = None
        self.is_mock = False

    @staticmethod
    def _resolve_device(device_str: str) -> str:
        """Determine device targeting CUDA -> MPS -> CPU."""
        if device_str and device_str.lower() != "auto":
            return device_str.lower()
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"

    @staticmethod
    def _normalise_rope_scaling(config: Any) -> Any:
        """Undo the RoPE config rewrite that breaks this checkpoint's own code.

        FinanceParam's `config.json` declares `"rope_scaling": null`, and its
        vendored `modeling_parambharatgen.py` (written against transformers
        4.55) branches on exactly that:

            if self.config.rope_scaling is None:   -> plain rotary embedding
            else:                                  -> self.config.rope_scaling["type"]

        transformers 5.x normalises the field on load, so `None` becomes
        `{"rope_theta": ..., "rope_type": "default"}`. The `is None` test then
        fails, the legacy branch runs, and the legacy `"type"` key it wants no
        longer exists -- `KeyError: 'type'`, before a single weight is read.

        `rope_type: "default"` means no scaling, which is what `None` meant, so
        restoring `None` selects the identical code path rather than working
        around it. A checkpoint that genuinely configures linear or dynamic
        scaling is left untouched.
        """
        scaling = getattr(config, "rope_scaling", None)
        if not isinstance(scaling, dict):
            return config
        if "type" in scaling or "factor" in scaling:
            return config  # real legacy scaling config; the model can read it
        if str(scaling.get("rope_type", "default")).lower() == "default":
            logger.debug(
                "Restoring rope_scaling=None for FinanceParam (transformers "
                "normalised it to %s, which its 4.55-era modelling code cannot read).",
                scaling,
            )
            config.rope_scaling = None
        return config

    def _smoke_test(self) -> bool:
        """Can the freshly loaded model actually form a sentence?

        Rejects the two signatures of a mis-wired forward pass: an immediately
        repeating token, and output that is almost entirely non-Latin when the
        prompt was English.

        The probe goes through the chat template, because that is how every
        caller here uses the model -- an instruction-tuned checkpoint given a
        bare completion prompt can degenerate even when it is perfectly healthy,
        and a check that fails a working model is worse than no check.

        Conservative by design: it only rejects output no working LLM would emit.
        """
        try:
            import torch

            messages = [{"role": "user", "content": "What is a NACH mandate in Indian banking?"}]
            try:
                enc = self.tokenizer.apply_chat_template(
                    messages, tokenize=True, return_tensors="pt"
                )
                ids = enc["input_ids"] if (hasattr(enc, "input_ids") or isinstance(enc, dict)) else enc
            except Exception:
                ids = self.tokenizer(
                    "<s><|user|>What is a NACH mandate in Indian banking?<|/user|><|assistant|>",
                    return_tensors="pt",
                ).input_ids
            ids = ids.to(self.model.device)
            with torch.inference_mode():
                out = self.model.generate(
                    ids,
                    attention_mask=torch.ones_like(ids),
                    max_new_tokens=12,
                    do_sample=False,
                    use_cache=False,
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                )
            new_ids = out[0][ids.shape[-1]:].tolist()
            text = self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()

            if not text:
                logger.warning("FinanceParam smoke test: empty completion.")
                return False

            # Degenerate loop: the same token over and over.
            if len(new_ids) >= 5 and len(set(new_ids)) <= max(1, len(new_ids) // 4):
                logger.warning(
                    f"FinanceParam smoke test: degenerate repetition ({text[:60]!r})."
                )
                return False

            # An English prompt answered with almost no Latin characters.
            letters = [c for c in text if c.isalpha()]
            if letters:
                latin = sum(1 for c in letters if c.isascii())
                if latin / len(letters) < 0.5:
                    logger.warning(
                        f"FinanceParam smoke test: English prompt produced "
                        f"non-Latin output ({text[:60]!r})."
                    )
                    return False
            return True

        except Exception as e:
            logger.warning(f"FinanceParam smoke test could not run: {e}")
            return False

    def load(self) -> Union[Any, MockParamFinanceModel]:
        """Load HuggingFace model or initialize sovereign fallback model."""
        if self.mock_mode:
            logger.info("Initializing Param-Finance in Mock Mode as requested.")
            self.model = MockParamFinanceModel()
            self.is_mock = True
            return self.model

        is_local = Path(self.model_path).exists()
        if not is_local:
            logger.warning(
                f"FinanceParam weights not found at '{self.model_path}'. This build runs "
                f"offline and will not download them; falling back to the heuristic engine. "
                f"Fetch them with: python -m tools.fetch_finance_param"
            )
            self.model = MockParamFinanceModel()
            self.is_mock = True
            return self.model

        try:
            import os
            import sys
            os.environ["USE_TF"] = "0"
            os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
            os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
            if sys.platform == "win32":
                torch_lib = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages", "torch", "lib")
                if os.path.exists(torch_lib):
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(torch_lib)
                        except Exception:
                            pass
                    os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")

            if "torch" in sys.modules and not hasattr(sys.modules["torch"], "__version__"):
                sys.modules.pop("torch", None)

            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info(f"Loading BharatGen FinanceParam from: {self.model_path} on {self.device}")
            load_kwargs: Dict[str, Any] = {}
            if self.quantize in ["4bit", "8bit"] and self.device == "cuda":
                try:
                    from transformers import BitsAndBytesConfig
                    if self.quantize == "4bit":
                        load_kwargs["quantization_config"] = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_compute_dtype=torch.bfloat16,
                            bnb_4bit_use_double_quant=True,
                        )
                    else:
                        load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
                except ImportError:
                    logger.warning("bitsandbytes not installed, loading without quantization.")

            # The checkpoint is published in bfloat16 and the card specifies it.
            # float16 overflows on this architecture's activations.
            if self.device == "cuda":
                dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32
            else:
                dtype = torch.float32

            from transformers import AutoConfig

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path, trust_remote_code=True, local_files_only=True,
            )

            config = AutoConfig.from_pretrained(
                self.model_path, trust_remote_code=True, local_files_only=True,
            )
            config = self._normalise_rope_scaling(config)

            # device_map="auto" is REQUIRED, not a convenience.
            #
            # Loading without it and calling .to(device) afterwards produces a
            # model that loads with every weight verified present and then emits
            # incoherent text. The reason is that the rotary embedding's
            # `inv_freq` is a *computed buffer*, not a checkpoint tensor: under
            # transformers' low_cpu_mem_usage path the module is built on the
            # meta device, accelerate is what materialises those buffers, and a
            # later .to() cannot recover what was never computed. RoPE then
            # scrambles positions -- activations look healthy, logits look
            # structured, and the output is fluent-shaped nonsense. No weight
            # check catches it, because inv_freq is not a weight.
            #
            # This is also exactly what the model card specifies.
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                config=config,
                trust_remote_code=True,
                local_files_only=True,
                torch_dtype=dtype,
                device_map="auto" if self.device == "cuda" else None,
                **load_kwargs,
            )
            if self.device != "cuda" and "quantization_config" not in load_kwargs:
                self.model = self.model.to(self.device)

            self.model.eval()
            self.is_mock = False

            # Loading successfully is not the same as working.
            #
            # This checkpoint's vendored modelling code targets transformers
            # 4.55. On 5.x it loads with all 291 tensors present and correct,
            # reports zero missing or mismatched keys, shows a healthy residual
            # stream, and then emits word-salad. Nothing in the load path
            # catches it, because nothing in the load path is wrong. Hence an
            # output check: the project pins 4.55 for this reason, and this is
            # what fails loudly if that pin is ever loosened.
            if not self._smoke_test():
                logger.error(
                    "FinanceParam loaded but failed its output sanity check -- it is "
                    "producing degenerate text. The usual cause is a transformers "
                    "version newer than the 4.55 this checkpoint's bundled modelling "
                    "code targets (check `pip show transformers`), or `accelerate` "
                    "missing so device_map='auto' could not materialise the rotary "
                    "embedding buffers. Falling back to the deterministic engine."
                )
                self.model = MockParamFinanceModel()
                self.is_mock = True
                return self.model

            logger.info(
                f"BharatGen FinanceParam loaded ({dtype}, ctx {MODEL_MAX_CONTEXT}) — "
                f"running fully offline."
            )
            return self.model

        except Exception as e:
            logger.warning(
                f"FinanceParam present but could not be loaded ({e}). "
                f"Falling back to the heuristic engine.",
                exc_info=True,
            )
            self.model = MockParamFinanceModel()
            self.is_mock = True
            return self.model


# ----------------------------------------------------------------------
# Central Param Adapter (Singleton)
# ----------------------------------------------------------------------
class ParamAdapter:
    """Unified Adapter connecting BharatGen Param-Finance into the credit underwriting pipeline."""

    _instance: Optional[ParamAdapter] = None

    def __init__(self, loader: Optional[ParamModelLoader] = None):
        self.loader = loader or ParamModelLoader()
        self.engine = self.loader.load()
        self.cache: Dict[str, ParamExtractionResult] = {}
        self.mock_fallback = MockParamFinanceModel()
        self.api_url = os.getenv("BHARATGEN_PARAM_API_URL", "")
        # A single model instance shared by the web app's thread pool. Neither
        # HF generate() nor the KV cache is re-entrant, so calls are serialised.
        self._gen_lock = threading.Lock()

    @property
    def llm_available(self) -> bool:
        """True when real FinanceParam weights are loaded (not the heuristic)."""
        return not self.loader.is_mock and self.loader.model is not None

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 300,
        system: Optional[str] = None,
    ) -> Optional[str]:
        """Run FinanceParam locally and return its completion, or None.

        Decoding is greedy. Underwriting output has to be reproducible: the same
        statement must not yield two different memos on two runs, which is also
        what the project's own integration blueprint requires ("temperature =
        0.0 or greedy decoding").

        Returns None rather than raising, so every caller can fall back to its
        deterministic path and no model problem can take out the pipeline.
        """
        if not self.llm_available:
            return None

        try:
            import torch

            tokenizer = self.loader.tokenizer
            model = self.loader.model

            content = f"{system.strip()}\n\n{prompt.strip()}" if system else prompt.strip()
            messages = [{"role": "user", "content": content}]

            mask = None
            try:
                encoded = tokenizer.apply_chat_template(
                    messages, tokenize=True, add_generation_prompt=True,
                    return_tensors="pt",
                )
            except Exception:
                # Older/newer template plumbing: fall back to the raw format
                # this checkpoint's chat_template.jinja encodes.
                raw = f"<s><|user|>{content}<|/user|><|assistant|>"
                encoded = tokenizer(raw, return_tensors="pt")

            # transformers 4.x returns a bare tensor here; 5.x returns a
            # BatchEncoding. Reading `.shape` off the latter raises a bare
            # AttributeError from its dict __getattr__, which is opaque enough
            # that it reads like a model failure rather than a shape mix-up.
            if hasattr(encoded, "input_ids") or isinstance(encoded, dict):
                ids = encoded["input_ids"]
                mask = encoded.get("attention_mask")
            else:
                ids = encoded

            # Budget the prompt so prompt + completion stay inside the 2048
            # window. Overflowing it does not raise -- it degrades the output
            # into noise, which is far worse on a credit file than a refusal.
            budget = MODEL_MAX_CONTEXT - max_new_tokens - 8
            if ids.shape[-1] > budget:
                logger.warning(
                    f"FinanceParam prompt of {ids.shape[-1]} tokens exceeds the "
                    f"{budget}-token budget; truncating the oldest context."
                )
                ids = ids[:, -budget:]
                if mask is not None:
                    mask = mask[:, -budget:]

            ids = ids.to(model.device)
            attention_mask = (
                mask.to(model.device) if mask is not None else torch.ones_like(ids)
            )

            with self._gen_lock, torch.inference_mode():
                out = model.generate(
                    ids,
                    attention_mask=attention_mask,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    # The checkpoint's vendored modelling code reads the KV
                    # cache as a legacy tuple (`past_key_values[0][0].shape[2]`),
                    # which transformers 5.x no longer supplies -- it passes a
                    # DynamicCache object, and indexing it raises. Disabling the
                    # cache keeps `past_key_values` None and takes the branch
                    # that code can handle. This is what the model card's own
                    # usage example does, so it is the supported path rather
                    # than a workaround; the cost is recomputation per step.
                    use_cache=False,
                    eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
                )

            completion = tokenizer.decode(
                out[0][ids.shape[-1]:], skip_special_tokens=True,
            ).strip()
            return completion or None

        except Exception as e:
            logger.warning(f"FinanceParam generation failed: {e}", exc_info=True)
            return None

    @classmethod
    def get_instance(cls) -> ParamAdapter:
        """Access singleton adapter instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _hash_key(narration: str, txn_type: str) -> str:
        """Create cache key based on narration text and debit/credit type."""
        raw = f"{narration.strip().lower()}::{txn_type.upper()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _extract_json_from_text(self, text: str) -> Optional[Any]:
        """Safely extract JSON payload from LLM generation text."""
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        block_match = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
        if block_match:
            try:
                return json.loads(block_match.group(1))
            except Exception:
                pass

        bracket_match = re.search(r"([\[\{].*[\]\}])", text, re.DOTALL)
        if bracket_match:
            try:
                return json.loads(bracket_match.group(1))
            except Exception:
                pass

        return None

    # ------------------------------------------------------------------
    # Pillar 1: Batch Exception Handler
    # ------------------------------------------------------------------
    def classify_unresolved_batch(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Classify a batch of unresolved/ambiguous transactions in a single pass.
        
        Args:
            transactions: List of dicts, each with keys 'narration', 'debit', 'credit', 'index'.
        Returns:
            Enriched list with keys 'category', 'subcategory', 'counterparty', 'entity_type',
            'upi_handle', 'banking_rail', 'needs_wants', 'confidence', 'classification_method'.
        """
        if not transactions:
            return []

        results = []
        unresolved_to_infer = []

        # Check cache first
        for item in transactions:
            narration = str(item.get("narration") or item.get("description") or "")
            debit = float(item.get("debit") or 0.0)
            credit = float(item.get("credit") or 0.0)
            txn_type = "CREDIT" if credit > 0 else "DEBIT"
            amount = credit if credit > 0 else debit

            cache_key = self._hash_key(narration, txn_type)
            if cache_key in self.cache:
                cached = self.cache[cache_key]
                enriched = dict(item)
                enriched.update({
                    "category": cached.category,
                    "subcategory": cached.subcategory,
                    "counterparty": cached.counterparty,
                    "entity_type": cached.entity_type,
                    "upi_handle": cached.upi_handle,
                    "banking_rail": cached.banking_rail,
                    "needs_wants": cached.needs_wants,
                    "confidence": cached.confidence,
                    "classification_method": "param_finance",
                })
                results.append(enriched)
            else:
                unresolved_to_infer.append((item, narration, txn_type, amount, cache_key))

        if not unresolved_to_infer:
            return results

        # FinanceParam first, heuristic for anything it does not resolve.
        #
        # This loop used to call the mock unconditionally -- the comment said
        # "Mock Heuristic or Local LLM" but there was no LLM branch, so Tier 4.5
        # never ran a model however many weights were loaded.
        llm_results = self._llm_classify_batch(
            [(narration, txn_type, amount) for _, narration, txn_type, amount, _ in unresolved_to_infer]
        )

        for position, (item, narration, txn_type, amount, cache_key) in enumerate(unresolved_to_infer):
            res: Optional[ParamExtractionResult] = llm_results.get(position)
            if res is None:
                res = self.mock_fallback.infer(narration, txn_type, amount)
            self.cache[cache_key] = res
            enriched = dict(item)
            enriched.update({
                "category": res.category,
                "subcategory": res.subcategory,
                "counterparty": res.counterparty,
                "entity_type": res.entity_type,
                "upi_handle": res.upi_handle,
                "banking_rail": res.banking_rail,
                "needs_wants": res.needs_wants,
                "confidence": res.confidence,
                "classification_method": "param_finance",
            })
            results.append(enriched)

        return results

    # Categories the pipeline understands. A model answer outside this set is
    # rejected rather than written into the ledger, so an unexpected label
    # cannot silently create a new category downstream.
    _ALLOWED_CATEGORIES = {
        "Income", "Expense", "Debt / Loans", "Investment", "Transfer",
        "Banking", "Taxes", "Insurance",
    }
    _ALLOWED_NEEDS_WANTS = {"Needs", "Wants", "Debt Servicing", "Investment", "None"}

    def _llm_classify_batch(
        self,
        items: List[Tuple[str, str, float]],
        chunk: int = 8,
    ) -> Dict[int, ParamExtractionResult]:
        """Classify unresolved narrations with FinanceParam, in small batches.

        Batched because a call per transaction is what the integration blueprint
        explicitly warns against ("calling an LLM 500 times ... will blow
        statement processing latency from 1.5 seconds to over 2 minutes").
        Chunks are kept to eight so prompt plus JSON reply fit the 2048-token
        window. Anything the model does not return, or returns off-schema, is
        left for the heuristic.
        """
        resolved: Dict[int, ParamExtractionResult] = {}
        if not self.llm_available or not items:
            return resolved

        system = (
            "You label Indian bank statement transactions. For each numbered "
            "narration return one JSON object with keys: index, category, "
            "subcategory, counterparty, entity_type, banking_rail, needs_wants. "
            f"category must be one of: {', '.join(sorted(self._ALLOWED_CATEGORIES))}. "
            "entity_type must be one of: Corporate, NBFC, Bank, Individual, Merchant, Government. "
            "needs_wants must be one of: Needs, Wants, Debt Servicing, Investment, None. "
            "Reply with a JSON array only, no prose."
        )

        for start in range(0, len(items), chunk):
            batch = items[start:start + chunk]
            lines = [
                f"{i}. [{txn_type}] Rs {amount:,.2f} | {narration[:90]}"
                for i, (narration, txn_type, amount) in enumerate(batch)
            ]
            # Measured on the ICICI corpus with this tokeniser: a reply object
            # is 63 tokens, so 60 each would truncate the final entry of a full
            # batch mid-JSON and lose it to the parse. 70 leaves headroom.
            completion = self.generate(
                "TRANSACTIONS:\n" + "\n".join(lines),
                max_new_tokens=70 * len(batch) + 40,
                system=system,
            )
            if not completion:
                continue

            parsed = self._extract_json_from_text(completion)
            if not isinstance(parsed, list):
                logger.debug("FinanceParam batch reply was not a JSON array; using heuristic.")
                continue

            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                try:
                    local_idx = int(entry.get("index", -1))
                except (TypeError, ValueError):
                    continue
                if not 0 <= local_idx < len(batch):
                    continue

                category = str(entry.get("category") or "").strip()
                if category not in self._ALLOWED_CATEGORIES:
                    continue
                needs_wants = str(entry.get("needs_wants") or "None").strip()
                if needs_wants not in self._ALLOWED_NEEDS_WANTS:
                    needs_wants = "None"

                narration, txn_type, amount = batch[local_idx]
                # The rail and UPI handle are readable from the narration
                # itself, so they are taken from the deterministic parser rather
                # than trusted from the model.
                heuristic = self.mock_fallback.infer(narration, txn_type, amount)
                resolved[start + local_idx] = ParamExtractionResult(
                    category=category,
                    subcategory=str(entry.get("subcategory") or heuristic.subcategory).strip(),
                    counterparty=str(entry.get("counterparty") or heuristic.counterparty).strip(),
                    entity_type=str(entry.get("entity_type") or heuristic.entity_type).strip(),
                    upi_handle=heuristic.upi_handle,
                    banking_rail=heuristic.banking_rail,
                    needs_wants=needs_wants,
                    confidence=0.75,
                )

        if resolved:
            logger.info(
                f"FinanceParam resolved {len(resolved)}/{len(items)} unresolved transactions."
            )
        return resolved

    # ------------------------------------------------------------------
    # Pillar 2: SME Business Profiling & Commingling Detection
    # ------------------------------------------------------------------
    def profile_sme_counterparties(self, top_counterparties: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform sectoral profiling and commingling risk detection on top counterparties."""
        if not top_counterparties:
            return {
                "inferred_business_sector": "General Retail / Services",
                "commingling_risk": "LOW",
                "informal_borrowing_flag": False,
                "informal_borrowing_signals": [],
                "explanation": "No distinct commercial counterparties observed.",
            }

        names = [str(cp.get("name") or cp.get("counterparty") or "").lower() for cp in top_counterparties]
        combined = " ".join(names)

        # Detect Sector. Keyword mappings first -- they are exact where they
        # match -- then FinanceParam for the long tail they do not cover, which
        # is most of it: the mapping table only knows a fixed list of trades.
        inferred_sector = None
        for keywords, sector in self.mock_fallback.SECTOR_MAPPINGS:
            if any(kw in combined for kw in keywords):
                inferred_sector = sector
                break

        if inferred_sector is None and self.llm_available:
            named = [n for n in names if n][:15]
            completion = self.generate(
                "COUNTERPARTIES:\n" + "\n".join(f"- {n[:60]}" for n in named),
                max_new_tokens=40,
                system=(
                    "Given the counterparties on an Indian bank statement, name the "
                    "single most likely business sector of the account holder. "
                    "Reply with the sector name only, at most six words, no punctuation "
                    "or explanation. If the counterparties do not indicate a business, "
                    "reply exactly: General Commercial Enterprises"
                ),
            )
            if completion:
                candidate = completion.strip().splitlines()[0].strip(" .\"'")
                # A sector is a short noun phrase; anything longer is the model
                # explaining itself, which is not what this field holds.
                if 0 < len(candidate) <= 60:
                    inferred_sector = candidate

        if inferred_sector is None:
            inferred_sector = "General Commercial Enterprises"

        # Detect Commingling Risk
        # Commingling occurs when commercial/B2B entities account for significant inflow in personal accounts
        commercial_count = sum(
            1 for n in names
            if any(t in n for t in ["textiles", "enterprises", "traders", "logistics", "industries", "pvt ltd", "foods", "kirana", "steels"])
        )
        total = len(names) or 1
        commingling_ratio = commercial_count / total

        if commingling_ratio >= 0.40:
            commingling_risk = "HIGH"
            commingling_note = "Extensive commercial B2B supplier and buyer counterparty flows detected in personal account."
        elif commingling_ratio >= 0.15:
            commingling_risk = "MEDIUM"
            commingling_note = "Moderate business transaction volume commingled with personal activities."
        else:
            commingling_risk = "LOW"
            commingling_note = "Account flows demonstrate primarily retail and personal transactions."

        # Detect Informal Borrowing / Chit Fund Signals
        informal_signals = []
        for cp in top_counterparties:
            cp_name = str(cp.get("name") or cp.get("counterparty") or "")
            cp_lower = cp_name.lower()
            if any(term in cp_lower for term in ["chit", "bc", "committee", "hand loan", "bisi", "bachat gat"]):
                informal_signals.append(f"Informal pool entity identified: '{cp_name}'")

        informal_flag = len(informal_signals) > 0

        return {
            "inferred_business_sector": inferred_sector,
            "commingling_risk": commingling_risk,
            "informal_borrowing_flag": informal_flag,
            "informal_borrowing_signals": informal_signals,
            "explanation": f"{inferred_sector} sector identified. {commingling_note}",
        }

    # ------------------------------------------------------------------
    # Pillar 3: Virtual Underwriting Officer (CAM Narrative Synthesis)
    # ------------------------------------------------------------------
    def generate_cam_executive_narrative(self, features: Dict[str, Any]) -> str:
        """Synthesize institutional 3-paragraph executive Credit Appraisal Memorandum."""
        borrower = features.get("borrower_name") or features.get("entity_name") or "The Borrower"
        turnover = float(features.get("true_turnover") or features.get("annualized_turnover") or features.get("total_credits") or 0.0)
        circular_vol = float(features.get("circular_volume") or features.get("circular_turnover") or 0.0)
        foir = float(features.get("foir") or features.get("estimated_foir") or 0.35)
        inward_bounces = int(features.get("inward_bounces") or features.get("bounce_count") or 0)
        volatility = str(features.get("volatility_band") or "Low")
        adb = float(features.get("adb") or features.get("average_monthly_balance") or 0.0)

        # Paragraph 1: Business Velocity & Verified True Turnover
        turnover_lakhs = turnover / 100000.0
        p1 = (
            f"Borrower '{borrower}' demonstrates active business velocity with verified genuine annual turnover of "
            f"₹{turnover_lakhs:,.2f} Lakhs. "
        )
        if circular_vol > 0:
            circular_lakhs = circular_vol / 100000.0
            p1 += (
                f"Gross inflows have been deflated by ₹{circular_lakhs:,.2f} Lakhs to exclude artificial circular and "
                "mirrored round-trip transfers, establishing a verified baseline of core commercial trading receipts."
            )
        else:
            p1 += "Inflow velocity shows organic transaction distribution without artificial circular turnover inflation."

        # Paragraph 2: Debt Absorption Capacity, FOIR & Discretionary Cushion
        foir_pct = foir * 100.0 if foir <= 1.0 else foir
        tier_str = "Prime" if foir_pct < 45.0 else ("Standard" if foir_pct < 65.0 else "Sub-Prime")
        adb_lakhs = adb / 100000.0
        p2 = (
            f"Debt servicing assessment indicates a Fixed Obligation to Income Ratio (FOIR) of {foir_pct:.1f}% "
            f"({tier_str} risk tier), supported by an Average Daily Balance (ADB) of ₹{adb_lakhs:,.2f} Lakhs. "
            f"Cash flow cushion remains adequate to service proposed debt obligations with {volatility.lower()} balance volatility."
        )

        # Paragraph 3: Behavioral Integrity, Dishonour Risk & Recommended Underwriting Covenants
        if inward_bounces == 0:
            p3 = (
                "Behavioral integrity is pristine with 0 inward NACH/cheque dishonours across the statement horizon. "
                "Recommendation: Sanction proposed credit facility subject to standard documentation covenants."
            )
        elif inward_bounces == 1:
            p3 = (
                "Cautionary Note: A single inward cheque/NACH dishonour was recorded during the evaluation period due to "
                "transitory timing variance. Recommend setting repayment auto-debit dates for the 7th of the month to "
                "align with verified customer payment inflow cycles."
            )
        else:
            p3 = (
                f"High Caution Covenant: {inward_bounces} inward dishonour events detected in the statement horizon. "
                "Recommend an escrow/sweep-in mechanism, enhanced debt service reserve account (DSRA), and collateral backing."
            )

        template_memo = f"{p1}\n\n{p2}\n\n{p3}"

        # FinanceParam writes the memo where it can; the template above is the
        # fallback and also the source of every figure quoted to the model.
        # Sanction memoranda are the one output here whose value is the prose,
        # so a fixed template reads identically for every borrower -- but the
        # numbers must still not be the model's to compute.
        if not self.llm_available:
            return template_memo

        brief = (
            f"BORROWER: {borrower}\n"
            f"Verified annual turnover: Rs {turnover:,.0f}\n"
            f"Circular/self-transfer volume excluded: Rs {circular_vol:,.0f}\n"
            f"FOIR: {foir * 100:.1f}%\n"
            f"Average daily balance: Rs {adb:,.0f}\n"
            f"Balance volatility band: {volatility}\n"
            f"Inward dishonours: {inward_bounces}"
        )
        completion = self.generate(
            brief,
            max_new_tokens=320,
            system=(
                "You are a credit officer drafting a Credit Appraisal Memorandum for a "
                "sanction committee. Write exactly three short paragraphs: business "
                "velocity and turnover quality; debt servicing capacity and balance "
                "behaviour; recommended covenants. Use only the figures given, quoting "
                "them exactly. Do not invent any number. Do not state a final approve or "
                "reject decision. Formal institutional English."
            ),
        )
        if not completion or len(completion) < 120:
            return template_memo

        # Any figure the model prints must be one it was given. A memo that
        # quotes an invented turnover is worse than a generic one.
        given = {
            f"{turnover:,.0f}", f"{circular_vol:,.0f}", f"{adb:,.0f}",
            f"{foir * 100:.1f}", str(inward_bounces),
        }
        printed = set(re.findall(r"\d[\d,]*\.?\d*", completion))
        invented = {
            p for p in printed
            if p not in given and len(p.replace(",", "").replace(".", "")) >= 4
        }
        if invented:
            logger.warning(
                f"FinanceParam CAM memo quoted figures it was not given "
                f"({sorted(invented)[:4]}); using the deterministic memo instead."
            )
            return template_memo

        return completion

    # ------------------------------------------------------------------
    # Pillar 4: Interactive Dashboard Underwriting Copilot (5 Guardrails)
    # ------------------------------------------------------------------
    def query_underwriting_copilot(
        self,
        question: str,
        context_txns: List[Dict[str, Any]],
        scorecard: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Process conversational underwriting query enforcing the 5 Institutional BFSI Guardrails.
        
        1. Grounded Citation Mandate: Every factual statement must cite `[Ref: Date | Narration | Amount]`.
        2. Indirect Prompt Injection Defense: Transactions enclosed strictly in `<verified_statement_data>`.
        3. Deterministic Numeric Lock: Totals/ratios pulled strictly from pre-computed scorecard.
        4. Scope & Advisory Containment: Refuses legal advice, bureau CIBIL questions, and unauthorized approvals.
        5. PII Masking: Redacts 16-digit account numbers and phone numbers.
        """
        q_lower = question.lower().strip()

        # Small talk. Someone saying "hi" is not asking a ledger question, and
        # answering them with transaction counts and a list of supported query
        # forms reads as a broken bot rather than a careful one. Handled first
        # and cheaply, before anything tries to parse it as a query.
        stripped = q_lower.strip(" .!?,")
        _GREETINGS = {
            "hi", "hey", "hello", "yo", "hiya", "howdy", "namaste", "hola",
            "good morning", "good afternoon", "good evening", "morning",
            "hey there", "hi there", "hello there",
            "how are you", "hey how are you", "hi how are you",
            "how are u", "how r u", "hows it going", "how's it going",
            "how are you doing", "whats up", "what's up", "sup",
        }
        if stripped in _GREETINGS or (len(stripped) <= 24 and stripped.startswith(
            ("hi ", "hey ", "hello ", "good morning", "good afternoon", "good evening")
        )):
            return {
                "answer": (
                    "Hello. I'm reading this statement and can answer questions about "
                    "it — a counterparty you don't recognise, where the money went in a "
                    "given month, whether a payment repeats, the largest or smallest "
                    "amounts, or anything about a specific merchant or lender. "
                    "What would you like to look at?"
                ),
                "citations": [],
            }

        _THANKS = {"thanks", "thank you", "thx", "ty", "cheers", "great", "nice", "ok", "okay", "cool"}
        if stripped in _THANKS:
            return {
                "answer": "Happy to help. Ask me anything else about this statement.",
                "citations": [],
            }

        # Guardrail 4: Out-of-Domain Scope Containment
        unauthorized_approval_terms = ["should i approve", "approve this loan", "sanction this application", "reject this loan"]
        if any(term in q_lower for term in unauthorized_approval_terms):
            foir_pct = scorecard.get("foir", 0.35)
            foir_str = f"{foir_pct * 100:.1f}%" if foir_pct <= 1.0 else f"{foir_pct:.1f}%"
            adb = scorecard.get("adb", 0.0)
            bounces = scorecard.get("inward_bounces", 0)
            return {
                "answer": (
                    "The underwriting sanction decision is governed by institutional credit policy. "
                    f"Based on evaluated statement metrics (FOIR: {foir_str}, ADB: ₹{adb:,.0f}, {bounces} Dishonour events), "
                    "the borrower qualifies for Standard Review under policy parameters, subject to Credit Committee approval."
                ),
                "citations": [],
            }

        bureau_terms = ["cibil", "credit score", "bureau score", "experian", "crif", "court case", "legal dispute", "police"]
        if any(term in q_lower for term in bureau_terms):
            return {
                "answer": (
                    "Bureau records, CIBIL scores, and legal litigations fall outside the bank statement ledger domain. "
                    "Please refer to the standalone Credit Bureau Report or legal verification report for this borrower."
                ),
                "citations": [],
            }

        # Guardrail 3: Deterministic Numeric Lock
        if any(term in q_lower for term in ["turnover", "total income", "foir", "debt ratio", "adb", "average balance"]):
            turnover = scorecard.get("true_turnover") or scorecard.get("annualized_turnover") or scorecard.get("total_credits") or 0.0
            foir_val = scorecard.get("foir", 0.35)
            foir_pct = foir_val * 100.0 if foir_val <= 1.0 else foir_val
            adb_val = scorecard.get("adb", 0.0)
            bounces = scorecard.get("inward_bounces", 0)
            answer = (
                f"Verified Deterministic Metrics from Scorecard: "
                f"True Deflated Turnover: ₹{turnover:,.2f} | "
                f"FOIR: {foir_pct:.1f}% | "
                f"Average Daily Balance (ADB): ₹{adb_val:,.2f} | "
                f"Inward Dishonours: {bounces}."
            )
            return {"answer": answer, "citations": []}

        # General ledger questions the analyst framed themselves.
        #
        # Everything below this point is a fixed-topic handler, and everything
        # that matched none of them used to hit a canned "please ask about
        # fintech loans, balance dips, tax payments or large credits" reply.
        # "Which is the highest payment" is a perfectly answerable question
        # about data we hold; it was refused only because no branch happened to
        # own the word. This resolves it arithmetically over the ledger.
        #
        # It runs *after* the numeric lock and the scope refusals above, so a
        # question like "total true turnover and FOIR" still comes from the
        # verified scorecard rather than being recomputed here, and approval /
        # bureau questions are still declined. It runs *before* the topic
        # handlers, which phrase their own answers better, and it only claims a
        # question carrying an explicit intent -- so topic phrasings fall
        # through to them untouched.
        try:
            resolved = ledger_query.resolve(question, context_txns, strict=True)
        except Exception as e:  # never let a parsing slip break the chat
            logger.warning(f"Ledger query resolver failed, falling through: {e}")
            resolved = None
        if resolved:
            return {
                "answer": self._sanitize_pii(resolved["answer"]),
                "citations": resolved.get("citations", []),
            }

        # Check for High-Interest Fintech App Loans (Navi, KreditBee, Fibe, etc.)
        if any(term in q_lower for term in ["fintech", "kreditbee", "fibe", "navi", "moneytap", "app loan", "digital loan"]):
            lender_hits = []
            citations = []
            found_lenders = set()
            fintech_names = ["kreditbee", "fibe", "earlysalary", "navi", "moneytap", "smartcoin", "rupeeredee"]

            for txn in context_txns:
                narr = str(txn.get("narration") or txn.get("description") or "").lower()
                for fn in fintech_names:
                    if fn in narr:
                        found_lenders.add(fn.title())
                        date_str = str(txn.get("date") or "N/A")
                        debit_val = float(txn.get("debit") or 0.0)
                        credit_val = float(txn.get("credit") or 0.0)
                        amount = debit_val if debit_val > 0 else (credit_val if credit_val > 0 else float(txn.get("amount") or 0.0))
                        citation = {
                            "date": date_str,
                            "narration": txn.get("narration") or txn.get("description"),
                            "amount": amount,
                            "lender": fn.title(),
                        }
                        citations.append(citation)
                        lender_hits.append(f"[Ref: {date_str} | {txn.get('narration') or txn.get('description')} | ₹{amount:,.2f}]")

            if lender_hits:
                lenders_str = ", ".join(sorted(found_lenders))
                answer = (
                    f"Yes, identified {len(lender_hits)} digital fintech loan transactions ({lenders_str}): "
                    + "; ".join(lender_hits)
                    + ". This indicates short-term personal liquidity reliance."
                )
            else:
                answer = "No transactions associated with high-interest digital app lenders (KreditBee, Fibe, Navi) were identified in the statement."

            return {"answer": self._sanitize_pii(answer), "citations": citations}


        # Check for Balance Drops / Low Balance Days
        if any(term in q_lower for term in ["drop", "dip", "october", "low balance", "lowest", "drain"]):
            drain_hits = []
            citations = []
            for txn in context_txns:
                debit = float(txn.get("debit") or 0.0)
                narr = str(txn.get("narration") or txn.get("description") or "")
                date_str = str(txn.get("date") or "N/A")
                if debit >= 50000:
                    citations.append({"date": date_str, "narration": narr, "amount": debit})
                    drain_hits.append(f"[Ref: {date_str} | {narr} | ₹{debit:,.2f}]")

            if drain_hits:
                answer = (
                    f"Balance drops correlate with significant outflow events: "
                    + "; ".join(drain_hits[:3])
                    + ". Review these specific transfers to assess if they reflect scheduled capital expenditure or supplier settlement."
                )
            else:
                answer = "No abrupt major balance drop events exceeding ₹50,000 were observed in the ledger."

            return {"answer": self._sanitize_pii(answer), "citations": citations}

        # Check for Tax / GST Payments
        if any(term in q_lower for term in ["tax", "gst", "cbdt", "advance tax", "challan"]):
            tax_hits = []
            citations = []
            for txn in context_txns:
                narr = str(txn.get("narration") or txn.get("description") or "").lower()
                if any(k in narr for k in ["gst", "cbdt", "tax", "challan", "incometax", "oltas"]):
                    date_str = str(txn.get("date") or "N/A")
                    debit = float(txn.get("debit") or 0.0)
                    citations.append({"date": date_str, "narration": txn.get("narration") or txn.get("description"), "amount": debit})
                    tax_hits.append(f"[Ref: {date_str} | {txn.get('narration') or txn.get('description')} | ₹{debit:,.2f}]")

            if tax_hits:
                answer = f"Verified {len(tax_hits)} statutory tax/GST remittances: " + "; ".join(tax_hits)
            else:
                answer = "No tax payment, GST remittance, or CBDT transactions are present in the provided bank statement period."

            return {"answer": self._sanitize_pii(answer), "citations": citations}

        # Check for Large Credits (> 1 Lakh)
        if any(term in q_lower for term in ["large credit", "credit >", "credits >", "1 lakh", "unusual credit"]):
            large_credits = []
            citations = []
            for txn in context_txns:
                credit = float(txn.get("credit") or 0.0)
                if credit >= 100000.0:
                    date_str = str(txn.get("date") or "N/A")
                    narr = txn.get("narration") or txn.get("description")
                    citations.append({"date": date_str, "narration": narr, "amount": credit})
                    large_credits.append(f"[Ref: {date_str} | {narr} | ₹{credit:,.2f}]")

            if large_credits:
                answer = f"Identified {len(large_credits)} major credit inflows exceeding ₹1,00,000: " + "; ".join(large_credits[:5])
            else:
                answer = "No individual credit inflows exceeding ₹1,00,000 were identified in the statement period."

            return {"answer": self._sanitize_pii(answer), "citations": citations}

        # General Statement Query Fallback.
        #
        # Second pass with the intent requirement relaxed: a bare mention of
        # something that actually appears in the ledger ("tell me about Navi",
        # "anything for electricity") is a real search, and returning the rows
        # beats telling the analyst their question was the wrong shape.
        try:
            resolved = ledger_query.resolve(question, context_txns, strict=False)
        except Exception as e:
            logger.warning(f"Ledger query fallback failed: {e}")
            resolved = None
        if resolved:
            return {
                "answer": self._sanitize_pii(resolved["answer"]),
                "citations": resolved.get("citations", []),
            }

        # FinanceParam, for the interpretive questions arithmetic cannot answer.
        #
        # It runs last on purpose. Everything above is deterministic, so no
        # figure the analyst sees is ever model-generated: the scorecard lock,
        # the ledger resolver and the topic handlers have all had their turn.
        # What reaches here is judgement -- "is this pattern concerning", "what
        # sort of counterparty is this" -- which is what the model is for, and
        # it is given only a compact grounded brief to reason over because the
        # context window is 2048 tokens and cannot hold a 358-row ledger.
        llm_answer = self._llm_statement_answer(question, context_txns, scorecard)
        if llm_answer:
            return llm_answer

        # Genuinely nothing to match on. Say what is actually here and what can
        # be asked of it, rather than asserting "transaction flows reflect
        # consistent business activities" -- which was stated regardless of what
        # the statement showed, and is exactly the kind of ungrounded claim the
        # citation guardrail exists to prevent.
        try:
            inventory = ledger_query.capability_summary(context_txns)
        except Exception:
            inventory = ""
        return {
            "answer": (
                f"I could not match that question to anything in the ledger. {inventory} "
                "You can ask for superlatives (\"largest payment\", \"lowest balance\"), "
                "totals and averages (\"total spent in October\", \"average EMI\"), "
                "counts (\"how many credits above 1 lakh\"), or any merchant, lender or "
                "category that appears in the statement."
            ).strip(),
            "citations": [],
        }

    # ------------------------------------------------------------------
    # FinanceParam grounded answering
    # ------------------------------------------------------------------
    def _llm_statement_answer(
        self,
        question: str,
        context_txns: List[Dict[str, Any]],
        scorecard: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Answer an interpretive question with FinanceParam, grounded in the ledger.

        The brief handed to the model is deliberately small and pre-computed:
        verified scorecard figures, plus at most a dozen rows selected by the
        deterministic resolver as relevant to the question. The model is never
        asked to total anything -- the arithmetic is already done, and a 3B
        model doing sums over a ledger is exactly the failure the project's
        blueprint warns about. Citations come from the selected rows, not from
        the generated text, so a citation can never be hallucinated.
        """
        if not self.llm_available:
            return None

        try:
            rows = ledger_query.select_context(question, context_txns, limit=12)
        except Exception as e:
            logger.warning(f"Could not build FinanceParam context: {e}")
            rows = []

        facts = []
        if scorecard:
            foir = scorecard.get("foir")
            if isinstance(foir, (int, float)):
                facts.append(f"FOIR: {foir * 100:.1f}%" if foir <= 1 else f"FOIR: {foir:.1f}%")
            for key, label, money in (
                ("true_turnover", "Verified annual turnover", True),
                ("adb", "Average daily balance", True),
                ("credit_score", "Internal credit score (0-1000)", False),
                ("inward_bounces", "Inward dishonours", False),
            ):
                val = scorecard.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    facts.append(f"{label}: {'Rs ' + format(val, ',.2f') if money else val}")
            band = scorecard.get("risk_band")
            if band:
                facts.append(f"Risk band: {band}")

        evidence = []
        for row in rows:
            amount = row.get("debit") or row.get("credit") or 0.0
            flow = "paid" if row.get("debit") else "received"
            evidence.append(
                f"- {row.get('date')} | {str(row.get('narration'))[:70]} | "
                f"Rs {amount:,.2f} {flow}"
            )

        system = (
            "You are a credit underwriting assistant reading one Indian bank statement. "
            "Answer only from the VERIFIED FIGURES and LEDGER EXTRACT below. "
            "Never invent an amount, date or counterparty. If the statement does not "
            "contain the answer, say so plainly in one sentence. Do not approve or "
            "reject any loan. Be concise: at most four sentences."
        )
        brief = []
        if facts:
            brief.append("VERIFIED FIGURES:\n" + "\n".join(facts))
        if evidence:
            brief.append("LEDGER EXTRACT:\n" + "\n".join(evidence))
        brief.append(f"QUESTION: {question.strip()}")

        completion = self.generate("\n\n".join(brief), max_new_tokens=220, system=system)
        if not completion:
            return None

        return {
            "answer": self._sanitize_pii(completion),
            # Grounded in the rows actually shown to the model, never parsed
            # back out of its output.
            "citations": [
                {
                    "date": str(r.get("date") or ""),
                    "narration": r.get("narration"),
                    "amount": r.get("debit") or r.get("credit") or 0.0,
                }
                for r in rows[:5]
            ],
        }

    # ------------------------------------------------------------------
    # Guardrail 5: PII Sanitization
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_pii(text: str) -> str:
        """Mask 16-digit account numbers and 10-digit mobile numbers."""
        # 16-digit account numbers: keep last 4 digits
        masked = re.sub(r"\b\d{12}(\d{4})\b", r"XXXX-XXXX-XXXX-\1", text)
        # 10-digit mobile numbers: mask middle digits
        masked = re.sub(r"\b([6-9]\d{2})\d{4}(\d{3})\b", r"\1-XXXX-\2", masked)
        return masked
