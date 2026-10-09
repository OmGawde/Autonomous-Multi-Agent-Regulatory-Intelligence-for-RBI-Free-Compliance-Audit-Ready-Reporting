import os
import sys

# Configure environment before any ML/PyTorch/Transformers imports
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

import re
import uuid
import json
import asyncio
import aiofiles
import traceback
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from arq import create_pool
from arq.connections import RedisSettings

from core.logger import get_logger
from core.config import settings
from core.database import get_connection, init_db, close_connection, get_cursor
from core import queries
from core.cache import cache
from services.template_service import TemplateService
import extractor_adapter
from worker import process_loan_application
from models.schemas import (
    BanksListResponse, 
    StatusResponse, 
    LoanResultResponse, 
    ApplicationResponse,
    ApplicationsListResponse,
    TransactionsResponse,
    CopilotQueryRequest,
    CopilotQueryResponse
)

logger = get_logger(__name__)

# Initialize Services
template_service = TemplateService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown."""
    try:
        logger.info("Initializing database...")
        init_db()
        
        # Initialize ARQ Redis Pool if explicitly enabled
        app.state.redis = None
        if getattr(settings, "ENABLE_REDIS", False) and settings.REDIS_URL:
            try:
                parsed = urlparse(settings.REDIS_URL)
                use_ssl = parsed.scheme == "rediss"
                redis_settings = RedisSettings(
                    host=parsed.hostname,
                    port=parsed.port or (6380 if use_ssl else 6379),
                    password=parsed.password or None,
                    username=parsed.username or None,
                    ssl=use_ssl,
                    conn_timeout=2.0
                )
                app.state.redis = await create_pool(redis_settings)
                logger.info("Connected to Redis successfully.")
            except Exception as redis_err:
                logger.warning(f"Could not connect to Redis: {redis_err}. Background worker will run inline synchronously.")
                app.state.redis = None
        else:
            logger.info("Redis is disabled. Pipeline running in native inline async mode.")
        
        logger.info("Syncing bank registry image hashes...")
        sync_all_bank_hashes()
        
        logger.info("Server is ready and services are initialized.")
        yield
    finally:
        if hasattr(app.state, "redis") and app.state.redis:
            await app.state.redis.aclose()
        logger.info("Shutting down...")

app = FastAPI(title="Loan Approval System API", lifespan=lifespan)

# CORS Middleware
# allow_origins=["*"] together with allow_credentials=True makes Starlette
# reflect whatever Origin the caller sends and permit cookies with it -- i.e.
# "any site may make credentialed calls to this API". Harmless only while
# nothing here authenticates; a CSRF/exfiltration route the moment auth lands.
# Origins are configurable so a deployment can name its real front-end host.
_configured_origins = getattr(settings, "CORS_ALLOW_ORIGINS", "") or ""
_explicit_origins = [o.strip() for o in _configured_origins.split(",") if o.strip()]

if _explicit_origins:
    # A deployment has named its real front-end host(s). Honour exactly those.
    ALLOWED_ORIGINS = _explicit_origins
    ALLOWED_ORIGIN_REGEX = None
else:
    # Local development. Vite does not hold port 5173: if something else has it,
    # it moves to 5174, then 5175, without complaining. Pinning the dev
    # allowlist to 5173 meant the browser's requests were rejected while the
    # server still logged them as "200 OK" -- so the dashboard rendered as empty
    # (both fetches fall into a catch that only console.errors) and the backend
    # log looked perfectly healthy. Accept loopback on any port instead; this
    # stays off the network, so it does not widen exposure beyond this machine.
    ALLOWED_ORIGINS = []
    ALLOWED_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve paths relative to main.py
BASE_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = BASE_DIR.parent / "frontend" / "dist" if (BASE_DIR.parent / "frontend").exists() else BASE_DIR.parent / "Frontend" / "dist"

# Mount Static Files (Vite bundles compiled assets to dist/assets)
if (FRONTEND_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

@app.get("/")
async def read_index():
    """Serves the front-end SPA index page."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {
        "status": "development_mode",
        "message": "Frontend build not found. Please run the React dev server using 'npm run dev' or build the bundle using 'npm run build'."
    }

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# STANDARD ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/banks", response_model=BanksListResponse)
async def get_banks():
    """Returns a list of all supported bank names."""
    logger.info("Request: GET /banks")
    banks = template_service.get_all_bank_names()
    return {"banks": banks}

# Roles the extractor understands. A calibrated column must map to one of
# these or it is dropped during normalisation.
_CALIBRATION_ROLES = {"date", "description", "debit", "credit", "balance",
                      "cheque", "value_date", "serial", "time", "timing", "timestamp", "time_stamp", "ignore"}


def _calibration_from_request(request: dict):
    """
    Turn the calibrator's drawn column ranges into what the extractor needs.

    The UI collects `[{label, role, x0, x1}, ...]` as fractions of page width.
    `find_tables(vertical_strategy="explicit")` wants BOUNDARIES, and yields
    exactly len(boundaries)-1 columns in left-to-right order -- which is what
    lets the extractor's existing index->role positional mapping consume them
    with no new mechanism.
    """
    columns = request.get("columns") or []
    if not columns:
        raise HTTPException(status_code=400, detail="At least one column must be marked.")

    ordered = sorted(columns, key=lambda c: float(c.get("x0", 0)))
    roles = []
    for col in ordered:
        role = str(col.get("role") or col.get("label") or "").strip().lower().replace(" ", "_")
        if role not in _CALIBRATION_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown column role '{role}'. Use one of: {sorted(_CALIBRATION_ROLES)}",
            )
        roles.append(role)

    for required in ("date", "balance"):
        if required not in roles:
            raise HTTPException(
                status_code=400,
                detail=f"A '{required}' column is required -- without it the statement cannot be parsed.",
            )
    if "debit" not in roles and "credit" not in roles:
        raise HTTPException(status_code=400, detail="Mark at least one of 'debit' or 'credit'.")

    # Boundaries: exactly len(ordered) + 1 boundaries for len(ordered) columns.
    # The boundary between column i and column i+1 is placed at their midpoint
    # so that any gap between drawn boxes does not create phantom columns.
    edges = [float(ordered[0]["x0"])]
    for i in range(len(ordered) - 1):
        mid = (float(ordered[i]["x1"]) + float(ordered[i + 1]["x0"])) / 2.0
        edges.append(round(mid, 4))
    edges.append(float(ordered[-1]["x1"]))
    return edges, roles


@app.post("/banks/save-template")
async def save_bank_template(request: dict):
    """Persist a calibrated template so an unsupported bank becomes parseable."""
    bank_name = (request.get("bank_name") or "").strip()
    if not bank_name:
        raise HTTPException(status_code=400, detail="bank_name is required.")

    edges, roles = _calibration_from_request(request)
    try:
        template_service.save_bank_template(
            bank_name,
            vertical_lines_norm=edges,
            date_format=request.get("date_format") or None,
            column_roles=roles,
            table_region_norm=request.get("table_region") or None,
            ifsc_prefix=request.get("ifsc_prefix") or None,
            detect_markers=request.get("detect_markers") or None,
        )
        cache.clear()
        extractor_adapter.reload_extractor_templates()
        logger.info(
            f"Saved calibrated template '{bank_name}': {len(edges)} boundaries, roles={roles}"
        )
        return {"success": True, "bank_name": bank_name,
                "boundaries": len(edges), "roles": roles}
    except Exception as e:
        logger.error(f"Error saving bank template: {e}")
        raise HTTPException(status_code=500, detail=f"Could not save template: {str(e)}")


