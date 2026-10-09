import os
import sys
import json
import logging
import traceback
import pandas as pd
from pathlib import Path

logger = logging.getLogger("ExtractorAdapter")

# Locate project root containing extractor.py dynamically
BACKEND_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = BACKEND_DIR
while PROJECT_ROOT != PROJECT_ROOT.parent:
    if (PROJECT_ROOT / "extractor.py").exists():
        break
    PROJECT_ROOT = PROJECT_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FE_DIR = PROJECT_ROOT / "Feature Extraction"
if str(FE_DIR) not in sys.path:
    sys.path.insert(0, str(FE_DIR))

# Import StandalonePDFExtractor from project root extractor.py
try:
    from extractor import StandalonePDFExtractor, _import_pipeline, PdfPasswordError
except ImportError as err:
    logger.error(f"Could not import StandalonePDFExtractor from {PROJECT_ROOT}: {err}")
    StandalonePDFExtractor = None
    _import_pipeline = lambda: (None, None)

    class PdfPasswordError(Exception):
        """Stand-in so `except PdfPasswordError` stays valid without the extractor."""

        def __init__(self, message: str = "", *, password_supplied: bool = False):
            super().__init__(message)
            self.password_supplied = password_supplied

_extractor_instance = None

def get_extractor():
    global _extractor_instance
    if _extractor_instance is None and StandalonePDFExtractor is not None:
        try:
            _extractor_instance = StandalonePDFExtractor()
        except Exception as e:
            logger.error(f"Failed to instantiate StandalonePDFExtractor: {e}")
    if _extractor_instance is not None:
        try:
            _extractor_instance.reload_templates()
        except Exception:
            pass
    return _extractor_instance


def reload_extractor_templates():
    """Reload templates from disk into the running StandalonePDFExtractor instance."""
    global _extractor_instance
    if _extractor_instance is not None and hasattr(_extractor_instance, "reload_templates"):
        try:
            _extractor_instance.reload_templates()
            logger.info("Reloaded StandalonePDFExtractor templates from disk.")
        except Exception as e:
            logger.error(f"Failed to reload extractor templates: {e}")
    elif StandalonePDFExtractor is not None:
        try:
            _extractor_instance = StandalonePDFExtractor()
            logger.info("Initialized fresh StandalonePDFExtractor instance.")
        except Exception as e:
            logger.error(f"Failed to initialize extractor: {e}")


def probe_pdf(file_path: Path, password: str = None) -> dict:
    """Is this PDF readable at all -- encrypted, unlocked, does it carry text?"""
    extractor = get_extractor()
    if not extractor:
        return {"encrypted": False, "unlocked": True, "pages": 0,
                "has_text_layer": False, "error": "extractor unavailable"}
    from extractor import probe_pdf as _probe
    return _probe(file_path, password)


def read_statement_anchors(file_path: Path, password: str = None):
    """
    Read the facts the statement prints about itself (see utils/anchors.py).

    Returns a StatementAnchors, or None if the module is unavailable. Never
    raises: verification is a safety net, and failing to read the anchors must
    not stop a statement from being analysed -- it just means the result comes
    back UNVERIFIED instead of VERIFIED.
    """
    try:
        from src.utils.anchors import extract_anchors
        return extract_anchors(file_path, password)
    except Exception as e:
        logger.warning(f"Could not read statement anchors for {file_path.name}: {e}")
        return None


def detect_bank_name(file_path: Path, password: str = None) -> str:
    """Detects the bank name from a given PDF file using StandalonePDFExtractor."""
    extractor = get_extractor()
    if extractor:
        try:
            return extractor.detect_bank(file_path, password)
        except PdfPasswordError:
            # A locked file must not be reported as an unrecognised bank.
            raise
        except Exception as e:
            logger.warning(f"Error detecting bank name: {e}")
    return "Other"


