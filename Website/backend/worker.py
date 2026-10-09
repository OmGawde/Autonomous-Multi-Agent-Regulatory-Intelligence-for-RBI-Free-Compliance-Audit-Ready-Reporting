import asyncio
import traceback
import logging
import time
import csv
import json
from pathlib import Path

from core.logger import get_logger
from core.database import get_connection, close_connection
from core import queries
import extractor_adapter

logger = get_logger(__name__)

async def process_loan_application(
    ctx,
    application_id: str,
    file_path: str = None,
    bank_name: str = None,
    pdf_type: str = "digital",
    column_x_positions: str = None,
    # Supplied by the upload request when the statement is encrypted. Kept in
    # memory for the life of this job and never written to the DB or the logs.
    pdf_password: str = None,
):
    """Background worker to process a bank statement through the extractor adapter pipeline."""
    logger.info(f"Processing started for Application ID: {application_id}")

    conn = get_connection()
    try:
        # Fetch file_path / bank_name from DB if missing
        if not file_path or not bank_name:
            app_data = queries.get_loan_application(conn, application_id)
            if not app_data:
                logger.error(f"Application {application_id} not found in DB. Skipping.")
                return
            file_path = app_data['file_path']
            if not bank_name:
                bank_name = app_data.get('bank_name', 'Auto-Detect')

        is_multi = False
        paths_list = []
        if isinstance(file_path, str) and file_path.strip().startswith("[") and file_path.strip().endswith("]"):
            try:
                paths_list = [Path(p) for p in json.loads(file_path)]
                is_multi = True
            except Exception:
                paths_list = [Path(file_path)]
        elif isinstance(file_path, str) and ";" in file_path:
            paths_list = [Path(p.strip()) for p in file_path.split(";") if p.strip()]
            is_multi = True
        else:
            paths_list = [Path(file_path)]

        path_obj = paths_list[0]

        # -----------------------------------------------------------------------
        # Step 1: Detect Bank Name
        # -----------------------------------------------------------------------
        queries.update_application_status(conn, application_id, "detecting")
        logger.info(f"Status updated to 'detecting' for {application_id}")
        await asyncio.sleep(0.1)

        if not bank_name or bank_name.lower() in ("auto-detect", "auto", "other", "unknown"):
            detected_bank = await asyncio.to_thread(extractor_adapter.detect_bank_name, path_obj, pdf_password)
            if detected_bank and detected_bank != "Other":
                bank_name = detected_bank
                queries.update_bank_name(conn, application_id, bank_name)
                logger.info(f"Auto-detected bank '{bank_name}' for application {application_id}")
            await asyncio.sleep(0.1)

        # Read the account holder off the statement itself.
        holder_info = await asyncio.to_thread(extractor_adapter.extract_account_holder, path_obj, pdf_password)
        account_holder = (holder_info or {}).get("account_holder")
        if account_holder:
            queries.update_applicant_name(conn, application_id, account_holder)
            logger.info(
                f"Read account holder '{account_holder}' from the statement "
                f"for application {application_id}"
            )
        else:
            queries.update_applicant_name(conn, application_id, "Not stated in statement")
            logger.info(
                f"No account holder name present in the statement for {application_id}; "
                f"self-transfer detection will be skipped"
            )

        # -----------------------------------------------------------------------
        # Step 2: Extract Transactions Table
        # -----------------------------------------------------------------------
        queries.update_application_status(conn, application_id, "extracting")
        logger.info(f"Status updated to 'extracting' for {application_id}")
        await asyncio.sleep(0.1)

        start_time = time.perf_counter()
        if is_multi:
            df = await asyncio.to_thread(extractor_adapter.extract_multiple_statements, paths_list, bank_name, pdf_password)
        else:
            df = await asyncio.to_thread(extractor_adapter.extract_statement, path_obj, bank_name, pdf_password)
        # Read straight off the frame: pandas does not reliably carry .attrs
        # through subsequent operations, so this has to happen before anything
        # touches the DataFrame.
        extraction_diagnostics = dict(getattr(df, "attrs", {}).get("extraction_diagnostics") or {})
        if extraction_diagnostics.get("template_fallback"):
            logger.warning(
                f"Application {application_id} was parsed with the generic 'Other' "
                f"template (requested bank: {extraction_diagnostics.get('requested_bank')}). "
                f"Column mapping is unverified."
            )
        extraction_time = time.perf_counter() - start_time
        logger.info(f"Extraction completed for {application_id} in {extraction_time:.2f}s, extracted {len(df)} rows")

        # Read what the statement prints about itself -- opening and closing
        # balances, totals, a serial column, the period. These are the only
        # reference values in the whole bundle that do not come from our own
        # extraction, which is what makes them able to catch a statement that
        # parsed cleanly but wrongly.
        statement_anchors = await asyncio.to_thread(
            extractor_adapter.read_statement_anchors, path_obj, pdf_password
        )
        if statement_anchors is not None:
            extraction_diagnostics["_anchors"] = statement_anchors
        await asyncio.sleep(0.1)

        if df.empty:
            logger.warning(f"No transactions extracted from {file_path}")
            # None, not 0.0. Storing "we could not determine this" as zero reads
            # on screen as a borrower with no income and no debt, and drags the
            # dashboard's average confidence down with a fabricated number.
            if extraction_diagnostics.get("template_fallback"):
                why = (
                    f"No transactions could be read. '{bank_name}' has no template, so the "
                    f"generic layout was used. Calibrate this bank to add one."
                )
            else:
                why = f"No transactions extracted using the '{bank_name}' template."
            serializable_stats = {k: v for k, v in extraction_diagnostics.items() if not k.startswith('_')}
            failed_result = {
                "decision": "failed",
                "confidence_score": None,
                "reasoning": why,
                "average_monthly_balance": None,
                "total_income": None,
                "total_expenses": None,
                "debt_to_income_ratio": None,
                "monthly_obligations": None,
                "metadata": {"extraction_stats": serializable_stats}
            }
            try:
                queries.create_loan_result(conn, application_id, failed_result)
            except Exception as db_err:
                logger.error(f"Error saving failed loan result: {db_err}")

            queries.update_application_status(conn, application_id, "failed")
            return

        # -----------------------------------------------------------------------
        # Step 3: Run Feature Analysis & Compute Scorecard
        # -----------------------------------------------------------------------
        queries.update_application_status(conn, application_id, "scoring")
        logger.info(f"Status updated to 'scoring' for {application_id}")
        await asyncio.sleep(0.1)

        tx_records = extractor_adapter.format_transactions_for_db(df)

        # Save extracted transactions to CSV files for quick viewer & download
        safe_bank = (bank_name or "UNKNOWN").replace(" ", "_").upper()
        backend_dir = Path(__file__).parent.resolve()
        tx_dir = backend_dir.parent / "extracted_transactions"
        tx_dir.mkdir(parents=True, exist_ok=True)
        tx_csv_path = tx_dir / f"{safe_bank}_{application_id[:8]}_transactions.csv"

        current_tx_dir = backend_dir.parent / "current_extracted_transactions"
        current_tx_dir.mkdir(parents=True, exist_ok=True)
        current_csv_path = current_tx_dir / "current_transactions.csv"

        try:
            fieldnames = ['date', 'description', 'debit', 'credit', 'balance']
            with open(tx_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(tx_records)

            with open(current_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(tx_records)
            logger.info(f"Saved extracted transactions CSV to {tx_csv_path}")
        except Exception as csv_err:
            logger.warning(f"Could not save transactions CSV: {csv_err}")

        # Insert transactions into Database
        try:
            queries.insert_transactions(conn, application_id, tx_records)
            logger.info(f"Inserted {len(tx_records)} transaction records to DB for {application_id}")
        except Exception as db_tx_err:
            logger.error(f"Database insertion failed for transactions: {db_tx_err}")

        # Feature Analysis Pipeline execution.
        # The account holder read off the statement above lets the pipeline tell
        # transfers between the applicant's own accounts apart from real income,
        # and lets an applicant-scoped counterparty label beat a global one.
        features = await asyncio.to_thread(
            extractor_adapter.run_feature_analysis, df, bank_name, str(tx_csv_path),
            account_holder, str(application_id), extraction_diagnostics,
        )

        # Build final scorecard loan result
        loan_result = extractor_adapter.compute_loan_result(df, features)
        try:
            queries.create_loan_result(conn, application_id, loan_result)
            logger.info(f"Saved loan result for {application_id}")
        except Exception as res_err:
            logger.error(f"Error saving loan result to DB: {res_err}")

        # The status must follow the result. Scoring that did not complete is
        # not a success, however many rows were extracted.
        if loan_result.get("decision") in ("analysis_incomplete", "extraction_unverified"):
            queries.update_application_status(conn, application_id, loan_result["decision"])
            logger.error(
                f"Application {application_id}: no decision issued -- "
                f"{loan_result.get('reasoning')}"
            )
        else:
            queries.update_application_status(conn, application_id, "success")
            logger.info(f"Pipeline finished successfully for Application ID: {application_id}")

    except Exception as e:
        logger.error(f"Error in process_loan_application: {e}\n{traceback.format_exc()}")
        # Persist a result row as well as the status. Without one, GET /result
        # raises 202 "Result not ready yet." forever, so a permanently failed
        # application reports as still processing.
        try:
            queries.create_loan_result(conn, application_id, {
                "decision": "failed",
                "confidence_score": None,
                "reasoning": f"Processing failed: {e}",
                "average_monthly_balance": None,
                "total_income": None,
                "total_expenses": None,
                "debt_to_income_ratio": None,
                "monthly_obligations": None,
                "metadata": {},
            })
        except Exception as res_err:
            logger.error(f"Could not persist failure result: {res_err}")
        try:
            queries.update_application_status(conn, application_id, "failed")
        except Exception:
            pass
    finally:
        close_connection(conn)