@app.post("/api/calibration/preview")
async def preview_calibration(request: dict):
    """
    Parse a statement using the calibration currently being edited, and report
    whether the result agrees with the figures printed on the statement.

    This is the point of the calibrator: rather than asking someone to eyeball
    300 rows, tell them "total debits 7,74,966 -- matches the statement" or
    "expected 358 rows, got 344". The previous preview endpoint ran generic
    auto-detection and ignored the drawn columns entirely, so it could never
    show the effect of a change.
    """
    pdf_name = request.get("pdf")
    if not pdf_name:
        raise HTTPException(status_code=400, detail="pdf is required.")
    pdf_path = find_pdf_path(pdf_name)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")

    edges, roles = _calibration_from_request(request)
    password = request.get("password") or None

    def _run():
        import pandas as pd
        from extractor import StandalonePDFExtractor

        extractor = StandalonePDFExtractor()
        provisional = "__calibration_preview__"
        extractor.templates[provisional] = {
            "vertical_lines_norm": edges,
            "table_region_norm": request.get("table_region") or None,
            "column_positions": {
                "expected_cols": len(roles),
                "mapping": {str(i): r for i, r in enumerate(roles) if r not in ("ignore", "serial")},
            },
            "date_format": request.get("date_format") or None,
            "columns": {},
            "calibrated": True,
        }
        raw = extractor.extract_with_template(Path(pdf_path), provisional, password)
        diagnostics = raw.attrs.get("extraction_diagnostics", {})

        renamed = raw.rename(columns={
            "Date": "date", "Description": "description", "Withdrawal Amt.": "debit",
            "Deposit Amt.": "credit", "Closing Balance": "balance"})

        fidelity = {}
        stats = {}
        if not renamed.empty:
            from src.utils.validation import validate_and_clean
            from src.utils.anchors import extract_anchors
            from src.utils import extraction_fidelity as ef
            try:
                cleaned, stats = validate_and_clean(renamed, "Other")
                fidelity = ef.check(cleaned, extract_anchors(Path(pdf_path), password),
                                    {**stats, **diagnostics})
                renamed = cleaned
            except Exception as e:
                fidelity = {"status": "UNVERIFIED", "checks": [], "failed_count": 0,
                            "reason": f"could not verify: {e}"}

        preview = renamed.head(60).where(pd.notnull(renamed.head(60)), None)
        return {
            "rows": preview.to_dict(orient="records"),
            "row_count": len(renamed),
            "columns": [r for r in roles if r not in ("ignore", "serial")],
            "diagnostics": diagnostics,
            "extraction_stats": stats,
            "fidelity": fidelity,
        }

    try:
        return await asyncio.to_thread(_run)
    except HTTPException:
        raise
    except Exception as e:
        from extractor import PdfPasswordError

        if isinstance(e, PdfPasswordError):
            raise HTTPException(status_code=422, detail={
                "status": "password_incorrect" if e.password_supplied else "password_required",
                "message": str(e)})
        logger.error(f"Calibration preview failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")


@app.delete("/banks/calibrated/{bank_name}")
async def delete_calibrated_template(bank_name: str):
    """Remove a calibrated template. Built-in templates are protected."""
    try:
        removed = template_service.delete_bank_template(bank_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail=f"No template named '{bank_name}'.")
    cache.clear()
    extractor_adapter.reload_extractor_templates()
    return {"success": True, "bank_name": bank_name}

@app.post("/upload", response_model=StatusResponse)
async def upload_statement(
    file: UploadFile = File(...),
    bank_name: str = Form("Auto-Detect"),
    # Optional. The account holder is read off the statement during processing
    # -- every bank prints it somewhere -- so callers are not asked to supply it.
    applicant_name: str = Form("Reading from statement..."),
    pdf_type: str = Form("digital"),
    custom_bank_name: str = Form(None),
    column_x_positions: str = Form(None),
    # Held for the duration of this request only: used to unlock the PDF, passed
    # to the job in memory, and never written to the database or the logs.
    pdf_password: str = Form(None),
):
    """Uploads a bank statement and initiates the processing pipeline."""
    effective_bank_name = custom_bank_name.strip() if custom_bank_name and custom_bank_name.strip() else bank_name
    logger.info(f"Request: POST /upload - Bank: {effective_bank_name}")

    if not file.filename.lower().endswith(".pdf") and file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    file_id = str(uuid.uuid4())
    file_extension = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{file_extension}"
    file_path = os.path.join(settings.UPLOAD_DIR, filename)

    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)

        logger.info(f"File saved: {file_path}")

        # Can we actually read this file? This is the last synchronous moment --
        # everything below is fire-and-forget via asyncio.create_task, so a
        # problem found later can only surface as a failed job several seconds
        # after the user has been told the upload succeeded. An encrypted
        # statement used to do exactly that, and reported itself as an unknown
        # bank template.
        probe = await asyncio.to_thread(
            extractor_adapter.probe_pdf, Path(file_path), pdf_password
        )
        if probe.get("encrypted") and not probe.get("unlocked"):
            os.remove(file_path)
            status = "password_incorrect" if pdf_password else "password_required"
            logger.info(f"Upload rejected: {status} for {file.filename}")
            # 422, and no DB row and no job: a locked file is not an application.
            raise HTTPException(
                status_code=422,
                detail={
                    "status": status,
                    "message": (
                        "This statement is password-protected. Enter the password to continue."
                        if status == "password_required"
                        else "That password did not open the statement. Please try again."
                    ),
                },
            )
        if probe.get("pages") and not probe.get("has_text_layer"):
            os.remove(file_path)
            logger.info(f"Upload rejected: no text layer in {file.filename}")
            raise HTTPException(
                status_code=422,
                detail={
                    "status": "no_text_layer",
                    "message": (
                        "This PDF has no selectable text -- it looks like a scan or "
                        "photograph. Please upload the digital statement issued by "
                        "your bank."
                    ),
                },
            )

        # Save to Database
        conn = get_connection()
        try:
            application = queries.create_loan_application(
                conn, 
                applicant_name=applicant_name, 
                bank_name=effective_bank_name, 
                file_path=file_path
            )
            application_id = application['id']
            
            # Run inline asynchronously for immediate execution
            asyncio.create_task(
                process_loan_application(
                    ctx=None,
                    application_id=str(application_id),
                    file_path=file_path,
                    bank_name=effective_bank_name,
                    pdf_type=pdf_type,
                    column_x_positions=column_x_positions,
                    # In memory, for this job only -- never persisted.
                    pdf_password=pdf_password,
                )
            )
            logger.info(f"Job spawned inline for Application ID: {application_id}")
            
            cache.clear()
            return {
                "application_id": str(application_id),
                "status": "pending",
                "message": "File uploaded successfully. Analysis started."
            }
        finally:
            close_connection(conn)
    except HTTPException:
        # A deliberate response -- "this statement needs a password", "this PDF
        # has no text layer". Flattening it into a generic 500 is what made an
        # encrypted upload look like a server fault instead of a prompt.
        raise
    except Exception as e:
        logger.error(f"Error in upload_statement: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An error occurred during file upload.")