def extract_account_holder(file_path: Path, password: str = None) -> dict:
    """Reads the account holder's name and number off the statement itself.

    Returns {"account_holder": str|None, "account_number": str|None}. Never
    invents a name: some e-statements genuinely omit it, and self-transfer
    detection stands down rather than guess when the holder is unknown.
    """
    extractor = get_extractor()
    if not extractor:
        return {"account_holder": None, "account_number": None}
    try:
        return extractor.extract_account_holder(file_path, password)
    except PdfPasswordError:
        raise
    except Exception as e:
        logger.warning(f"Account holder extraction failed for {file_path.name}: {e}")
        return {"account_holder": None, "account_number": None}


def extract_statement(file_path: Path, bank_name: str, password: str = None) -> pd.DataFrame:
    """Extracts statement transactions into a standardized pandas DataFrame.

    DataFrame schema: ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
    """
    extractor = get_extractor()
    if not extractor:
        logger.error("StandalonePDFExtractor is unavailable.")
        return pd.DataFrame(columns=['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance'])

    try:
        df = extractor.extract_with_template(file_path, bank_name, password)
        return df
    except PdfPasswordError:
        raise
    except Exception as e:
        logger.error(f"Extraction failed for {file_path.name}: {e}\n{traceback.format_exc()}")
        return pd.DataFrame(columns=['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance'])


def extract_multiple_statements(file_paths: list, bank_name: str = None, password: str = None) -> pd.DataFrame:
    """Extracts and merges multiple statement transactions into a single standardized DataFrame."""
    extractor = get_extractor()
    if not extractor:
        logger.error("StandalonePDFExtractor is unavailable.")
        return pd.DataFrame(columns=['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance'])

    try:
        df = extractor.extract_multiple_statements(file_paths, bank_name, password)
        return df
    except PdfPasswordError:
        raise
    except Exception as e:
        logger.error(f"Multi-statement extraction failed: {e}\n{traceback.format_exc()}")
        return pd.DataFrame(columns=['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance'])


def run_feature_analysis(df: pd.DataFrame, bank_name: str, csv_path: str = None,
                         account_holder_name: str = None,
                         applicant_id: str = None,
                         extraction_diagnostics: dict = None) -> dict:
    """Runs the feature extraction pipeline on the extracted DataFrame/CSV.

    account_holder_name lets the pipeline tell transfers between the applicant's
    own accounts apart from real income; applicant_id lets an applicant-scoped
    counterparty override beat a global one; extraction_diagnostics carries what
    the PDF extractor saw, which the pipeline cannot observe for itself.

    On failure this returns a bundle carrying `analysis_status`, never a bare
    {} -- an empty dict was indistinguishable from a successful run with no
    findings, and compute_loan_result rendered it as a green "success".
    """
    process_single_csv, TransactionClassifier = _import_pipeline()
    clean_stats = {k: v for k, v in (extraction_diagnostics or {}).items() if not k.startswith('_')}
    if process_single_csv is None:
        logger.warning("Feature Extraction pipeline is unavailable.")
        return {"analysis_status": "pipeline_unavailable",
                "extraction_stats": clean_stats}

    try:
        classifier_instance = None
        if TransactionClassifier is not None:
            try:
                classifier_instance = TransactionClassifier()
            except Exception as e:
                logger.warning(f"Could not initialize classifier: {e}")

        fe_output_dir = str(FE_DIR / "outputs")
        features = process_single_csv(
            csv_path=csv_path or "",
            bank_name=bank_name,
            output_dir=fe_output_dir,
            classifier=classifier_instance,
            input_df=df,
            account_holder_name=account_holder_name,
            applicant_id=applicant_id,
            extraction_diagnostics=extraction_diagnostics,
        )
        if not features:
            return {"analysis_status": "no_features_returned",
                    "extraction_stats": clean_stats}
        return features
    except Exception as e:
        logger.error(f"Feature analysis failed: {e}\n{traceback.format_exc()}")
        return {"analysis_status": "error",
                "analysis_error": str(e),
                "extraction_stats": clean_stats}


