"""
Pipeline Orchestrator — End-to-end flow

    1. Load CSV + settings
    2. Auto-detect bank from filename (or use --bank override)
    3. Validate & clean
    4. Classify all transactions (bank-aware)
    5. Save classified DataFrame
    6. Run Modules 2–10 (independent feature engines)
    7. Aggregate features
    8. Save JSON + CSV outputs

CLI usage:
    python -m src.pipeline --input path/to/statement.csv [--bank ICICI]
    python -m src.pipeline --input-dir output/    # batch mode
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from src.utils import reconciliation
from src.utils import extraction_fidelity
from src.utils.validation import (
    load_settings,
    infer_bank_name,
    get_bank_config,
    validate_and_clean,
)
from src.classifier import TransactionClassifier
from src.engines import income, expense, balance, cashflow, savings, investment
from src.engines import debt_engine, behaviour_engine, fraud_engine
from src.engines.common_utils import BankStatementParser
from src.feature_aggregator import aggregate, save_all

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Pipeline")


def process_single_csv(
    csv_path: str,
    bank_name: Optional[str] = None,
    settings: Optional[dict] = None,
    output_dir: Optional[str] = None,
    classifier: Optional[TransactionClassifier] = None,
    input_df: Optional[pd.DataFrame] = None,
    account_holder_name: Optional[str] = None,
    applicant_id: Optional[str] = None,
    extraction_diagnostics: Optional[dict] = None,
) -> dict:
    """
    Process a single bank statement CSV (or in-memory DataFrame) through the full pipeline.

    Args:
        account_holder_name: whose account this is. Used to tell transfers
            between the holder's own accounts apart from real income and
            spending. Without it, self-transfers are not detected -- a shared
            surname alone is a relative at least as often as a second account.
        applicant_id: lets an applicant-scoped counterparty override take
            precedence over a global one.
        extraction_diagnostics: what the PDF extractor observed on the way in
            (template used, pages that failed to parse). The pipeline cannot
            see any of that itself -- it receives an already-extracted frame --
            so the caller has to hand it over for it to reach the bundle.
    """
    if settings is None:
        settings = load_settings()

    # Per-run context the classifier reads for self-transfer detection and
    # applicant-scoped counterparty overrides.
    if account_holder_name or applicant_id:
        settings = dict(settings)
        if account_holder_name:
            settings["account_holder_name"] = account_holder_name
        if applicant_id:
            settings["applicant_id"] = applicant_id
        # A caller-supplied classifier was built with different settings.
        if classifier is not None and (
            getattr(classifier, "account_holder_name", "") != (account_holder_name or "")
        ):
            classifier = None

    # --- Step 1: Infer bank name ---
    if bank_name is None:
        bank_name = infer_bank_name(csv_path)
    logger.info(f"Processing: {Path(csv_path).name} | Bank: {bank_name}")

    bank_config = get_bank_config(settings, bank_name)

    # --- Step 2: Load and validate ---
    logger.info("Step 1/5: Loading and validating CSV")
    if input_df is not None:
        raw_df = input_df.copy()
    else:
        csv_file = Path(csv_path)
        if not csv_file.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        raw_df = pd.read_csv(csv_path, encoding="utf-8")
    df, validation_stats = validate_and_clean(raw_df, bank_name, settings)

    if df.empty:
        logger.error("No valid transactions after cleaning. Aborting.")
        # Return the reason rather than a bare {}. An empty dict is
        # indistinguishable from "the pipeline crashed", and the caller used to
        # render both as a successful analysis.
        return {
            "analysis_status": "no_valid_transactions",
            "extraction_stats": {
                **(validation_stats or {}),
                **(extraction_diagnostics or {}),
            },
        }

    logger.info(f"Valid transactions: {len(df)}")

    # --- Step 3: Classify transactions ---
    logger.info("Step 2/5: Classifying transactions")
    if classifier is None:
        classifier = TransactionClassifier(settings=settings)
    classified_df = classifier.classify_dataframe(df, bank_name)

    # Save classified DataFrame
    if output_dir is None:
        output_dir = str(Path(__file__).parent.parent / "outputs")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    prefix = bank_name.replace(" ", "_")
    classified_csv_path = output_path / f"{prefix}_classified.csv"
    classified_df.to_csv(classified_csv_path, index=False, encoding="utf-8")
    logger.info(f"Saved classified transactions: {classified_csv_path}")

    # --- Step 4: Run feature engines ---
    logger.info("Step 3/5: Running feature engines concurrently in parallel threads")
    from concurrent.futures import ThreadPoolExecutor

    context = {"bank_config": bank_config}

    # Enrich with parsed_payee / rail_type / txn_id. The behaviour and fraud
    # engines guard on these columns and silently no-op without them, which
    # disabled four AML detectors, cash_preference and merchant_diversity.
    classified_df = BankStatementParser(bank_code=bank_name).enrich(classified_df)

    # Wave 1: engines with no cross-engine dependencies.
    with ThreadPoolExecutor(max_workers=4) as executor:
        f_income = executor.submit(income.process, classified_df.copy(), context)
        f_balance = executor.submit(balance.process, classified_df.copy(), context)
        f_cashflow = executor.submit(cashflow.process, classified_df.copy(), context)
        f_fraud = executor.submit(fraud_engine.process, classified_df.copy(), context)

        income_features = f_income.result()
        balance_features = f_balance.result()
        cashflow_features = f_cashflow.result()
        fraud_features = f_fraud.result()

    context["income"] = income_features
    context["balance"] = balance_features
    context["cash_flow"] = cashflow_features
    context["fraud"] = fraud_features

    # Wave 2: engines that read income/balance out of the context. These used to
    # run alongside income in a single wave, so context["income"] was always
    # empty when they read it -- expense_ratio and investment_ratio came out 0.0
    # and the debt engine fell back to a hardcoded income.
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_expense = executor.submit(expense.process, classified_df.copy(), context)
        f_investment = executor.submit(investment.process, classified_df.copy(), context)
        f_debt = executor.submit(debt_engine.process, classified_df.copy(), context)

        expense_features = f_expense.result()
        investment_features = f_investment.result()
        debt_features = f_debt.result()

    context["expense"] = expense_features
    context["investment"] = investment_features
    context["debt"] = debt_features

    # Wave 3: engines that depend on wave 2 output (savings needs expense).
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_savings = executor.submit(savings.process, classified_df.copy(), context)
        f_behaviour = executor.submit(behaviour_engine.process, classified_df.copy(), context)

        savings_features = f_savings.result()
        behaviour_features = f_behaviour.result()

    # --- Step 5: Aggregate and save ---
    logger.info("Step 4/5: Aggregating features")

    # Determine statement period
    statement_period = {}
    if not classified_df.empty:
        statement_period = {
            "start": str(classified_df["date"].min().date()),
            "end": str(classified_df["date"].max().date()),
        }

    # SME Business Profiling (Pillar 2)
    try:
        from src.engines.business_profiler import profile_business
        business_profile = profile_business(classified_df)
    except Exception as e:
        logger.warning(f"Business profiling encountered error: {e}")
        business_profile = {}

    # L2 Credit Auditor (2-Step Verification)
    try:
        from src.engines.credit_auditor import audit_statement
        audit_output = audit_statement(classified_df, {
            "income": income_features,
            "fraud": fraud_features,
            "balance": balance_features,
            "cash_flow": cashflow_features,
            "debt": debt_features,
        })
    except Exception as e:
        logger.warning(f"Credit auditor encountered error: {e}")
        audit_output = {}

    engine_outputs = {
        "income": income_features,
        "expense": expense_features,
        "balance": balance_features,
        "cash_flow": cashflow_features,
        "savings": savings_features,
        "investment": investment_features,
        "debt": debt_features,
        "behaviour": behaviour_features,
        "fraud": fraud_features,
        "business_profiler": business_profile,
        "audit_verification": audit_output,
    }

    combined_features = aggregate(engine_outputs, bank_name, statement_period)

    # Cross-engine reconciliation. Publishes whether the bundle's numbers agree
    # with each other and with the account ledger.
    combined_features["reconciliation"] = reconciliation.check(classified_df, combined_features)

    # Does the parsed frame agree with what the statement prints about itself?
    # This is the only check in the bundle whose reference values do not come
    # from our own extraction, so it is the only one that can catch a statement
    # that was read wrongly but self-consistently.
    statement_anchors = (extraction_diagnostics or {}).pop("_anchors", None)
    if statement_anchors is not None:
        combined_features["extraction_fidelity"] = extraction_fidelity.check(
            classified_df, statement_anchors,
            {**(validation_stats or {}), **(extraction_diagnostics or {})},
        )
        logger.info(
            f"Extraction fidelity: {combined_features['extraction_fidelity']['status']} "
            f"({combined_features['extraction_fidelity']['failed_count']} failed check(s))"
        )

    # How the statement was read, as opposed to how it was categorised. These
    # numbers were computed by validate_and_clean and then dropped on the floor
    # -- the count of rows that break the running-balance chain existed only in
    # a log line, so nothing downstream could tell a clean parse from a mangled
    # one.
    combined_features["extraction_stats"] = {
        **(validation_stats or {}),
        **(extraction_diagnostics or {}),
    }

    # Compute classification summary stats
    classification_summary = {}
    if not classified_df.empty:
        total_count = len(classified_df)
        methods = classified_df["classification_method"].astype(str)
        bank_rule_count = int((methods == "bank_rule").sum())
        keyword_count = int((methods == "keyword").sum())
        fuzzy_count = int((methods == "fuzzy").sum())

        # Deterministic means "decided by a rule", not "decided by one of the
        # three tiers we happened to list first". Counting only bank_rule +
        # keyword + fuzzy understated coverage by everything the rail fallback,
        # self-transfer, override and recurrence passes resolve -- 22% of rows
        # on the current corpus. Invert instead: everything that is not the
        # model and not a miss is deterministic.
        non_deterministic = {"slm", "slm_low_confidence", "none", ""}
        deterministic_count = int((~methods.isin(non_deterministic)).sum())
        deterministic_pct = round((deterministic_count / total_count) * 100, 1) if total_count > 0 else 0.0

        classification_summary = {
            "total_count": total_count,
            "bank_rule_count": bank_rule_count,
            "keyword_count": keyword_count,
            "fuzzy_count": fuzzy_count,
            "deterministic_count": deterministic_count,
            "deterministic_pct": deterministic_pct,
            "method_breakdown": {
                str(k): int(v) for k, v in methods.value_counts().items()
            },
        }

    # Save outputs
    logger.info("Step 5/5: Saving outputs")
    saved_paths = save_all(
        combined_features,
        str(output_path),
        bank_name,
        classification_summary=classification_summary,
    )

    # Publish the real classification coverage in the returned bundle. It was
    # previously computed and written only to the key-results markdown, so
    # downstream consumers (the web API) had to invent a confidence figure.
    combined_features["classification_summary"] = classification_summary

    logger.info(f"Pipeline complete for {bank_name}:")
    logger.info(f"  Classified CSV:  {classified_csv_path}")
    logger.info(f"  Features JSON:   {saved_paths['json']}")
    logger.info(f"  Features CSV:    {saved_paths['csv']}")
    logger.info(f"  Key Results CSV: {saved_paths.get('key_results_csv')}")
    logger.info(f"  Key Results MD:  {saved_paths.get('key_results_md')}")

    # Print classification summary
    if not classified_df.empty:
        method_counts = classified_df["classification_method"].value_counts()
        logger.info(f"  Classification breakdown:")
        for method, count in method_counts.items():
            logger.info(f"    {method}: {count} ({count/len(classified_df)*100:.1f}%)")

    return combined_features


def process_directory(
    input_dir: str,
    settings: Optional[dict] = None,
    output_dir: Optional[str] = None,
    classifier: Optional[TransactionClassifier] = None,
) -> dict:
    """
    Batch process all *_extracted.csv files in a directory.

    Args:
        input_dir: Directory containing extracted CSVs
        settings: Configuration settings dict
        output_dir: Directory for output files
        classifier: Optional pre-warmed TransactionClassifier instance to reuse across batch files

    Returns:
        Dict mapping bank_name → feature dict
    """
    input_path = Path(input_dir)
    csv_files = list(input_path.glob("*_extracted.csv")) + list(input_path.glob("*.csv"))
    # Deduplicate
    csv_files = list(set(csv_files))

    if not csv_files:
        logger.warning(f"No CSV files found in {input_dir}")
        return {}

    logger.info(f"Batch mode: found {len(csv_files)} CSV files in {input_dir}")

    if settings is None:
        settings = load_settings()

    if classifier is None:
        logger.info("Initializing warm TransactionClassifier for batch mode")
        classifier = TransactionClassifier(settings=settings)

    results = {}
    for csv_file in csv_files:
        try:
            logger.info(f"\n{'='*60}")
            features = process_single_csv(
                str(csv_file),
                settings=settings,
                output_dir=output_dir,
                classifier=classifier,
            )
            bank = features.get("bank_name", csv_file.stem)
            results[bank] = features
        except Exception as e:
            logger.error(f"Failed to process {csv_file.name}: {e}", exc_info=True)

    logger.info(f"\nBatch complete: {len(results)}/{len(csv_files)} files processed")
    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Bank Statement Feature Extraction Pipeline"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        help="Path to a single standardized CSV file",
    )
    parser.add_argument(
        "--input-dir", "-d",
        type=str,
        help="Directory containing multiple extracted CSVs (batch mode)",
    )
    parser.add_argument(
        "--bank", "-b",
        type=str,
        default=None,
        help="Bank name override (auto-detected from filename if not specified)",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to settings.yaml config file",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Output directory for features (default: <input>/../outputs/)",
    )
    parser.add_argument(
        "--account-holder",
        type=str,
        default=None,
        help="Account holder name, used to identify transfers between their own accounts",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.input and not args.input_dir:
        parser.error("Either --input or --input-dir is required")

    # Load settings
    settings = load_settings(args.config)

    if args.input:
        process_single_csv(
            args.input,
            bank_name=args.bank,
            settings=settings,
            output_dir=args.output_dir,
            account_holder_name=args.account_holder,
        )
    elif args.input_dir:
        process_directory(
            args.input_dir,
            settings=settings,
            output_dir=args.output_dir,
        )


if __name__ == "__main__":
    main()