@app.post("/upload-multiple", response_model=StatusResponse)
async def upload_multiple_statements(
    files: list[UploadFile] = File(...),
    bank_name: str = Form("Auto-Detect"),
    applicant_name: str = Form("Reading from statement..."),
    pdf_type: str = Form("digital"),
    custom_bank_name: str = Form(None),
    pdf_password: str = Form(None),
):
    """Uploads multiple bank statement PDFs for chronological merging and analysis."""
    effective_bank_name = custom_bank_name.strip() if custom_bank_name and custom_bank_name.strip() else bank_name
    logger.info(f"Request: POST /upload-multiple - {len(files)} files - Bank: {effective_bank_name}")

    if not files:
        raise HTTPException(status_code=400, detail="At least one PDF file must be provided.")

    saved_paths = []
    try:
        for file in files:
            if not file.filename.lower().endswith(".pdf") and file.content_type != "application/pdf":
                raise HTTPException(status_code=400, detail=f"File {file.filename} is not a PDF.")

            file_id = str(uuid.uuid4())
            file_extension = os.path.splitext(file.filename)[1]
            filename = f"{file_id}{file_extension}"
            file_path = os.path.join(settings.UPLOAD_DIR, filename)

            async with aiofiles.open(file_path, 'wb') as out_file:
                content = await file.read()
                await out_file.write(content)
            saved_paths.append(file_path)

        # Probe the first file for validity/passwords
        probe = await asyncio.to_thread(extractor_adapter.probe_pdf, Path(saved_paths[0]), pdf_password)
        if probe.get("encrypted") and not probe.get("unlocked"):
            for p in saved_paths:
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
            status = "password_incorrect" if pdf_password else "password_required"
            raise HTTPException(
                status_code=422,
                detail={
                    "status": status,
                    "message": "One or more statements are password-protected. Please enter password.",
                },
            )

        paths_payload = json.dumps(saved_paths)
        conn = get_connection()
        try:
            application = queries.create_loan_application(
                conn,
                applicant_name=applicant_name,
                bank_name=effective_bank_name,
                file_path=paths_payload
            )
            application_id = application['id']

            asyncio.create_task(
                process_loan_application(
                    ctx=None,
                    application_id=str(application_id),
                    file_path=paths_payload,
                    bank_name=effective_bank_name,
                    pdf_type=pdf_type,
                    pdf_password=pdf_password,
                )
            )
            logger.info(f"Job spawned inline for Multi-Statement Application ID: {application_id}")
            cache.clear()
            return {
                "application_id": str(application_id),
                "status": "pending",
                "message": f"Successfully uploaded {len(files)} statements. Merging and analysis started."
            }
        finally:
            close_connection(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload_multiple_statements: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An error occurred during multi-file upload.")

@app.get("/status/{application_id}", response_model=StatusResponse)
async def get_status(application_id: str):
    """Retrieves the current status and real-time progress of a loan application."""
    conn = get_connection()
    try:
        application = queries.get_loan_application(conn, application_id)
        if not application:
            raise HTTPException(status_code=404, detail="Application not found.")
        
        status_val = application['status']
        progress = 10
        stage_msg = "Initializing statement processing pipeline..."
        
        if status_val == "pending":
            progress = 15
            stage_msg = "File received. Queueing processing agent..."
        elif status_val == "detecting":
            progress = 35
            stage_msg = "Auto-detecting bank template & extracting account holder name..."
        elif status_val == "extracting":
            progress = 65
            stage_msg = "Extracting transaction table rows from PDF pages..."
        elif status_val == "scoring":
            progress = 88
            stage_msg = "Validating transactions & calculating monthly balance metrics..."
        elif status_val == "processing":
            progress = 50
            stage_msg = "Executing pipeline agents..."
        elif status_val == "success":
            progress = 100
            stage_msg = "Statement analysis & extraction complete!"
        elif status_val in ("extraction_unverified", "analysis_incomplete"):
            progress = 100
            stage_msg = "Statement analysis complete with verification warnings."
        elif status_val == "failed":
            progress = 0
            stage_msg = "Processing failed."

        return {
            "application_id": str(application['id']),
            "status": status_val,
            "message": stage_msg,
            "progress": progress,
            "applicant_name": application.get('applicant_name'),
            "bank_name": application.get('bank_name')
        }
    finally:
        close_connection(conn)

@app.get("/result/{application_id}", response_model=LoanResultResponse)
async def get_result(application_id: str):
    """Retrieves the final loan result for a given application."""
    conn = get_connection()
    try:
        result = queries.get_loan_result(conn, application_id)
        if not result:
            app_record = queries.get_loan_application(conn, application_id)
            if not app_record:
                raise HTTPException(status_code=404, detail="Application not found.")
            raise HTTPException(status_code=202, detail="Result not ready yet.")
        
        # Ensure correct type for application_id
        result['application_id'] = str(result['application_id'])

        # bank_name lives on loan_applications, not loan_results, so the
        # Scorecard's "Bank Name" row rendered blank. Attach it here.
        app_record = queries.get_loan_application(conn, application_id)
        if app_record:
            result['bank_name'] = app_record.get('bank_name')

        meta = result.get('metadata')
        if isinstance(meta, str):
            try:
                import json as _json
                meta = _json.loads(meta)
            except Exception:
                meta = {}
        if isinstance(meta, dict):
            result['loan_eligibility'] = meta.get('loan_eligibility')
            result['audit_verification'] = meta.get('audit_verification')
            if not result.get('loan_eligibility'):
                try:
                    from src.engines.loan_eligibility_agent import calculate_loan_eligibility
                    result['loan_eligibility'] = calculate_loan_eligibility(meta)
                except Exception:
                    pass

        return result
    finally:
        close_connection(conn)


@app.get("/applications", response_model=ApplicationsListResponse)
async def get_applications():
    """Retrieves all loan applications."""
    cache_key = "applications:all"
    cached = cache.get(cache_key)
    if cached:
        return {"applications": cached}

    conn = get_connection()
    try:
        apps_list = queries.get_all_applications(conn)
        for a in apps_list:
            a['id'] = str(a['id'])
        cache.set(cache_key, apps_list, ttl=60)
        return {"applications": apps_list}
    finally:
        close_connection(conn)

@app.post("/applications/clear")
async def clear_applications():
    """Clears all loan applications."""
    cache.clear()
    conn = get_connection()
    try:
        with get_cursor(conn) as cursor:
            from core.database import IS_SQLITE
            if IS_SQLITE:
                cursor.execute("DELETE FROM loan_results;")
                cursor.execute("DELETE FROM transaction_records;")
                cursor.execute("DELETE FROM loan_applications;")
            else:
                cursor.execute("TRUNCATE TABLE loan_results, transaction_records, loan_applications CASCADE;")
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error truncating tables: {e}")
        raise HTTPException(status_code=500, detail="Database clear failed.")
    finally:
        close_connection(conn)
        
    try:
        if app.state.redis:
            await app.state.redis.flushdb()
    except Exception as cache_err:
        logger.warning(f"Error flushing Redis queue: {cache_err}")
        
    return {"success": True, "message": "All database records cleared."}

_CLASSIFICATION_FIELDS = (
    "category", "subcategory", "needs_wants", "counterparty_key",
    "classification_method", "recurrence_type", "suggestion_reason",
)


def _merge_classification(tx_list: list, bank_name: str) -> list:
    """
    Attach the pipeline's labels to the stored transaction rows.

    `transaction_records` holds only date/description/amounts -- the category,
    counterparty and needs/wants live in the pipeline's classified CSV. Without
    this merge the transactions table has no label to display and no
    counterparty for the operator to tag.

    Matched on (date, description, amount); a row we cannot match simply keeps
    its unlabelled form rather than borrowing a neighbour's label.
    """
    if not tx_list or not bank_name:
        return tx_list

    path = FEATURES_OUTPUT_DIR / f"{bank_name.replace(' ', '_')}_classified.csv"
    if not path.exists():
        return tx_list

    try:
        import csv as csv_mod
        lookup = {}
        with open(path, "r", encoding="utf-8") as fh:
            for row in csv_mod.DictReader(fh):
                key = (
                    str(row.get("date", ""))[:10],
                    str(row.get("description", "")).strip()[:80],
                    round(float(row.get("debit") or 0), 2),
                    round(float(row.get("credit") or 0), 2),
                )
                lookup[key] = row
    except Exception as e:
        logger.warning(f"Could not read classified output for {bank_name}: {e}")
        return tx_list

    matched = 0
    for tx in tx_list:
        key = (
            str(tx.get("date", ""))[:10],
            str(tx.get("description", "")).strip()[:80],
            round(float(tx.get("debit") or 0), 2),
            round(float(tx.get("credit") or 0), 2),
        )
        row = lookup.get(key)
        if not row:
            continue
        matched += 1
        for field in _CLASSIFICATION_FIELDS:
            value = row.get(field)
            if value not in (None, "", "nan"):
                tx[field] = value

    logger.info(f"Merged classification onto {matched}/{len(tx_list)} transactions")
    return tx_list


@app.get("/applications/{application_id}/transactions", response_model=TransactionsResponse)
async def get_application_transactions(application_id: str):
    """Retrieves all parsed transaction records for an application."""
    cache_key = f"transactions:{application_id}"
    cached_memory = cache.get(cache_key)
    if cached_memory:
        return {"transactions": cached_memory}

    try:
        import json
        if app.state.redis:
            cached_data = await app.state.redis.get(cache_key)
            if cached_data:
                parsed = json.loads(cached_data)
                cache.set(cache_key, parsed, ttl=300)
                return {"transactions": parsed}
    except Exception as cache_err:
        logger.warning(f"Cache lookup failed: {cache_err}")

    conn = get_connection()
    try:
        tx_list = queries.get_transactions(conn, application_id)
        app_record = queries.get_loan_application(conn, application_id)
        tx_list = _merge_classification(tx_list, (app_record or {}).get("bank_name"))
        cache.set(cache_key, tx_list, ttl=300)
        try:
            import json
            if app.state.redis:
                await app.state.redis.setex(cache_key, 86400 * 7, json.dumps(tx_list, default=str))
        except:
            pass
        return {"transactions": tx_list}
    finally:
        close_connection(conn)


# ══════════════════════════════════════════════════════════════════════════════
# UNDERWRITING COPILOT (BHARATGEN PARAM-FINANCE)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/copilot/query", response_model=CopilotQueryResponse)
async def query_copilot(req: CopilotQueryRequest):
    """
    Interrogate bank statement transactions via BharatGen Param-Finance Underwriting Copilot.
    Strictly enforces the 5 Institutional BFSI Guardrails:
      1. Grounded Citation Mandate: Line-item evidence [Ref: Date | Narration | Amount].
      2. Indirect Prompt Injection Defense: Transactions isolated inside <verified_statement_data>.
      3. Deterministic Numeric Lock: Financial totals/ratios pulled strictly from verified scorecard.
      4. Scope & Advisory Containment: Refuses legal advice and unauthorized credit decisions.
      5. PII Masking: Redacts account and phone numbers.
    """
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    conn = get_connection()
    try:
        app_record = queries.get_loan_application(conn, req.application_id)
        if not app_record:
            raise HTTPException(status_code=404, detail="Application not found.")

        loan_result = queries.get_loan_result(conn, req.application_id) or {}
        tx_list = queries.get_transactions(conn, req.application_id)
        tx_list = _merge_classification(tx_list, (app_record or {}).get("bank_name"))

        # Guardrail 3 (Deterministic Numeric Lock) is only as good as what it is
        # handed. `loan_result` is the flat DB row -- it carries no
        # `true_turnover`, `inward_bounces` or `risk_band` column at all, and
        # its `confidence_score` is classification coverage on a 0-1 scale, not
        # a 0-1000 credit score. Reading them off the row made the Copilot state
        # "True Deflated Turnover: Rs 0.00", quote the DTI as the FOIR, and call
        # the pipeline status ("success") a risk band -- all under the heading
        # "Verified Deterministic Metrics". Those figures live in the feature
        # bundle stored in `metadata`.
        meta = loan_result.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (ValueError, TypeError):
                meta = {}
        meta = meta or {}
        summary = meta.get("underwriting_summary") or {}
        balance_f = meta.get("balance") or {}

        def _first(*candidates):
            """First candidate that is a real number, else None."""
            for c in candidates:
                if isinstance(c, bool) or c is None:
                    continue
                if isinstance(c, (int, float)):
                    return c
            return None

        scorecard = {
            "true_turnover": _first(
                summary.get("true_turnover"),
                (meta.get("cash_flow") or {}).get("net_turnover_credit"),
            ) or 0.0,
            # The debt engine's FOIR, not the debt-to-income ratio. They are
            # different numbers over different bases (0.378 vs 0.640 here) and
            # the scorecard on screen already shows the former.
            "foir": _first(
                summary.get("foir_score"),
                (meta.get("debt") or {}).get("foir"),
            ) or 0.0,
            "adb": _first(
                balance_f.get("average_daily_balance"),
                loan_result.get("average_monthly_balance"),
            ) or 0.0,
            "inward_bounces": int(
                _first(
                    summary.get("inward_bounce_count"),
                    (meta.get("fraud") or {}).get("inward_bounce_count"),
                ) or 0
            ),
            "credit_score": _first(summary.get("credit_score")) or 0,
            "risk_band": summary.get("risk_band") or "NOT_ASSESSED",
        }

        try:
            from src.model.param_adapter import ParamAdapter
            adapter = ParamAdapter.get_instance()
            result = adapter.query_underwriting_copilot(
                question=req.question,
                context_txns=tx_list,
                scorecard=scorecard,
            )
            return result
        except Exception as e:
            logger.error(f"Error querying Param Underwriting Copilot: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Copilot inference error: {str(e)}")
    finally:
        close_connection(conn)

# ══════════════════════════════════════════════════════════════════════════════
# COUNTERPARTY OVERRIDE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════
#
# Some purposes are simply not written in the statement. A Rs 1,300 monthly NEFT
# to a co-operative bank is housing-society maintenance, and no parser will ever
# say so -- ICICI truncated the payee at 10 characters before the PDF was
# written. These endpoints let a human name a counterparty once; the label then
# applies to every statement that counterparty appears in.

def _counterparty_registry():
    """The registry shared with the Feature Extraction pipeline."""
    from src.rules.counterparty import get_registry
    return get_registry()


@app.get("/counterparty-overrides")
async def list_counterparty_overrides():
    """All learned counterparty labels."""
    try:
        entries = _counterparty_registry().all_entries()
        return {"counterparties": entries, "count": len(entries)}
    except Exception as e:
        logger.error(f"Could not read counterparty registry: {e}")
        raise HTTPException(status_code=500, detail="Could not read the counterparty registry.")


@app.post("/counterparty-overrides")
async def set_counterparty_override(request: dict):
    """
    Teach the system what a counterparty is.

    Body: counterparty_key, category, subcategory, and optionally needs_wants,
    scope ("global" | "applicant"), applicant_id, note.
    """
    key = str(request.get("counterparty_key", "")).strip()
    category = str(request.get("category", "")).strip()
    subcategory = str(request.get("subcategory", "")).strip()

    if not key:
        raise HTTPException(status_code=400, detail="counterparty_key is required.")
    if not category or not subcategory:
        raise HTTPException(status_code=400, detail="category and subcategory are required.")

    try:
        entry = _counterparty_registry().set(
            key,
            category=category,
            subcategory=subcategory,
            needs_wants=str(request.get("needs_wants", "Unknown")),
            scope=str(request.get("scope", "global")),
            applicant_id=request.get("applicant_id"),
            note=str(request.get("note", "")),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Could not save counterparty override: {e}")
        raise HTTPException(status_code=500, detail="Could not save the counterparty override.")

    # Cached application and transaction payloads now embed a stale label.
    cache.clear()
    logger.info(f"Counterparty override saved: {key} -> {category}/{subcategory}")
    return {"success": True, "counterparty_key": key, "entry": entry}


@app.delete("/counterparty-overrides")
async def delete_counterparty_override(
    counterparty_key: str = Query(...),
    scope: str = Query("global"),
    applicant_id: str = Query(None),
):
    """Forget a learned counterparty label."""
    try:
        removed = _counterparty_registry().delete(
            counterparty_key, scope=scope, applicant_id=applicant_id
        )
    except Exception as e:
        logger.error(f"Could not delete counterparty override: {e}")
        raise HTTPException(status_code=500, detail="Could not delete the counterparty override.")

    if not removed:
        raise HTTPException(status_code=404, detail="No matching counterparty override.")
    cache.clear()
    return {"success": True, "counterparty_key": counterparty_key}


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE OUTPUT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_feature_outputs_dir() -> Path:
    """
    Locate the directory the Feature Extraction pipeline actually writes to.

    These constants previously pointed at Website/features_output and
    Website/outputs. Neither has ever existed -- the pipeline writes to
    "<project root>/Feature Extraction/outputs" -- so /features/{id} returned
    404 unconditionally and the entire engine bundle was unreachable from the
    web app. Resolved by walking up to the project root, the same way
    extractor_adapter locates extractor.py.
    """
    root = BASE_DIR
    while root != root.parent:
        candidate = root / "Feature Extraction" / "outputs"
        if candidate.exists():
            return candidate
        root = root.parent
    return BASE_DIR.parent / "features_output"


FEATURES_OUTPUT_DIR = _resolve_feature_outputs_dir()
OUTPUTS_DIR = BASE_DIR.parent / "outputs"
logger.info(f"Feature outputs directory resolved to: {FEATURES_OUTPUT_DIR}")

@app.get("/features/{application_id}")
async def get_features(application_id: str):
    """Retrieves feature analysis data from the features_output/ folder for a given application.
    
    Searches for feature CSV/JSON files matching the application's bank name.
    Falls back to outputs/ folder if features_output/ doesn't have a match.
    """
    conn = get_connection()
    try:
        app_record = queries.get_loan_application(conn, application_id)
        if not app_record:
            raise HTTPException(status_code=404, detail="Application not found.")

        bank_name = app_record.get("bank_name", "Unknown")
        safe_bank = bank_name.replace(" ", "_")

        # Prefer the bundle stored against THIS application.
        #
        # The on-disk files are named by bank only, so every applicant at a bank
        # resolves to one shared file and each new run overwrites the previous
        # applicant's features -- one person's analysis could be served for
        # another's application. The database row is per-application and cannot
        # collide, so it is the authoritative source; the file is a fallback for
        # rows processed before the bundle was persisted.
        result_row = queries.get_loan_result(conn, application_id)
    finally:
        close_connection(conn)

    if result_row:
        stored = result_row.get("metadata") or {}
        if isinstance(stored, str):
            try:
                stored = json.loads(stored)
            except Exception:
                stored = {}
        bundle = stored.get("features_summary") or (
            stored if stored.get("income") or stored.get("balance") else None
        )
        if bundle:
            return {
                "application_id": application_id,
                "bank_name": bank_name,
                "source_file": "database:loan_results.metadata",
                "features": bundle,
            }

    # Fallback: the shared per-bank file on disk.
    feature_data = None
    source_file = None

    for search_dir in [FEATURES_OUTPUT_DIR, OUTPUTS_DIR]:
        if not search_dir.exists():
            continue

        # Try JSON first (richer data), then CSV. Match case-insensitively --
        # the pipeline writes "Axis_features.json" while this endpoint used to
        # upper-case the name, which happens to work on Windows and breaks on
        # any case-sensitive filesystem.
        def _find(suffix: str):
            exact = search_dir / f"{safe_bank}_features{suffix}"
            if exact.exists():
                return exact
            target = f"{safe_bank}_features{suffix}".lower()
            for p in search_dir.glob(f"*_features{suffix}"):
                if p.name.lower() == target:
                    return p
            return None

        json_path = _find(".json") or (search_dir / f"{safe_bank}_features.json")
        csv_path = _find(".csv") or (search_dir / f"{safe_bank}_features.csv")

        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    feature_data = json.load(f)
                source_file = str(json_path)
                break
            except Exception as e:
                logger.warning(f"Could not parse feature JSON {json_path}: {e}")
        
        if csv_path.exists():
            try:
                import csv as csv_mod
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv_mod.DictReader(f)
                    rows = list(reader)
                    if rows:
                        # CSV is a single-row flattened dict — convert to key-value pairs
                        feature_data = {
                            "format": "csv_flat",
                            "bank_name": bank_name,
                            "features": rows[0]
                        }
                        source_file = str(csv_path)
                        break
            except Exception as e:
                logger.warning(f"Could not parse feature CSV {csv_path}: {e}")
    
    if feature_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No feature files found for bank '{bank_name}'. "
                   f"Run the decision engine pipeline to generate features in features_output/."
        )
    
    return {
        "application_id": application_id,
        "bank_name": bank_name,
        "source_file": source_file,
        "features": feature_data
    }

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTED TRANSACTION CSV ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

EXTRACTED_TX_DIR = BASE_DIR.parent / "extracted_transactions"

def _find_transaction_csv(bank_name: str, application_id: str) -> Path:
    """Finds the best matching transaction CSV for a given bank + application.
    
    Search order:
      1. {BANK}_{app_id_prefix}_transactions.csv  (exact match with app ID)
      2. {BANK}_transactions.csv                  (bank-only fallback)
      3. Any CSV whose name starts with the bank prefix
    """
    if not EXTRACTED_TX_DIR.exists():
        return None
    
    safe_bank = bank_name.replace(" ", "_").upper()
    app_prefix = application_id[:8]
    
    # 1. Exact match with app ID prefix
    exact_path = EXTRACTED_TX_DIR / f"{safe_bank}_{app_prefix}_transactions.csv"
    if exact_path.exists():
        return exact_path
    
    # 2. Bank-only filename
    bank_path = EXTRACTED_TX_DIR / f"{safe_bank}_transactions.csv"
    if bank_path.exists():
        return bank_path
    
    # 3. Fuzzy: any CSV starting with bank prefix
    for child in sorted(EXTRACTED_TX_DIR.glob(f"{safe_bank}*_transactions.csv")):
        return child
    
    return None


@app.get("/transactions-csv/{application_id}")
async def get_transactions_csv_data(application_id: str):
    """Returns parsed transaction CSV data as JSON for UI rendering.
    
    Response includes column headers, rows of data, and metadata about the CSV file.
    """
    conn = get_connection()
    try:
        app_record = queries.get_loan_application(conn, application_id)
        if not app_record:
            raise HTTPException(status_code=404, detail="Application not found.")
        bank_name = app_record.get("bank_name", "Unknown")
    finally:
        close_connection(conn)
    
    csv_path = _find_transaction_csv(bank_name, application_id)
    if not csv_path:
        raise HTTPException(
            status_code=404,
            detail=f"No transaction CSV found for bank '{bank_name}' in extracted_transactions/."
        )
    
    try:
        import csv as csv_mod
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            columns = reader.fieldnames or []
            rows = list(reader)
        
        return {
            "application_id": application_id,
            "bank_name": bank_name,
            "csv_filename": csv_path.name,
            "total_rows": len(rows),
            "columns": columns,
            "rows": rows,
        }
    except Exception as e:
        logger.error(f"Error parsing transaction CSV {csv_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not parse CSV: {str(e)}")


@app.get("/features-csv/{application_id}/download")
async def download_features_csv(application_id: str):
    """
    The feature-extraction results as CSV: every transaction with the category,
    subcategory, needs/wants, counterparty and confidence the pipeline assigned.

    Distinct from /transactions-csv, which serves the raw extracted rows before
    any classification.
    """
    conn = get_connection()
    try:
        app_record = queries.get_loan_application(conn, application_id)
        if not app_record:
            raise HTTPException(status_code=404, detail="Application not found.")
        bank_name = app_record.get("bank_name", "Unknown")
        txns = queries.get_transactions(conn, application_id) or []
    finally:
        close_connection(conn)

    rows = _merge_classification(txns, bank_name)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No classified transactions are available for this application yet.",
        )

    import csv as csv_mod
    import io

    columns = ["date", "description", "debit", "credit", "balance", "category",
               "subcategory", "needs_wants", "merchant_entity", "counterparty_key",
               "rail_type", "classification_method", "matched_rule", "confidence",
               "recurrence_type", "suggestion_reason"]

    buffer = io.StringIO()
    writer = csv_mod.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})

    safe_bank = (bank_name or "UNKNOWN").replace(" ", "_").upper()
    filename = f"{safe_bank}_{application_id[:8]}_feature_extraction.csv"
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),  # BOM so Excel reads UTF-8
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/report-xlsx/{application_id}/download")
@app.get("/report-cam/{application_id}/download")
async def download_report_xlsx(application_id: str):
    """The full multi-sheet Excel analysis and Credit Appraisal Memo (CAM) report."""
    conn = get_connection()
    try:
        app_record = queries.get_loan_application(conn, application_id)
        if not app_record:
            raise HTTPException(status_code=404, detail="Application not found.")
        bank_name = app_record.get("bank_name", "Unknown")
        txns = queries.get_transactions(conn, application_id) or []
        result = queries.get_loan_result(conn, application_id)
    finally:
        close_connection(conn)

    features = {}
    if result:
        metadata = result.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        metadata = metadata or {}
        features = metadata.get("features_summary") or metadata

    if not txns:
        raise HTTPException(
            status_code=404,
            detail="No transactions are available for this application yet.",
        )

    def _build():
        import io

        from services.report_builder import build_report

        workbook = build_report(features, _merge_classification(txns, bank_name), app_record)
        stream = io.BytesIO()
        workbook.save(stream)
        return stream.getvalue()

    try:
        payload = await asyncio.to_thread(_build)
    except Exception as e:
        logger.error(f"Report generation failed for {application_id}: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Could not build the report: {e}")

    safe_bank = (bank_name or "UNKNOWN").replace(" ", "_").upper()
    filename = f"{safe_bank}_{application_id[:8]}_CAM_analysis_report.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/transactions-csv/{application_id}/download")