def format_transactions_for_db(df: pd.DataFrame) -> list:
    """Converts the extracted DataFrame into dict records suitable for database insertion."""
    records = []
    if df.empty:
        return records

    for _, row in df.iterrows():
        date_val = str(row.get('Date', '')) if pd.notnull(row.get('Date')) else ""
        desc_val = str(row.get('Description', '')) if pd.notnull(row.get('Description')) else ""
        
        try:
            debit_val = float(row.get('Withdrawal Amt.', 0.0) or 0.0)
        except (ValueError, TypeError):
            debit_val = 0.0

        try:
            credit_val = float(row.get('Deposit Amt.', 0.0) or 0.0)
        except (ValueError, TypeError):
            credit_val = 0.0

        try:
            balance_val = float(row.get('Closing Balance', 0.0) or 0.0)
        except (ValueError, TypeError):
            balance_val = 0.0

        records.append({
            'date': date_val,
            'description': desc_val,
            'debit': debit_val,
            'credit': credit_val,
            'balance': balance_val
        })
    return records


def compute_loan_result(df: pd.DataFrame, features: dict = None) -> dict:
    """Calculates financial score & metrics summary from extracted DataFrame and features."""
    if df.empty:
        # None, not 0.0 -- "we could not determine this" must not be stored as
        # "this is zero", which reads on screen as a borrower with no debt.
        return {
            "decision": "failed",
            "confidence_score": None,
            "reasoning": "No valid transaction data extracted.",
            "average_monthly_balance": None,
            "total_income": None,
            "total_expenses": None,
            "debt_to_income_ratio": None,
            "monthly_obligations": None,
            "metadata": {}
        }

    # The Feature Extraction engines are the single source of truth for these
    # figures. This function used to recompute them from the raw frame -- income
    # as *every* credit, expenses as *every* debit, DTI as the ratio of the two.
    # That is a burn ratio, not a debt-to-income ratio, which is why it read
    # 109% for a solvent account while the debt engine computed 62%. The
    # "override from feature analysis" block below it tested for top-level keys
    # (`total_income`, `avg_monthly_balance`) that the nested bundle has never
    # had, so it was dead code and never once fired.
    f = features if isinstance(features, dict) else {}
    income_f = f.get("income") or {}
    expense_f = f.get("expense") or {}
    balance_f = f.get("balance") or {}
    debt_f = f.get("debt") or {}

    def _pick(*candidates):
        """First non-None candidate, else None (never a fabricated stand-in)."""
        for c in candidates:
            if c is not None:
                try:
                    return float(c)
                except (TypeError, ValueError):
                    continue
        return None

    total_income = _pick(income_f.get("total_income"))
    total_expenses = _pick(expense_f.get("total_expenses"))
    avg_monthly_balance = _pick(balance_f.get("average_daily_balance"))
    dti_ratio = _pick(debt_f.get("dti"))
    monthly_obligations = _pick(debt_f.get("monthly_emi"), debt_f.get("total_monthly_obligations"))

    if not f:
        logger.warning(
            "compute_loan_result: no feature bundle supplied; financial metrics "
            "will be reported as unavailable rather than recomputed naively"
        )

    # Real deterministic-classification coverage, not a transaction-count proxy.
    # The previous value was literally `0.95 if len(df) > 5 else 0.85` and was
    # surfaced in the UI as "Confidence Score" and "Extraction accuracy".
    classification = f.get("classification_summary") or {}
    deterministic_pct = classification.get("deterministic_pct")
    confidence = round(float(deterministic_pct) / 100.0, 4) if deterministic_pct is not None else None

    meta_dict = {
        "total_transactions": len(df),
        "transaction_count": len(df),
        "features_summary": features if isinstance(features, dict) else {}
    }
    if isinstance(features, dict):
        for k, v in features.items():
            meta_dict[k] = v

    summary = f.get("underwriting_summary") or {}
    recon = f.get("reconciliation") or {}
    reasoning = (
        f"Extracted {len(df)} transactions. "
        f"Underwriting decision: {summary.get('underwriting_decision', 'not computed')}"
        f" (credit score {summary.get('credit_score', 'n/a')}, "
        f"risk band {summary.get('risk_band', 'n/a')}). "
        f"Cross-engine reconciliation: {recon.get('status', 'not run')}."
    )
    if summary.get("decision_coherence_note"):
        reasoning += f" {summary['decision_coherence_note']}"

    # An analysis that produced no engine output is not a success. Rows were
    # extracted, so the df.empty branch above does not catch it, and the result
    # used to render as a green "success" badge alongside "Confidence Score: 0%"
    # with every financial metric blank.
    # The gate. If the statement's own printed figures disagree with what we
    # parsed, the numbers below are not trustworthy and must not be presented as
    # a decision. Refusing is strictly better than a confident wrong answer --
    # this is the case where everything downstream looks perfectly healthy.
    fidelity = f.get("extraction_fidelity") or {}
    recon = f.get("reconciliation") or {}
    if fidelity.get("status") == "FAILED" or recon.get("status") == "FAIL":
        failures = [c for c in fidelity.get("checks", []) if not c.get("passed")]
        if not failures:
            failures = [c for c in recon.get("checks", []) if not c.get("passed")]
        fail_summary = "; ".join(
            f"{c['check']} (expected {c['expected']}, got {c['actual']})" for c in failures[:3]
        )
        logger.error(f"compute_loan_result: extraction fidelity / reconciliation FAILED -- {fail_summary}")
        if isinstance(f, dict):
            f.setdefault("underwriting_summary", {})
            f["underwriting_summary"]["credit_score"] = None
            f["underwriting_summary"]["risk_band"] = "INTEGRITY_COMPROMISED"
            f["underwriting_summary"]["underwriting_decision"] = "REJECT_INTEGRITY_COMPROMISED"
            f["underwriting_summary"]["decision_coherence_note"] = (
                f"Document failed integrity verification: {fail_summary}. Scoring suppressed."
            )
            meta_dict["underwriting_summary"] = f["underwriting_summary"]
        return {
            "decision": "extraction_unverified",
            "confidence_score": None,
            "reasoning": (
                f"Extracted {len(df)} transactions, but they do not agree with the figures "
                f"printed on the statement: {fail_summary}. No credit decision is available "
                f"until the statement parses correctly."
            ),
            "average_monthly_balance": None,
            "total_income": None,
            "total_expenses": None,
            "debt_to_income_ratio": None,
            "monthly_obligations": None,
            "metadata": meta_dict,
        }

    analysis_status = f.get("analysis_status")
    if analysis_status or not f:
        why = {
            "no_valid_transactions": "no transactions survived validation",
            "pipeline_unavailable": "the analysis pipeline could not be loaded",
            "no_features_returned": "the analysis pipeline returned no features",
            "error": f"the analysis pipeline failed: {f.get('analysis_error', 'unknown error')}",
        }.get(analysis_status, "the analysis pipeline produced no output")
        logger.error(f"compute_loan_result: analysis incomplete -- {why}")
        return {
            "decision": "analysis_incomplete",
            "confidence_score": None,
            "reasoning": (
                f"Extracted {len(df)} transactions, but scoring did not complete: {why}. "
                f"No credit decision is available for this statement."
            ),
            "average_monthly_balance": None,
            "total_income": None,
            "total_expenses": None,
            "debt_to_income_ratio": None,
            "monthly_obligations": None,
            "metadata": meta_dict,
        }

    return {
        "decision": "success",
        "confidence_score": confidence,
        "reasoning": reasoning,
        "average_monthly_balance": round(avg_monthly_balance, 2) if avg_monthly_balance is not None else None,
        "total_income": round(total_income, 2) if total_income is not None else None,
        "total_expenses": round(total_expenses, 2) if total_expenses is not None else None,
        "debt_to_income_ratio": dti_ratio,
        "monthly_obligations": monthly_obligations,
        "metadata": meta_dict
    }