async def download_transactions_csv(application_id: str):
    """Downloads the raw extracted transaction CSV file."""
    conn = get_connection()
    try:
        app_record = queries.get_loan_application(conn, application_id)
        if not app_record:
            raise HTTPException(status_code=404, detail="Application not found.")
        bank_name = app_record.get("bank_name", "Unknown")
    finally:
        close_connection(conn)
    
    csv_path = _find_transaction_csv(bank_name, application_id)
    if not csv_path:
        raise HTTPException(
            status_code=404,
            detail=f"No transaction CSV found for bank '{bank_name}'."
        )
    
    return FileResponse(
        str(csv_path),
        media_type="text/csv",
        filename=csv_path.name,
        headers={"Content-Disposition": f'attachment; filename="{csv_path.name}"'}
    )


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

def find_pdf_path(pdf_name: str) -> Path:
    if not pdf_name:
        return None
    
    clean_name = Path(pdf_name.strip()).name
    possible_names = [clean_name]
    if not clean_name.lower().endswith(".pdf"):
        possible_names.append(f"{clean_name}.pdf")
    
    # Try stripping trailing numbers e.g. "SBI1.pdf" -> "SBI.pdf"
    no_digits = re.sub(r'\d+', '', clean_name)
    if no_digits and no_digits != clean_name:
        possible_names.append(no_digits)
        if not no_digits.lower().endswith(".pdf"):
            possible_names.append(f"{no_digits}.pdf")

    # Try first word matching e.g. "AXIS BANK.pdf" -> "AXIS.pdf"
    first_word = clean_name.split()[0]
    if first_word and first_word != clean_name:
        possible_names.append(first_word)
        if not first_word.lower().endswith(".pdf"):
            possible_names.append(f"{first_word}.pdf")

    search_dirs = [
        BASE_DIR / "uploads",
        Path(settings.UPLOAD_DIR).resolve(),
        BASE_DIR.parent / "temporary bank statments",
        BASE_DIR.parent / "processed", 
        BASE_DIR.parent / "input",
        BASE_DIR.parent / "uploads",
        BASE_DIR.parent / "Testing_Dump",
        BASE_DIR.parent,
        BASE_DIR
    ]

    for s_dir in search_dirs:
        if not s_dir.exists():
            continue
        for name in possible_names:
            p = s_dir / name
            if p.exists():
                return p
            # Case-insensitive check
            for child in s_dir.iterdir():
                if child.is_file() and child.name.lower() == name.lower():
                    return child

    # Fallback: substring match on any .pdf file in search_dirs
    for s_dir in search_dirs:
        if not s_dir.exists():
            continue
        for child in s_dir.glob("*.pdf"):
            base = clean_name.lower().replace(".pdf", "").split()[0]
            base_no_digits = re.sub(r'\d+', '', base)
            child_base = child.name.lower().replace(".pdf", "")
            child_base_no_digits = re.sub(r'\d+', '', child_base)
            if (base and base in child.name.lower()) or (base_no_digits and base_no_digits in child_base_no_digits):
                return child

    return None

def sync_all_bank_hashes() -> None:
    """Populates image / header screenshot hashes for all registered banks in bank_statement_hashes.json."""
    hashes_file = BASE_DIR.parent / "bank_statement_hashes.json"
    if not hashes_file.exists():
        return
    
    try:
        with open(hashes_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return
            bank_list = json.loads(content)
        
        modified = False
        for bank in bank_list:
            b_name = bank.get("bank_name") or bank.get("name") or ""
            images = bank.get("images", [])
            
            needs_hash = not images or any(not img.get("hash") for img in images)
            if needs_hash:
                pdf_name = None
                for img in images:
                    if img.get("original_statement"):
                        pdf_name = img.get("original_statement")
                        break
                if not pdf_name and b_name:
                    pdf_name = f"{b_name}.pdf"
                
                if pdf_name:
                    pdf_path = find_pdf_path(pdf_name)
                    if pdf_path:
                        pass

        if modified:
            with open(hashes_file, "w", encoding="utf-8") as f:
                json.dump(bank_list, f, indent=4)
    except Exception as e:
        logger.error(f"Error syncing bank image hashes: {e}")

def load_bank_hashes() -> list:
    """Safely loads bank_statement_hashes.json data, handling empty or corrupt files."""
    hashes_file = BASE_DIR.parent / "bank_statement_hashes.json"
    if not hashes_file.exists():
        return []
    try:
        with open(hashes_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Error loading bank_statement_hashes.json: {e}")
        return []

def save_bank_hashes(data: list) -> None:
    """Safely writes data to bank_statement_hashes.json and syncs missing hashes."""
    hashes_file = BASE_DIR.parent / "bank_statement_hashes.json"
    try:
        with open(hashes_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        sync_all_bank_hashes()
    except Exception as e:
        logger.error(f"Error saving bank_statement_hashes.json: {e}")

@app.get("/api/detect_bank")
async def detect_bank_endpoint(pdf: str = Query(...)):
    """Detects bank name for a PDF."""
    pdf_path = find_pdf_path(pdf)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")
    detected = extractor_adapter.detect_bank_name(pdf_path)
    return {"status": "success", "detected_bank": detected}

_JOB_UPLOAD_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _looks_like_job_upload(stem: str) -> bool:
    """Statements uploaded through /upload are renamed to a bare UUID."""
    return bool(_JOB_UPLOAD_NAME.match(stem))


@app.get("/api/statements")
async def get_statements():
    """Lists statement PDF files from search directories that belong to registered banks in the registry."""
    bank_list = load_bank_hashes()
    registry_pdfs = set()
    
    for bank in bank_list:
        for img in bank.get("images", []):
            orig = img.get("original_statement")
            if orig:
                registry_pdfs.add(orig.strip())
        b_name = bank.get("bank_name") or bank.get("name")
        if b_name:
            registry_pdfs.add(b_name.strip())
            registry_pdfs.add(f"{b_name.strip()}.pdf")

    search_dirs = [
        BASE_DIR / "uploads",
        Path(settings.UPLOAD_DIR).resolve(),
        BASE_DIR.parent / "processed", 
        BASE_DIR.parent / "input",
        BASE_DIR.parent / "uploads"
    ]
    
    matched_pdfs = set()
    for s_dir in search_dirs:
        if s_dir.exists():
            for f in s_dir.glob("*.pdf"):
                filename = f.name
                stem = f.stem
                
                is_in_hashes = (
                    filename in registry_pdfs or 
                    stem in registry_pdfs or 
                    any(p.lower() == filename.lower() for p in registry_pdfs) or
                    any(p.lower() == stem.lower() for p in registry_pdfs)
                )
                is_in_templates = template_service.bank_exists(stem) or template_service.bank_exists(filename)

                # A PDF uploaded FOR calibration belongs to a bank that, by
                # definition, is not yet in the registry or the templates. The
                # old filter dropped it, so a newly uploaded statement vanished
                # from this list on the next page refresh and could never be
                # re-selected -- the calibrator could not calibrate a new bank.
                is_calibration_upload = f.parent == Path(settings.UPLOAD_DIR).resolve() and not _looks_like_job_upload(stem)

                if is_in_hashes or is_in_templates or is_calibration_upload:
                    matched_pdfs.add(filename)

    return sorted(list(matched_pdfs))

@app.post("/api/upload_calibrator_pdf")
async def upload_calibrator_pdf(file: UploadFile = File(...)):
    """Uploads a PDF file specifically for interactive calibration."""
    if not file.filename.lower().endswith(".pdf") and file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    # Keep the human-readable name (the calibrator lists PDFs by name), but
    # strip any directory component: `Path(UPLOAD_DIR) / "../../x.pdf"` writes
    # outside the upload directory.
    filename = os.path.basename(file.filename or "").strip() or "calibration.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    file_path = Path(settings.UPLOAD_DIR).resolve() / filename
    if Path(settings.UPLOAD_DIR).resolve() not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
        
        logger.info(f"Calibrator PDF saved: {file_path}")
        return {"success": True, "filename": filename, "file_path": str(file_path)}
    except Exception as e:
        logger.error(f"Error uploading calibrator PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/delete_statement")
async def delete_statement(pdf: str = Query(...)):
    """Deletes a statement PDF file from the server uploads/archive and registry."""
    if not pdf:
        raise HTTPException(status_code=400, detail="Missing pdf parameter")
        
    pdf_path = find_pdf_path(pdf)
    deleted_files = []
    
    if pdf_path and pdf_path.exists():
        try:
            pdf_path.unlink()
            deleted_files.append(str(pdf_path))
            logger.info(f"Deleted statement file from disk: {pdf_path}")
        except Exception as err:
            logger.error(f"Failed to delete {pdf_path}: {err}")
            
    clean_name = Path(pdf).name
    clean_stem = Path(pdf).stem
    upload_file = Path(settings.UPLOAD_DIR) / clean_name
    if upload_file.exists() and str(upload_file) not in deleted_files:
        try:
            upload_file.unlink()
            deleted_files.append(str(upload_file))
        except Exception:
            pass

    # Clean up from bank_statement_hashes.json
    registry_removed = False
    try:
        bank_list = load_bank_hashes()
        new_bank_list = []
        for bank in bank_list:
            b_name = bank.get("bank_name") or bank.get("name") or ""
            # Filter out images matching deleted pdf
            images = bank.get("images", [])
            new_images = [
                img for img in images 
                if (img.get("original_statement") or "").lower() not in [clean_name.lower(), clean_stem.lower()]
            ]
            if len(new_images) != len(images):
                registry_removed = True
                bank["images"] = new_images

            # Keep bank entry if it has name_coordinates or columns or remaining images
            new_bank_list.append(bank)
            
        if registry_removed:
            save_bank_hashes(new_bank_list)
            logger.info(f"Removed '{pdf}' references from bank registry.")
    except Exception as reg_err:
        logger.warning(f"Error cleaning registry for deleted PDF {pdf}: {reg_err}")

    if not deleted_files and not registry_removed:
        # Check if file was already deleted or doesn't exist
        return {"status": "success", "message": f"Statement {pdf} is no longer in archive."}
        
    return {
        "status": "success", 
        "message": f"Successfully deleted {pdf}", 
        "deleted_files": deleted_files,
        "registry_updated": registry_removed
    }

def _open_calibrator_pdf(pdf_path, password: str = None):
    """
    Open a calibrator PDF, turning an encrypted file into a 422 the UI can act on.

    These three endpoints used to return a bare 500 carrying the raw MuPDF text
    "document closed or encrypted", and /api/pdf_info was worse -- it reported a
    page count on a locked file, i.e. reported success.
    """
    from extractor import _open_fitz, PdfPasswordError
    try:
        return _open_fitz(str(pdf_path), password)
    except PdfPasswordError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "password_incorrect" if e.password_supplied else "password_required",
                "message": str(e),
            },
        )


@app.get("/api/pdf_info")
async def get_pdf_info(pdf: str = Query(...), password: str = Query(None)):
    """Returns page count of the uploaded PDF."""
    pdf_path = find_pdf_path(pdf)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")
    doc = _open_calibrator_pdf(pdf_path, password)
    try:
        page_count = len(doc)
        doc.close()
        return {"page_count": page_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/render")
async def render_pdf_page(pdf: str = Query(...), page: int = Query(0), password: str = Query(None)):
    """Returns rendered page as PNG."""
    pdf_path = find_pdf_path(pdf)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")
    doc = _open_calibrator_pdf(pdf_path, password)
    try:
        p = doc[page]
        pix = p.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        doc.close()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/extract")
async def extract_text(
    pdf: str = Query(...),
    page: int = Query(0),
    x0: float = Query(...),
    y0: float = Query(...),
    x1: float = Query(...),
    y1: float = Query(...),
    password: str = Query(None)
):
    """Extracts text within specified normalized bounding box coordinates."""
    pdf_path = find_pdf_path(pdf)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")
    doc = _open_calibrator_pdf(pdf_path, password)
    try:
        p = doc[page]
        rect = p.rect
        clip_rect = fitz.Rect(x0 * rect.width, y0 * rect.height, x1 * rect.width, y1 * rect.height)
        extracted_text = p.get_text("text", clip=clip_rect).strip()
        doc.close()
        snippet = (
            f"import fitz\n"
            f"doc = fitz.open('{pdf_path.name}')\n"
            f"page = doc[{page}]\n"
            f"rect = page.rect\n"
            f"clip_rect = fitz.Rect({x0}*rect.width, {y0}*rect.height, {x1}*rect.width, {y1}*rect.height)\n"
            f"text = page.get_text('text', clip=clip_rect).strip()\n"
            f"print(text)\n"
        )
        return {
            "extracted_text": extracted_text,
            "snippet": snippet,
            "coordinates": {
                "x0_pct": round(x0 * 100, 2),
                "y0_pct": round(y0 * 100, 2),
                "x1_pct": round(x1 * 100, 2),
                "y1_pct": round(y1 * 100, 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/extract_transactions")
async def extract_transactions(pdf: str = Query(...), filter_date: bool = Query(False)):
    """Preview extracted transactions using StandalonePDFExtractor."""
    pdf_path = find_pdf_path(pdf)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found")

    try:
        bank_name = extractor_adapter.detect_bank_name(pdf_path)
        df = extractor_adapter.extract_statement(pdf_path, bank_name)
        raw_rows = extractor_adapter.format_transactions_for_db(df)
        return {"status": "success", "transactions": raw_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save")
async def save_name_coordinate(request: dict):
    """Saves name coordinate bounds to bank_statement_hashes.json."""
    pdf_name = request.get("pdf")
    coordinates = request.get("coordinates")
    
    if not pdf_name or not coordinates:
        raise HTTPException(status_code=400, detail="Missing pdf or coordinates")
        
    bank_list = load_bank_hashes()
    updated = False
    clean_stem = Path(pdf_name).stem
    
    for bank in bank_list:
        b_name = bank.get("bank_name") or bank.get("name") or ""
        has_pdf = (
            any(img.get("original_statement") == pdf_name for img in bank.get("images", [])) or
            b_name.lower() == clean_stem.lower() or
            b_name.lower() == pdf_name.lower()
        )
        if has_pdf:
            bank["name_coordinates"] = coordinates
            for img in bank.get("images", []):
                if "account_holder" in img:
                    del img["account_holder"]
            updated = True
                    
    if not updated:
        new_entry = {
            "bank_name": clean_stem.upper(),
            "images": [{"original_statement": pdf_name}],
            "name_coordinates": coordinates,
            "columns": []
        }
        bank_list.append(new_entry)
        updated = True
        
    save_bank_hashes(bank_list)
    return {"status": "success", "updated": updated}

@app.post("/api/save_columns")
async def save_columns_coordinate(request: dict):
    """Saves column split coordinate configuration to bank_statement_hashes.json."""
    pdf_name = request.get("pdf")
    columns = request.get("columns")
    
    if not pdf_name or columns is None:
        raise HTTPException(status_code=400, detail="Missing pdf or columns")
        
    bank_list = load_bank_hashes()
    updated = False
    clean_stem = Path(pdf_name).stem
    
    for bank in bank_list:
        b_name = bank.get("bank_name") or bank.get("name") or ""
        has_pdf = (
            any(img.get("original_statement") == pdf_name for img in bank.get("images", [])) or
            b_name.lower() == clean_stem.lower() or
            b_name.lower() == pdf_name.lower()
        )
        if has_pdf:
            bank["columns"] = columns
            updated = True
                    
    if not updated:
        new_entry = {
            "bank_name": clean_stem.upper(),
            "images": [{"original_statement": pdf_name}],
            "name_coordinates": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.3},
            "columns": columns
        }
        bank_list.append(new_entry)
        updated = True
        
    save_bank_hashes(bank_list)
    return {"status": "success", "updated": updated}

@app.get("/api/banks-config")
async def get_banks_config():
    """Returns raw banks.json file content."""
    from services.template_service import TEMPLATE_PATH
    try:
        if TEMPLATE_PATH.exists():
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
                import json
                return json.load(f)
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bank-hashes")
async def get_bank_hashes():
    """Returns raw bank_statement_hashes.json file content."""
    return load_bank_hashes()

@app.get("/api/view_pdf")
async def view_pdf(pdf: str = Query(...)):
    """Serves raw PDF file for inline viewing in browser."""
    pdf_path = find_pdf_path(pdf)
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(str(pdf_path), media_type="application/pdf")

@app.post("/api/bank-hashes/crud")
async def create_bank_hash(entry: dict):
    """Creates a new bank registry entry in bank_statement_hashes.json."""
    data = load_bank_hashes()
    data.append(entry)
    save_bank_hashes(data)
    return {"status": "success", "message": "Registry entry created successfully"}

@app.put("/api/bank-hashes/crud/{index}")
async def update_bank_hash(index: int, entry: dict):
    """Updates an existing bank registry entry at specific index."""
    data = load_bank_hashes()
    if index < 0 or index >= len(data):
        raise HTTPException(status_code=400, detail="Invalid index")
        
    data[index] = entry
    save_bank_hashes(data)
    return {"status": "success", "message": "Registry entry updated successfully"}

@app.delete("/api/bank-hashes/crud/{index}")
async def delete_bank_hash(index: int):
    """Deletes a bank registry entry at specific index."""
    data = load_bank_hashes()
    if index < 0 or index >= len(data):
        raise HTTPException(status_code=400, detail="Invalid index")
        
    deleted_item = data.pop(index)
    save_bank_hashes(data)
        
    bank_name = deleted_item.get('bank_name') or deleted_item.get('name') or 'entry'
    return {"status": "success", "message": f"Deleted {bank_name}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
