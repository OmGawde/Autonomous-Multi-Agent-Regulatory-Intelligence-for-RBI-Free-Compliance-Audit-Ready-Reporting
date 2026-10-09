import os
import re
import sys
import json
import logging
import traceback
import warnings
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Suppress noisy third-party warnings before importing heavy libraries
# ---------------------------------------------------------------------------
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"          # No download bars
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN_WARNING"] = "1" # Mute unauthenticated token warning
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"       # Mute Windows symlink warning
os.environ["TRANSFORMERS_VERBOSITY"] = "error"             # Only errors from transformers
os.environ["TOKENIZERS_PARALLELISM"] = "false"             # Avoid fork warnings

# Torch backend only. transformers 4.x imports TensorFlow if it is installed;
# this project never uses it, and a broken TF/protobuf pairing on the host
# otherwise fails the import chain with an error that names neither. The 4.55
# pin is required by BharatGen FinanceParam -- see Feature Extraction/src/model.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
warnings.filterwarnings("ignore", category=FutureWarning)  # Suppress pandas FutureWarning

import threading

import pdfplumber
import fitz  # PyMuPDF
import pandas as pd

# PyMuPDF is not thread-safe: MuPDF keeps per-context state, and concurrent
# access from multiple threads corrupts it. The web app calls extraction through
# asyncio.to_thread, so six simultaneous uploads meant six threads inside fitz at
# once -- which silently returned PARTIAL tables rather than raising. Measured on
# the sample corpus: Axis dropped 422 rows to 273 and SBI 71 to 54, and both were
# then scored and reported as "success". Rows went missing from within pages, so
# the per-page diagnostics did not catch it either.
#
# Serialising costs little real throughput: extraction is CPU-bound, so the GIL
# already prevents these threads from running in parallel. Processes get their
# own MuPDF context, so the ProcessPoolExecutor path is unaffected -- each worker
# holds its own copy of this lock and never contends.
_PDF_READ_LOCK = threading.Lock()


class PdfPasswordError(Exception):
    """
    The PDF is encrypted and could not be opened with the password supplied.

    `password_supplied` distinguishes "we need one" from "the one we got is
    wrong", which is the difference between prompting and re-prompting.
    """

    def __init__(self, message: str, *, password_supplied: bool):
        super().__init__(message)
        self.password_supplied = password_supplied


def _open_fitz(file_path, password: str = None):
    """
    Open a PDF with PyMuPDF, authenticating first if it is encrypted.

    `fitz.open()` does NOT raise on an encrypted file -- it returns a Document
    whose page *count* reads fine, so callers happily proceed and then die
    several frames later at the first page access with a bare
    `ValueError: document closed or encrypted`. That is why every existing
    try/except in this module missed the case: they wrap the wrong call.

    Probing `needs_pass` up front turns it into a typed error the API can render
    as a password prompt.
    """
    doc = fitz.open(file_path)
    if doc.needs_pass:
        name = Path(file_path).name
        if not password:
            doc.close()
            raise PdfPasswordError(
                f"{name} is password-protected.", password_supplied=False
            )
        # authenticate() returns 0 on failure and a non-zero permission level on
        # success. needs_pass stays truthy even after a successful call, so it
        # must not be used as the success test.
        if not doc.authenticate(password):
            doc.close()
            raise PdfPasswordError(
                f"The password supplied for {name} is incorrect.",
                password_supplied=True,
            )
    return doc


def probe_pdf(file_path, password: str = None) -> dict:
    """
    Inspect a PDF before committing to processing it.

    Answers the three questions the upload endpoint needs: is it encrypted, did
    the supplied password open it, and does it carry a text layer at all. The
    last one matters because a scanned statement is out of scope for parsing --
    but reporting it as "unknown bank template" sends the user to fix the wrong
    thing.
    """
    result = {
        "encrypted": False,
        "unlocked": True,
        "pages": 0,
        "has_text_layer": False,
        "error": None,
    }
    try:
        with _PDF_READ_LOCK:
            doc = fitz.open(file_path)
            result["encrypted"] = bool(doc.needs_pass)
            if doc.needs_pass:
                if not password or not doc.authenticate(password):
                    result["unlocked"] = False
                    doc.close()
                    return result
            result["pages"] = len(doc)
            # A handful of pages is enough to tell a text PDF from a scan.
            for i in range(min(3, len(doc))):
                if (doc[i].get_text() or "").strip():
                    result["has_text_layer"] = True
                    break
            doc.close()
    except Exception as e:
        result["error"] = str(e) or e.__class__.__name__
        logger.warning(f"Could not probe {file_path}: {result['error']}")
    return result

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup Logging — route to stdout so output doesn't interleave with stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("PDFExtractor")

# Suppress chatty loggers from third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Ensure the Feature Extraction package is importable from the project root.
# This lets `from src.pipeline import process_single_csv` work even when
# extractor.py is run directly (python extractor.py).
# ---------------------------------------------------------------------------
_FE_DIR = Path(__file__).parent.resolve() / "Feature Extraction"
if str(_FE_DIR) not in sys.path:
    sys.path.insert(0, str(_FE_DIR))


def _import_pipeline():
    """Lazy import of the pipeline module to avoid import-time side effects."""
    try:
        from src.pipeline import process_single_csv
        from src.classifier import TransactionClassifier
        return process_single_csv, TransactionClassifier
    except ImportError as e:
        logger.warning(f"Feature pipeline not available: {e}")
        logger.warning("PDF extraction will work, but feature analysis will be skipped.")
        return None, None


def _extract_page_table_by_geometry(page, vertical_lines: list, table_region: dict = None):
    """
    Build a table directly from word positions using calibrated boundaries.

    `find_tables(vertical_strategy="explicit")` is not usable for a hand-drawn
    calibration: it intersects the supplied lines with a table bounding box it
    infers for itself, and silently drops any boundary outside it. On the Union
    statement that turned 7 boundaries into 5 columns and lost the balance
    column entirely -- the calibration the user drew was quietly overruled.

    Here the boundaries are authoritative. Words are grouped into visual rows,
    then allocated to the column whose span contains their horizontal centre.
    """
    if not vertical_lines or len(vertical_lines) < 2:
        return []

    rect = page.rect
    y_min, y_max = rect.y0, rect.y1
    if table_region:
        y0_frac = float(table_region.get("y0", 0.0)) if page.number == 0 else 0.0
        y1_frac = float(table_region.get("y1", 1.0))
        y_min = rect.y0 + y0_frac * rect.height
        y_max = rect.y0 + y1_frac * rect.height

    bounds = sorted(float(x) for x in vertical_lines)
    n_cols = len(bounds) - 1

    rows = {}
    for w in page.get_text("words"):
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        if not text.strip() or y1 < y_min or y0 > y_max:
            continue
        centre = (x0 + x1) / 2.0
        if centre < bounds[0] or centre > bounds[-1]:
            continue
        col = min(range(n_cols), key=lambda i: 0 if bounds[i] <= centre < bounds[i + 1] else 1)
        if not (bounds[col] <= centre < bounds[col + 1]):
            continue
        rows.setdefault(round(y0 / 3.0) * 3.0, []).append((col, x0, text))

    grid = []
    for y in sorted(rows):
        cells = [[] for _ in range(n_cols)]
        for col, x0, text in sorted(rows[y], key=lambda t: t[1]):
            cells[col].append(text)
        row = [" ".join(c).strip() for c in cells]
        if not any(row):
            continue

        # Wrapped cells arrive as their own visual row carrying only the
        # narration. find_tables merges those implicitly; doing it explicitly
        # here keeps a two-line description from becoming a junk row.
        non_empty = [i for i, c in enumerate(row) if c]
        if grid and len(non_empty) == 1 and n_cols > 2:
            i = non_empty[0]
            if 0 < i < n_cols - 1:
                grid[-1][i] = f"{grid[-1][i]} {row[i]}".strip()
                continue
        grid.append(row)

    return [grid] if len(grid) > 1 else []


def _extract_page_table_fitz(page, use_explicit: bool, vertical_lines: list = None,
                             table_region: dict = None):
    """
    Extracts table cell text grid from a PyMuPDF Page instance using page.find_tables().
    Returns list of extracted table grids (list of list of strings).
    Preserves multi-line cell text within transaction rows.

    With `use_explicit`, column boundaries are dictated rather than inferred --
    the route both ICICI and any calibrated bank take. `table_region` clips the
    search vertically: without it, explicit boundaries happily slice the
    customer's address block into columns and admit it as table rows.
    """
    extracted_tables = []
    try:
        clip = None
        if table_region:
            r = page.rect
            y0_norm = float(table_region.get("y0", 0.0)) if page.number == 0 else 0.0
            y1_norm = float(table_region.get("y1", 1.0))
            clip = fitz.Rect(
                r.x0,
                r.y0 + y0_norm * r.height,
                r.x1,
                r.y0 + y1_norm * r.height,
            )

        if use_explicit and vertical_lines:
            if table_region:
                geometric = _extract_page_table_by_geometry(page, vertical_lines, table_region)
                if geometric:
                    return geometric

            kwargs = {"vertical_strategy": "explicit", "vertical_lines": vertical_lines}
            if clip is not None:
                kwargs["clip"] = clip
            tabs = page.find_tables(**kwargs)
            if tabs and tabs.tables:
                for tab in tabs.tables:
                    grid = tab.extract()
                    if grid and len(grid) > 1:
                        extracted_tables.append(grid)

            if not extracted_tables:
                geometric = _extract_page_table_by_geometry(page, vertical_lines, table_region)
                if geometric:
                    return geometric
        else:
            if clip is not None:
                tabs = page.find_tables(clip=clip)
            else:
                tabs = page.find_tables()

            if tabs and tabs.tables:
                for tab in tabs.tables:
                    grid = tab.extract()
                    if grid and len(grid) > 1:
                        extracted_tables.append(grid)

            # Check if extracted tables are degenerate:
            # 1. No tables found
            # 2. Collapsed rows (e.g. IDBI/HDFC where rows collapsed into 1 row of a <= 3 row table)
            # 3. Only a few rows (<= 4) while the page has substantial text (> 20 lines)
            has_collapsed = any(
                len(grid) <= 3 and any(
                    any(isinstance(c, str) and c.count('\n') >= 3 for c in r if c)
                    for r in grid[1:]
                )
                for grid in extracted_tables
            )
            is_degenerate = False
            if not extracted_tables or has_collapsed:
                is_degenerate = True
            else:
                text_lines = [l for l in page.get_text().splitlines() if l.strip()]
                has_any_dates = any(
                    any(re.search(r'\b\d{1,2}[-/ ](?:[A-Za-z]{3}|\d{1,2})[-/ ]\d{2,4}\b', str(c)) for c in r if c)
                    for g in extracted_tables for r in g
                )
                if not has_any_dates and len(text_lines) > 20:
                    is_degenerate = True

            if is_degenerate:
                # 1. Try horizontal_strategy="text" (solves borderless tables like HDFC & IDBI)
                tabs_ht = page.find_tables(horizontal_strategy="text", clip=clip) if clip is not None else page.find_tables(horizontal_strategy="text")
                if tabs_ht and tabs_ht.tables:
                    grids_ht = [t.extract() for t in tabs_ht.tables if t.extract() and len(t.extract()) > 2]
                    curr_max = max(len(g) for g in extracted_tables) if extracted_tables else 0
                    if grids_ht and (has_collapsed or curr_max <= 4 or max(len(g) for g in grids_ht) > curr_max):
                        extracted_tables = grids_ht
                        is_degenerate = False

            if is_degenerate:
                # 2. Try vertical_strategy="text", horizontal_strategy="text" (solves borderless Kotak tables)
                tabs_vh = page.find_tables(vertical_strategy="text", horizontal_strategy="text", clip=clip) if clip is not None else page.find_tables(vertical_strategy="text", horizontal_strategy="text")
                if tabs_vh and tabs_vh.tables:
                    grids_vh = [t.extract() for t in tabs_vh.tables if t.extract() and len(t.extract()) > 2]
                    curr_max = max(len(g) for g in extracted_tables) if extracted_tables else 0
                    if grids_vh and (has_collapsed or curr_max <= 4 or max(len(g) for g in grids_vh) > curr_max):
                        extracted_tables = grids_vh
                        is_degenerate = False

            # Fallback to vertical_strategy="text", horizontal_strategy="lines" if still nothing
            if not extracted_tables:
                tabs_text = page.find_tables(vertical_strategy="text", horizontal_strategy="lines")
                if tabs_text and tabs_text.tables:
                    for tab in tabs_text.tables:
                        grid = tab.extract()
                        if grid:
                            extracted_tables.append(grid)
    except Exception as e:
        logger.warning(f"PyMuPDF table extraction error on page: {e}")
        extracted_tables = []
    return extracted_tables


def _extract_pdf_page_range(file_path_str: str, page_indices: list, use_explicit: bool,
                            vertical_lines: list, password: str = None, table_region: dict = None):
    """
    Multiprocess worker helper to extract tables from a specific slice of PDF page indices using PyMuPDF (fitz).
    Falls back to pdfplumber if fitz.find_tables() returns empty or irregular structure.

    `password` has to be passed explicitly rather than shared: this runs inside a
    ProcessPoolExecutor worker for long statements, and an authenticated
    Document cannot cross a process boundary.
    """
    # See _PDF_READ_LOCK: concurrent fitz access silently truncates the result.
    with _PDF_READ_LOCK:
        return _extract_pdf_page_range_unlocked(
            file_path_str, page_indices, use_explicit, vertical_lines, password, table_region
        )


def _extract_pdf_page_range_unlocked(file_path_str: str, page_indices: list, use_explicit: bool,
                                     vertical_lines: list, password: str = None, table_region: dict = None):
    """The actual page walk. Callers must hold _PDF_READ_LOCK."""
    page_tables = []
    pdf_plumber_obj = None

    try:
        doc = _open_fitz(file_path_str, password)
        for page_idx in page_indices:
            if page_idx >= len(doc):
                continue
            page = doc[page_idx]

            # 1. Primary: PyMuPDF fitz table parser
            tables = _extract_page_table_fitz(page, use_explicit, vertical_lines, table_region)

            # 2. Fallback: pdfplumber table parser if fitz yields no valid table rows
            if not tables or all(len(t) <= 1 for t in tables if t):
                if pdf_plumber_obj is None:
                    import pdfplumber
                    # pdfplumber takes the password at construction (unlike fitz,
                    # which authenticates after opening) and raises
                    # PdfminerException with an EMPTY message string on a locked
                    # file -- so it has to be caught by type, never by message.
                    pdf_plumber_obj = pdfplumber.open(file_path_str, password=password or "")

                if page_idx < len(pdf_plumber_obj.pages):
                    plumber_page = pdf_plumber_obj.pages[page_idx]
                    if use_explicit and vertical_lines:
                        # pdfplumber names the same option differently.
                        tables = plumber_page.extract_tables(table_settings={
                            "vertical_strategy": "explicit",
                            "explicit_vertical_lines": vertical_lines,
                            "horizontal_strategy": "lines"
                        })
                    else:
                        tables = plumber_page.extract_tables()
                        if not tables or all(len(t) <= 1 for t in tables if t):
                            tables = plumber_page.extract_tables(table_settings={
                                "vertical_strategy": "text",
                                "horizontal_strategy": "text"
                            })

            for t in tables:
                if t:
                    page_tables.append((page_idx, t))
        doc.close()
    finally:
        if pdf_plumber_obj:
            try:
                pdf_plumber_obj.close()
            except Exception:
                pass

    return page_tables



class StandalonePDFExtractor:
    def __init__(self):
        self.base_dir = Path(__file__).parent.resolve()
        self.uploads_dir = self.base_dir / "uploads"
        self.output_dir = self.base_dir / "output"
        self.templates_path = self.base_dir / "templates" / "banks.json"
        
        # Ensure directories exist
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load templates
        if not self.templates_path.exists():
            raise FileNotFoundError(f"Templates file not found at: {self.templates_path}")
        with open(self.templates_path, "r", encoding="utf-8") as f:
            self.templates = json.load(f)

    def reload_templates(self):
        """Reload templates from banks.json to pick up newly saved bank templates."""
        if self.templates_path.exists():
            with open(self.templates_path, "r", encoding="utf-8") as f:
                disk_templates = json.load(f)
            # Keep any in-memory calibrated templates injected during tests or dynamic runtime
            for k, v in list(self.templates.items()):
                if isinstance(v, dict) and v.get("calibrated") and k not in disk_templates:
                    disk_templates[k] = v
            self.templates = disk_templates

    # Labels that introduce the account holder's name. The value sits either on
    # the same line after the colon, or on the following line.
    _HOLDER_LABELS = [
        r"account\s*holders?[’']?\s*name",
        r"account\s*holder[’']?s?\s*name",
        r"account\s*name",
        r"customer\s*name",
        r"name\s*&\s*address",
        r"name\s*and\s*address",
        r"welcome",
    ]

    # Lines that look like a name but are not one.
    _NOT_A_NAME = re.compile(
        r"bank|statement|account|branch|address|ifsc|micr|customer\s*id|"
        r"nominee|mobile|email|joint\s*holder|period|summary|detail|"
        r"transaction|balance|deposit|withdrawal|credit|debit|page|date|"
        # Column headers read as title-case two-word names: the ICICI table
        # header "Cheque Number" was picked up as the account holder.
        r"cheque|number|remark|amount|particular|narration|serial|"
        r"\bsr\b|\bno\b|\btype\b|\bcode\b|opening|closing|value|"
        r"^\d|road|nagar|marg|floor|sector|mumbai|thane|maharashtra|india|"
        r"^\W*$",
        re.IGNORECASE,
    )

    @staticmethod
    def _looks_like_person_name(line: str) -> bool:
        """A 2-5 word, mostly-alphabetic line that reads as a personal name."""
        text = (line or "").strip().strip(":").strip()
        # Drop a leading honorific before testing case -- SBI prints
        # "Mr. GIRISH BABAJI GIDAYE", whose mixed case fails an isupper() test
        # on the whole string.
        text = re.sub(r"^(MR|MRS|MS|MISS|DR|SHRI|SMT|SRI|PROF)\.?\s+", "", text, flags=re.I)

        if not (6 <= len(text) <= 60):
            return False
        if StandalonePDFExtractor._NOT_A_NAME.search(text):
            return False

        words = text.split()
        if not (2 <= len(words) <= 5):
            return False

        # Every word must be a real word, not a column abbreviation. Without
        # this the ICICI table header "S No." reads as a two-word title-case
        # name.
        alpha = [w.strip(".") for w in words if w.strip(".").isalpha()]
        if len(alpha) < 2 or any(len(w) < 2 for w in alpha):
            return False
        if sum(len(w) for w in alpha) < 8:
            return False

        # Statements print holder names in upper case or title case.
        return text.isupper() or text.istitle()

    def extract_account_holder(self, file_path: Path, password: str = None) -> dict:
        """
        Read the account holder's name and number off the statement itself.

        Every bank prints the holder somewhere, but never in the same place:
        Axis puts a bare name on line 1, SBI prefixes it with "Welcome:", BOI
        labels it "Account holder name:", Union "Name & Address :", and BOB
        prints a column of Hindi/English labels followed by a column of values.

        ICICI labels it not at all: the name sits in a bare address block near
        the foot of page 1, and the only thing marking it as a name is that a
        postal address follows it.

        Returns {"account_holder": str|None, "account_number": str|None}. A name
        is never invented -- where a statement genuinely omits it the field
        stays None, and downstream self-transfer detection is written to stand
        down rather than guess when the holder is unknown.
        """
        result = {"account_holder": None, "account_number": None}
        try:
            with _PDF_READ_LOCK:
                doc = _open_fitz(file_path, password)
                pages = [doc[i].get_text() for i in range(min(2, len(doc)))]
                doc.close()
        except PdfPasswordError:
            raise
        except Exception as e:
            logger.warning(f"Could not read {file_path.name} for account holder: {e}")
            return result

        text = "\n".join(pages)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        # Account number, wherever it appears.
        m = re.search(r"(?:account\s*(?:no|number)\.?\s*:?\s*)([0-9Xx]{6,20})", text, re.I)
        if m:
            result["account_number"] = m.group(1).strip()

        # 1. Labelled forms -- value on the same line, or on a following line.
        #
        # `search`, not `match`: Bank of Baroda prefixes each label with the
        # Hindi text and a slash ("/ Account Name"), so the label is not at the
        # start of the line. BOB also prints ALL labels first and ALL values
        # after, so the lookahead has to be long and skip other labels.
        label_like = re.compile(r":|/|" + "|".join(self._HOLDER_LABELS), re.I)
        for label in self._HOLDER_LABELS:
            pattern = re.compile(label + r"\s*:?\s*(.*)", re.I)
            for idx, line in enumerate(lines):
                match = pattern.search(line)
                if not match:
                    continue
                inline = match.group(1).strip()
                if self._looks_like_person_name(inline):
                    result["account_holder"] = self._clean_holder(inline)
                    return result
                for follow in lines[idx + 1: idx + 15]:
                    if label_like.search(follow) and not self._looks_like_person_name(follow):
                        continue
                    if self._looks_like_person_name(follow):
                        result["account_holder"] = self._clean_holder(follow)
                        return result

        # 2. Unlabelled: a name in the first few lines (Axis prints it on line 1).
        for line in lines[:6]:
            if self._looks_like_person_name(line):
                result["account_holder"] = self._clean_holder(line)
                return result

        # 3. Unlabelled address block. ICICI's e-statement opens straight into
        # the transaction table and prints the customer's name and postal
        # address as a bare block below it, with no label of any kind. Requiring
        # a PIN code within the next four lines is what separates a real name
        # from a stray title-case line; the branch's own address block just
        # above it is already excluded by _NOT_A_NAME ("branch", "marg",
        # "mumbai").
        pin_code = re.compile(r"(?<![0-9])[0-9]{6}(?![0-9])")
        for idx, line in enumerate(lines):
            if not self._looks_like_person_name(line):
                continue
            if any(pin_code.search(nxt) for nxt in lines[idx + 1: idx + 5]):
                result["account_holder"] = self._clean_holder(line)
                logger.info(
                    f"Read account holder from the unlabelled address block "
                    f"in {file_path.name}"
                )
                return result

        logger.info(f"No account holder name found in {file_path.name}")
        return result

    @staticmethod
    def _clean_holder(value: str) -> str:
        """Strip honorifics and tidy whitespace."""
        text = re.sub(r"^\s*(MR|MRS|MS|MISS|DR|SHRI|SMT|SRI|PROF)\.?\s+", "",
                      str(value).strip(), flags=re.I)
        return re.sub(r"\s+", " ", text).strip(" :,-")

    def detect_bank(self, file_path: Path, password: str = None) -> str:
        """Heuristically detects the bank name from filename or first page text content."""
        self.reload_templates()
        filename_lower = file_path.name.lower()
        
        # 1. Quick Filename Check
        bank_mapping = {
            "hdfc": "HDFC",
            "sbi": "SBI",
            "icici": "ICICI",
            "axis": "Axis",
            "kotak": "Kotak",
            "bank of india": "Bank Of India",
            "boi": "Bank Of India",
            "union": "Union",
            "bob": "BOB",
            "baroda": "BOB",
            "canara": "Canara Bank",
            "idbi": "IDBI Bank",
            "pnb": "Punjab National Bank",
            "punjab national": "Punjab National Bank",
            "yes": "YES Bank",
            "yes bank": "YES Bank",
            "bom": "Bank Of Maharashtra",
            "mahabank": "Bank Of Maharashtra",
            "maharashtra": "Bank Of Maharashtra",
            "federal": "Federal Bank",
            "iob": "Indian Overseas Bank",
            "indian overseas": "Indian Overseas Bank",
            "indusind": "IndusInd Bank",
        }
        for kw, bank_name in bank_mapping.items():
            if kw in filename_lower:
                logger.info(f"Detected bank '{bank_name}' from filename.")
                return bank_name
                
        # 2. Content checks.
        #
        # Filename matching cannot fire for web uploads -- the API stores the
        # file under a UUID -- so this path decides in practice. Plain
        # first-match-wins over page-1 text is unsafe: a statement's transaction
        # table is full of *counterparty* bank names, so an Axis statement
        # mentioning "ICICI Ban" and "Kotak" as payees was detected as ICICI and
        # parsed with the wrong template.
        try:
            with _PDF_READ_LOCK:
                doc = _open_fitz(file_path, password)
                if len(doc) == 0:
                    doc.close()
                    return "Other"
                first_page_text = doc[0].get_text() or ""
                doc.close()
        except PdfPasswordError:
            # Never swallow this into "Other" -- an encrypted file would be
            # reported to the user as an unrecognised bank, sending them to fix
            # the wrong problem entirely.
            raise
        except Exception as e:
            logger.warning(f"Error checking text content for bank detection: {e}")
            return "Other"

        text_lower = first_page_text.lower()
        # The header carries the issuing bank's own branding; the table below
        # carries everyone else's. `header_raw` keeps its original case so IFSC
        # codes stay matchable.
        header_raw = " ".join(first_page_text.splitlines()[:40])
        header = header_raw.lower()

        # 2a-cal. Banks added through the interactive calibrator. Without this,
        # a freshly calibrated bank can never be auto-detected -- detection only
        # knew the eight hardcoded names -- so its template would sit on disk
        # unreachable unless the operator typed the name in exactly. Calibration
        # records the IFSC prefix and any distinguishing text markers from the
        # sample statement, and both are checked in the header only, for the
        # same reason the built-in rules are: the transaction table below is
        # full of other banks' names.
        for cal_name, cal_cfg in self.templates.items():
            if not isinstance(cal_cfg, dict) or not cal_cfg.get("calibrated"):
                continue
            ifsc_prefix = (cal_cfg.get("ifsc_prefix") or "").strip().lower()
            if ifsc_prefix and ifsc_prefix in {c.lower() for c in re.findall(r"([A-Z]{4})0[A-Z0-9]{6}", header_raw)}:
                logger.info(f"Detected calibrated bank '{cal_name}' from its IFSC prefix.")
                return cal_name
            for marker in cal_cfg.get("detect_markers") or []:
                if marker and str(marker).lower() in text_lower:
                    logger.info(f"Detected calibrated bank '{cal_name}' from marker '{marker}'.")
                    return cal_name

        # 2a. Explicitly labelled IFSC code (e.g. "IFSC : YESB0000469", "Branch IFSC : MAHB0001655")
        ifsc_map = {
            "utib": "Axis", "icic": "ICICI", "hdfc": "HDFC", "sbin": "SBI",
            "kkbk": "Kotak", "bkid": "Bank Of India", "barb": "BOB",
            "ubin": "Union", "punb": "Punjab National Bank", "yesb": "YES Bank",
            "mahb": "Bank Of Maharashtra", "fdrl": "Federal Bank",
            "ioba": "Indian Overseas Bank", "indb": "IndusInd Bank",
            "cnrb": "Canara Bank", "ibkl": "IDBI Bank"
        }
        labeled_ifsc = re.findall(r'(?:ifsc|rtgs/neft\s*ifsc|branch\s*ifsc|ifsc\s*code|ifs\s*code)\s*[:\-\s]\s*([A-Za-z]{4}0[A-Za-z0-9]{6})', first_page_text, re.I)
        for code in labeled_ifsc:
            p = code[:4].lower()
            if p in ifsc_map:
                bank = ifsc_map[p]
                logger.info(f"Detected bank '{bank}' from labeled IFSC code '{code}'.")
                return bank

        # 2ab. Unambiguous self-identification anywhere on the page.
        self_id_markers = {
            "ICICI": ["icici bank limited", "icici bank ltd", "www.icici"],
            "SBI": ["state bank of india", "onlinesbi", "sbi.co.in"],
            "Axis": ["axis bank limited", "axis bank ltd", "axisbank.com"],
            "HDFC": ["hdfc bank limited", "hdfc bank ltd", "hdfcbank.com"],
            "Kotak": ["kotak mahindra bank", "kotak.com"],
            "Union": ["union bank of india", "unionbankofindia"],
            "BOB": ["bank of baroda", "bankofbaroda"],
            "Bank Of India": ["bank of india", "bankofindia"],
            "Canara Bank": ["canara bank", "canarabank.com"],
            "IDBI Bank": ["idbi bank limited", "idbi bank ltd", "idbibank.in", "idbi bank"],
            "Punjab National Bank": ["punjab national bank", "pnbindia.in", "pnbindia.com"],
            "YES Bank": ["yes bank limited", "yes bank ltd", "yesbank.in", "yes bank", "yes rewardz"],
            "Bank Of Maharashtra": ["bank of maharashtra", "mahabank.co.in", "mahaconnect.in"],
            "Federal Bank": ["federal bank limited", "federal bank ltd", "federalbank.co.in", "federal bank"],
            "Indian Overseas Bank": ["indian overseas bank", "iob.in"],
            "IndusInd Bank": ["indusind bank limited", "indusind bank ltd", "indusind.com", "www.indusind"],
        }
        self_id_hits = {}
        for bank_name, markers in self_id_markers.items():
            count = sum(text_lower.count(marker) for marker in markers)
            if count:
                self_id_hits[bank_name] = count
        if len(self_id_hits) == 1:
            bank = next(iter(self_id_hits))
            logger.info(
                f"Detected bank '{bank}' from its full name/website on page 1."
            )
            return bank

        # 2ac. Header IFSC check with counterparty transaction narrative filtering
        clean_header_for_ifsc = re.sub(r'(?i)(?:neft\s*[cd]r[-/]|upi/|rtgs[-/]|imps[-/])[A-Za-z0-9_/-]+', '', header_raw)
        candidates = {
            ifsc_map[code.lower()]
            for code in re.findall(r"([A-Z]{4})0[A-Z0-9]{6}", clean_header_for_ifsc)
            if code.lower() in ifsc_map
        }
        if len(candidates) == 1:
            bank = candidates.pop()
            logger.info(f"Detected bank '{bank}' from the IFSC code in the statement header.")
            return bank

        # 2b. Weighted marker scoring
        text_markers = {
            "ICICI": ["icici bank", "icici", "industrial credit and investment corporation"],
            "HDFC": ["hdfc bank", "hdfc", "housing development finance"],
            "SBI": ["state bank of india", "sbi", "stategroup"],
            "Axis": ["axis bank", "axis"],
            "Kotak": ["kotak mahindra", "kotak"],
            "Bank Of India": ["bank of india", "star house", "boi"],
            "Union": ["union bank of india", "union bank"],
            "BOB": ["bank of baroda", "baroda"],
            "Canara Bank": ["canara bank", "canara sb"],
            "IDBI Bank": ["idbi bank", "idbi"],
            "Punjab National Bank": ["punjab national bank", "punjab national", "pnb"],
            "YES Bank": ["yes bank", "yesb"],
            "Bank Of Maharashtra": ["bank of maharashtra", "mahabank", "mahb"],
            "Federal Bank": ["federal bank", "fdrl"],
            "Indian Overseas Bank": ["indian overseas bank", "overseas bank", "ioba"],
            "IndusInd Bank": ["indusind bank", "indusind", "indb"],
        }
        scores = {}
        for bank_name, markers in text_markers.items():
            score = 0
            for marker in markers:
                if marker in header:
                    score += 10 + len(marker.split())      # header hit, longer phrase wins
                elif marker in text_lower:
                    score += 1                              # anywhere on the page
            if score:
                scores[bank_name] = score

        if scores:
            best = max(scores, key=scores.get)
            if scores[best] >= 10:
                logger.info(f"Detected bank '{best}' from statement header (scores: {scores}).")
                return best
            # Only incidental page-body mentions -- almost certainly counterparty
            # banks named in the transaction table. Saying "Other" is honest;
            # guessing picks a wrong template and mis-parses the whole file.
            logger.warning(
                f"No issuing-bank marker in the header of {file_path.name} "
                f"(weak scores: {scores}); treating the bank as unknown."
            )
            return "Other"
            
        logger.warning(f"Unable to auto-detect bank for {file_path.name}. Defaulting to 'Other'.")
        return "Other"

    def _extract_camsfinserv_aa(self, doc, bank_name: str, total_pages: int) -> pd.DataFrame:
        """Parses CAMSfinserv Account Aggregator statements directly from text stream when table borders bleed."""
        full_text = '\n'.join([doc[i].get_text('text') for i in range(total_pages)])
        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        txns = []
        curr = None
        for l in lines:
            if re.match(r'^S\d{8}$', l):
                if curr:
                    txns.append(curr)
                curr = [l]
            elif curr is not None:
                curr.append(l)
        if curr:
            txns.append(curr)

        parsed = []
        for t in txns:
            date_match = None
            for item in t[1:]:
                m = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', item)
                if m:
                    date_match = m.group(1)
                    break
            t_type = None
            type_idx = -1
            for i, item in enumerate(t):
                if re.search(r'\b(DEBIT|CREDIT)\b', item):
                    t_type = 'DEBIT' if 'DEBIT' in item else 'CREDIT'
                    type_idx = i
                    break
            amt = 0.0
            bal = 0.0
            if type_idx != -1:
                nums = []
                for item in t[type_idx:]:
                    m_nums = re.findall(r'\b\d+\.\d{2}\b', item)
                    nums.extend(m_nums)
                if len(nums) >= 2:
                    amt = float(nums[0])
                    bal = float(nums[1])
                elif len(nums) == 1:
                    amt = float(nums[0])

            narration = ''
            if type_idx > 3:
                desc_parts = []
                for item in t[3:type_idx]:
                    if not re.search(r'^\d{2}/\d{2}/\d{4}', item) and not re.search(r'^\d{4}-\d{2}-\d{2}', item) and item not in ['NACH', 'UPI', 'CARD', 'ATM', 'OTHERS', 'INTEREST_CREDI', 'T']:
                        desc_parts.append(item)
                narration = ' '.join(desc_parts).strip()
                narration = re.sub(r'^(?:\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*[ap]m\s*)+', '', narration, flags=re.I).strip()

            parsed.append({
                'Date': date_match,
                'Description': narration,
                'Withdrawal Amt.': amt if t_type == 'DEBIT' else 0.0,
                'Deposit Amt.': amt if t_type == 'CREDIT' else 0.0,
                'Closing Balance': bal
            })

        df = pd.DataFrame(parsed)
        if not df.empty and 'Date' in df.columns:
            try:
                df['Date'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce').dt.strftime('%Y-%m-%d')
            except Exception:
                pass
            df = df.dropna(subset=['Date'])

        target_schema_cols = ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
        for col in target_schema_cols:
            if col not in df.columns:
                df[col] = ""
        result = df[target_schema_cols]
        result.attrs["extraction_diagnostics"] = {
            "template_used": bank_name,
            "template_fallback": False,
            "requested_bank": bank_name,
            "pages_total": total_pages,
            "pages_without_tables": 0,
            "pages_without_tables_index": [],
            "rows_extracted": len(result)
        }
        return result

    def extract_with_template(self, file_path: Path, bank_name: str, password: str = None) -> pd.DataFrame:
        """Extracts tables from PDF using template and exact same logic as main project."""
        # Whether we are parsing this bank with its own template or with the
        # generic one. Applying a generic column mapping to a bank-specific
        # layout is the single highest-risk misalignment path in the system --
        # it produces rows that parse but map amounts to the wrong columns --
        # and until now nothing recorded that it had happened.
        template_fallback = bank_name not in self.templates
        if template_fallback:
            logger.warning(
                f"No template for bank '{bank_name}'; falling back to the generic "
                f"'Other' template. Column mapping is a guess from here on."
            )

        bank_config = self.templates.get(bank_name, self.templates.get("Other"))
        column_mapping = bank_config.get("columns", {})
        date_format = bank_config.get("date_format")

        # Positional column mapping for banks with empty/missing header rows
        col_positions = bank_config.get("column_positions")
        positional_mapping = None
        positional_expected_cols = 0
        if col_positions:
            positional_expected_cols = col_positions.get("expected_cols", 0)
            positional_mapping = {int(k): v for k, v in col_positions.get("mapping", {}).items()}

        # Tables to skip (e.g. Account Summary, Statement Summary)
        # Some banks (Bank of Baroda) merge the serial number, the value date and
        # the narration into one cell, so there is no date column to map. The
        # date is split back out of the description after extraction.
        date_in_description = bool(bank_config.get("date_in_description"))

        skip_tables_cfg = bank_config.get("skip_tables")
        skip_markers = [m.lower() for m in skip_tables_cfg.get("marker_columns", [])] if skip_tables_cfg else []

        # Explicit column geometry. Two sources, one mechanism:
        #   - `vertical_lines_norm` from the interactive calibrator, stored as
        #     fractions of page width so it survives a change of page size;
        #   - ICICI's, which used to be a hardcoded list gated on the literal
        #     string "ICICI" a few lines below this one.
        # Feeding both through the same path means a calibrated bank is not a
        # special case -- it takes exactly the route the built-in banks take.
        vertical_lines_norm = bank_config.get("vertical_lines_norm")
        explicit_vertical_lines = None
        if vertical_lines_norm:
            with _PDF_READ_LOCK:
                _probe_doc = _open_fitz(file_path, password)
                page_width = _probe_doc[0].rect.width if len(_probe_doc) else 0.0
                _probe_doc.close()
            if page_width:
                explicit_vertical_lines = sorted(
                    round(float(x) * page_width, 2) for x in vertical_lines_norm
                )
                logger.info(
                    f"Using calibrated column geometry for {bank_name}: "
                    f"{len(explicit_vertical_lines)} boundaries -> "
                    f"{len(explicit_vertical_lines) - 1} columns"
                )

        use_explicit = explicit_vertical_lines is not None
        if not use_explicit and bank_name == "ICICI":
            with _PDF_READ_LOCK:
                _doc_w = _open_fitz(file_path, password)
                _pw = _doc_w[0].rect.width if len(_doc_w) else 595.0
                _doc_w.close()
            if _pw < 700.0:
                use_explicit = True
                explicit_vertical_lines = [20.0, 55.0, 115.0, 190.0, 385.0, 455.0, 525.0, 575.0]

        table_region = bank_config.get("table_region_norm")

        logger.info(f"Starting extraction for {file_path.name} using {bank_name} template...")

        tables = []
        with _PDF_READ_LOCK:
            doc = _open_fitz(file_path, password)
            total_pages = len(doc)
            p0_text = doc[0].get_text() if total_pages > 0 else ""
            if "camsfinserv" in p0_text.lower() or ("fi type" in p0_text.lower() and re.search(r'\bS\d{8}\b', p0_text)):
                logger.info(f"Detected CAMSfinserv Account Aggregator statement format for {file_path.name}")
                df_aa = self._extract_camsfinserv_aa(doc, bank_name, total_pages)
                doc.close()
                return df_aa
            doc.close()

        num_workers = min(os.cpu_count() or 4, 16)
        if total_pages > 15 and num_workers > 1:
            logger.info(f"Parallelizing PyMuPDF PDF table extraction across {num_workers} CPU worker processes for {total_pages} pages...")
            import math
            from concurrent.futures import ProcessPoolExecutor
            chunk_size = math.ceil(total_pages / num_workers)
            page_chunks = [
                list(range(i, min(i + chunk_size, total_pages)))
                for i in range(0, total_pages, chunk_size)
            ]
            all_page_tables = []
            with ProcessPoolExecutor(max_workers=num_workers) as executor:
                futures = [
                    executor.submit(_extract_pdf_page_range, str(file_path), chunk, use_explicit, explicit_vertical_lines, password, table_region)
                    for chunk in page_chunks
                ]
                for future in futures:
                    all_page_tables.extend(future.result())

            # Sort by original page index to maintain exact sequential order
            all_page_tables.sort(key=lambda x: x[0])
            tables = [t for page_idx, t in all_page_tables]
        else:
            all_page_tables = _extract_pdf_page_range(str(file_path), list(range(total_pages)), use_explicit, explicit_vertical_lines, password, table_region)
            tables = [t for page_idx, t in all_page_tables]

        # Which pages yielded nothing. A page whose table extraction fails is
        # swallowed by design (so one bad page does not lose the statement), but
        # that also means a 3-of-13-page extraction currently reports success.
        # Derived from the page indices we got back rather than by threading a
        # counter through the process pool. Note a genuinely blank page counts
        # here too -- hence "without tables", not "failed".
        pages_seen = {page_idx for page_idx, _ in all_page_tables}
        pages_without_tables = [i for i in range(total_pages) if i not in pages_seen]
        if pages_without_tables:
            logger.warning(
                f"{len(pages_without_tables)} of {total_pages} pages yielded no table "
                f"in {file_path.name} (0-based indices: {pages_without_tables})"
            )

        matching_dfs = []
        standard_cols = ['date', 'time', 'description', 'cheque', 'value_date', 'amount', 'type', 'debit', 'credit', 'balance']
        last_mapping = None
        last_col_count = 0
        active_mapping = {}

        # Keywords for smart fuzzy fallback matching
        keywords = {
            "date": ["date", "txndate", "trandate", "transactiondate", "txn date", "tran date", "transaction date"],
            "time": ["time", "timing", "txntime", "transtime", "txn time", "trans time"],
            "cheque": ["cheque", "chq", "ref", "instrument", "chq / ref", "chq./ref.no"],
            "value_date": ["valuedate", "valdate", "value date", "val date", "v date"],
            "description": ["remark", "narration", "particular", "desc", "detail", "transaction details", "transaction remarks"],
            "amount": ["amount", "txnamt", "transactionamt", "txn amt", "transaction amt", "debit/credit"],
            "type": ["type", "crdr", "drcr", "dr / cr", "dr/cr", "cr/dr", "tran type", "cr / dr"],
            "debit": ["withdraw", "debit", "wdr", "withdrawal amt", "withdrawals"],
            "credit": ["deposit", "credit", "dep", "deposit amt", "deposits"],
            "balance": ["balance", "bal", "closing balance", "running balance", "current balance"]
        }

        for table_idx, table in enumerate(tables):
            if not table or len(table) < 1:
                continue

            # Skip non-transaction tables based on skip_tables markers
            if skip_markers:
                table_text = ' '.join(str(cell) for row in table[:3] for cell in row if cell).lower()
                if any(marker in table_text for marker in skip_markers):
                    continue
            
            header_idx = -1
            temp_mapping = {}
            
            # Scan first 35 rows (with multi-line combination) to locate header row
            for idx in range(min(35, len(table))):
                max_cols = max(len(table[idx + k]) for k in range(min(5, len(table) - idx)))
                row_combined = []
                for col_i in range(max_cols):
                    cell_vals = [table[idx + k][col_i] for k in range(min(5, len(table) - idx)) if col_i < len(table[idx + k])]
                    row_combined.append(' '.join(v for v in cell_vals if v).strip())
                
                matches = 0
                curr_mapping = {}
                
                for internal_name, bank_header in column_mapping.items():
                    bh_clean = re.sub(r'[^a-z0-9]', '', str(bank_header).lower()) if bank_header else ''
                    for i, col in enumerate(row_combined):
                        if i in curr_mapping:
                            continue
                        col_clean = re.sub(r'[^a-z0-9]', '', str(col).lower())
                        if not col_clean:
                            continue
                        
                        if bh_clean and len(col_clean) >= 3 and (bh_clean in col_clean or col_clean in bh_clean):
                            matches += 1
                            curr_mapping[i] = internal_name
                            break
                            
                        for kw in keywords.get(internal_name, []):
                            if kw in col_clean:
                                matches += 1
                                curr_mapping[i] = internal_name
                                break
                        if i in curr_mapping:
                            break

                # Also search unmapped columns for amount and type if debit/credit not both found
                if 'debit' not in curr_mapping.values() or 'credit' not in curr_mapping.values():
                    for i, col in enumerate(row_combined):
                        if i in curr_mapping:
                            continue
                        col_clean = re.sub(r'[^a-z0-9]', '', str(col).lower())
                        if not col_clean:
                            continue
                        if 'amount' not in curr_mapping.values():
                            for kw in keywords.get('amount', []):
                                if kw in col_clean:
                                    matches += 1
                                    curr_mapping[i] = 'amount'
                                    break
                        if 'type' not in curr_mapping.values() and i not in curr_mapping:
                            for kw in keywords.get('type', []):
                                if kw in col_clean:
                                    matches += 1
                                    curr_mapping[i] = 'type'
                                    break

                # Remap: if a column named "cr/dr" or "type" was grabbed by debit/credit, correct it to 'type'
                for i, assigned in list(curr_mapping.items()):
                    if assigned in ('debit', 'credit') and i < len(row_combined):
                        col_c = re.sub(r'[^a-z0-9]', '', str(row_combined[i]).lower())
                        if any(t_kw in col_c for t_kw in ['crdr', 'drcr', 'type']) and not any(d_kw in col_c for d_kw in ['withdraw', 'deposit']):
                            curr_mapping[i] = 'type'

                if matches >= 3:
                    header_idx = idx
                    # Skip multi-line header rows (guard against skipping data rows)
                    skip_header_rows = 1
                    for k in range(1, min(5, len(table) - idx)):
                        k_text = ' '.join(str(c) for c in table[idx + k] if c).lower()
                        has_date = bool(re.search(r'\b\d{1,2}[-/ ](?:[A-Za-z]{3}|\d{1,2})[-/ ]\d{2,4}\b', k_text))
                        has_amt = bool(re.search(r'\b\d{1,3}(?:,\d{2,3})*\.\d{2}\b', k_text))
                        if has_date or has_amt:
                            break
                        if any(w in k_text for w in ['date', 'amount', 'remarks', 'narration', 'balance', 'inr', 'cheque', 'particular', 'withdrawal', 'deposit']):
                            skip_header_rows += 1
                        else:
                            break
                    header_idx = idx + skip_header_rows - 1
                    temp_mapping = curr_mapping
                    break

            if header_idx != -1:
                last_mapping = temp_mapping
                last_col_count = len(table[header_idx])
                active_mapping = last_mapping
                data_rows = table[header_idx + 1:]
                df = pd.DataFrame(data_rows)
            elif positional_mapping and (len(table[0]) == positional_expected_cols or len(table[0]) >= max(positional_mapping.keys()) + 1):
                # Use positional column mapping from config (e.g. SBI with empty headers or calibrated geometry)
                active_mapping = positional_mapping
                # Skip the header row (first row) since it's empty/partial
                data_rows = table[1:]
                df = pd.DataFrame(data_rows)
                last_mapping = positional_mapping
                last_col_count = len(table[0])
            elif last_mapping:
                num_cols = len(table[0])
                curr_mapping = {}
                
                if num_cols == last_col_count:
                    curr_mapping = last_mapping
                else:
                    # Dynamically detect date column in first 5 rows of continuation table
                    date_col_idx = 0
                    for r in table[:min(5, len(table))]:
                        for ci, cell in enumerate(r):
                            if cell and re.search(r'\b\d{1,2}[-/ ](?:[A-Za-z]{3}|\d{1,2})[-/ ]\d{2,4}\b', str(cell)):
                                date_col_idx = ci
                                break
                        if date_col_idx > 0:
                            break
                    
                    curr_mapping[date_col_idx] = "date"
                    curr_mapping[date_col_idx + 1] = "description"
                    curr_mapping[num_cols - 1] = "balance"
                    
                    mid_cols = [c for c in range(date_col_idx + 2, num_cols - 1)]
                    if len(mid_cols) == 1:
                        curr_mapping[mid_cols[0]] = "debit"
                    elif len(mid_cols) == 2:
                        curr_mapping[mid_cols[0]] = "debit"
                        curr_mapping[mid_cols[1]] = "credit"
                    elif len(mid_cols) >= 3:
                        curr_mapping[mid_cols[-2]] = "debit"
                        curr_mapping[mid_cols[-1]] = "credit"
                
                active_mapping = curr_mapping
                df = pd.DataFrame(table)
            else:
                continue

            df = df.rename(columns=active_mapping)
            
            # Helper to clean currency amounts
            def clean_amount(val):
                if pd.isna(val) or val == '' or val is None:
                    return 0.0
                if isinstance(val, (int, float)):
                    return float(val)
                cleaned = str(val).replace(',', '')
                cleaned = cleaned.replace('₹', '').replace('\u20b9', '')
                cleaned = cleaned.replace('INR', '').replace('Rs.', '').replace('Rs', '').replace('$', '')
                cleaned_lower = cleaned.lower()
                is_dr = 'dr' in cleaned_lower or (cleaned.strip().startswith('(') and cleaned.strip().endswith(')'))
                cleaned = re.sub(r'(?i)\(?\b(cr|dr)\b\)?', '', cleaned)
                cleaned = cleaned.replace('(', '').replace(')', '').replace(' ', '').strip()
                try:
                    num = float(cleaned)
                    return -num if is_dr else num
                except:
                    return 0.0

            # If single amount column present and debit/credit are missing or empty, resolve them
            if 'amount' in df.columns:
                def resolve_amount_type(row):
                    amt_val = clean_amount(row.get('amount'))
                    t_val = str(row.get('type', '')).strip().upper()
                    if amt_val < 0:
                        return abs(amt_val), 0.0
                    if any(d in t_val for d in ['DR', 'DEBIT', 'WDL', 'WITHDRAWAL']):
                        return abs(amt_val), 0.0
                    elif any(c in t_val for c in ['CR', 'CREDIT', 'DEP', 'DEPOSIT']):
                        return 0.0, abs(amt_val)
                    else:
                        return 0.0, abs(amt_val)
                debit_populated = 'debit' in df.columns and (df['debit'].apply(clean_amount).abs().sum() > 0)
                credit_populated = 'credit' in df.columns and (df['credit'].apply(clean_amount).abs().sum() > 0)
                if not (debit_populated or credit_populated):
                    resolved = df.apply(resolve_amount_type, axis=1)
                    df['debit'] = [r[0] for r in resolved]
                    df['credit'] = [r[1] for r in resolved]

            # Merge cheque column into description if present
            if 'cheque' in df.columns and 'description' in df.columns:
                def append_cheque(r):
                    desc = str(r['description']) if pd.notnull(r['description']) else ''
                    chq = str(r['cheque']).strip() if pd.notnull(r['cheque']) else ''
                    if chq and chq.lower() not in ['nan', 'none', '', 'null', '-']:
                        if chq not in desc:
                            return f"{desc} - Cheque No: {chq}"
                    return desc
                df['description'] = df.apply(append_cheque, axis=1)

            # Filter standard columns
            valid_cols = [c for c in df.columns if isinstance(c, str) and c in standard_cols]
            df = df[valid_cols]
            
            # Ensure standard columns exist
            for col in standard_cols:
                if col not in df.columns:
                    df[col] = None
                    
            matching_dfs.append(df[standard_cols])

        # What the extractor observed on the way through. Carried on the frame
        # itself so callers get it without a signature change; the adapter reads
        # it immediately after extraction, before any pandas operation can drop
        # attrs.
        diagnostics = {
            "template_used": bank_name if not template_fallback else "Other",
            "template_fallback": template_fallback,
            "requested_bank": bank_name,
            "pages_total": total_pages,
            "pages_without_tables": len(pages_without_tables),
            "pages_without_tables_index": pages_without_tables,
        }

        target_schema_cols = ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
        if not matching_dfs:
            logger.warning(f"No matching tables found using {bank_name} configuration.")
            empty = pd.DataFrame(columns=target_schema_cols)
            empty.attrs["extraction_diagnostics"] = {**diagnostics, "rows_extracted": 0}
            return empty

        # Concatenate and clean data
        final_df = pd.concat(matching_dfs, ignore_index=True)
        final_df = final_df.dropna(subset=['debit', 'credit', 'balance'], how='all')

        # Remove empty padding rows (no date AND no description)
        final_df = final_df[~(
            final_df['date'].apply(lambda x: not x or (pd.isna(x) if not isinstance(x, str) else x.strip() == '')) &
            final_df['description'].apply(lambda x: not x or (pd.isna(x) if not isinstance(x, str) else x.strip() == ''))
        )]

        # Clean description of any newlines and multi-spaces
        def clean_description(val):
            if pd.isna(val) or val is None:
                return ""
            s = str(val).strip()
            s = re.sub(r'-\s*\n\s*', '-', s)  # Join hyphenated split words/lines
            s = re.sub(r'\s*\n\s*', ' ', s)   # Replace other newlines with spaces
            s = re.sub(r'\s+', ' ', s)        # Normalize multiple spaces
            return s
        final_df['description'] = final_df['description'].apply(clean_description)

        # Split "<serial> <dd-mm-yyyy> <narration>" back into date + description.
        # Continuation lines carry no date and inherit the previous row's, which
        # is how the statement itself reads.
        if date_in_description:
            leading_date = re.compile(r'^\s*(?:\d{1,4}\s+)?(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+(.*)$')
            extracted_dates = []
            cleaned_descriptions = []
            last_date = None
            for value in final_df['description']:
                match = leading_date.match(str(value))
                if match:
                    last_date = match.group(1)
                    cleaned_descriptions.append(match.group(2).strip())
                else:
                    cleaned_descriptions.append(str(value).strip())
                extracted_dates.append(last_date)
            final_df['description'] = cleaned_descriptions
            final_df['date'] = extracted_dates

        # Helper to clean currency amounts
        def clean_amount(val):
            if pd.isna(val) or val == '' or val is None:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            # Remove commas, currency symbols, and common abbreviations
            cleaned = str(val).replace(',', '')
            cleaned = cleaned.replace('₹', '').replace('\u20b9', '')
            cleaned = cleaned.replace('INR', '').replace('Rs.', '').replace('Rs', '').replace('$', '')
            # Clean up space/suffix Cr/Dr
            cleaned_lower = cleaned.lower()
            is_dr = 'dr' in cleaned_lower or (cleaned.strip().startswith('(') and cleaned.strip().endswith(')'))
            cleaned = re.sub(r'(?i)\(?\b(cr|dr)\b\)?', '', cleaned)
            cleaned = cleaned.replace('(', '').replace(')', '').replace(' ', '').strip()
            try:
                num = float(cleaned)
                return -num if is_dr else num
            except:
                return 0.0

        for col in ['debit', 'credit', 'balance']:
            final_df[col] = final_df[col].apply(clean_amount)

        # Merge dedicated time column into date if present
        if 'time' in final_df.columns:
            def merge_time(row):
                d = str(row.get('date', '')).strip()
                t = str(row.get('time', '')).strip()
                if t and t.lower() not in ('nan', 'none', '', 'null', '-'):
                    m = re.search(r'\b([012]?\d:[0-5]\d(?::[0-5]\d)?(?:\s*[AaPp][Mm])?)\b', t)
                    if m and d:
                        return f"{d} {m.group(1)}"
                return d
            final_df['date'] = final_df.apply(merge_time, axis=1)

        # Helper to parse and standardize dates & timestamps
        def parse_date(val):
            if not val or pd.isna(val):
                return None
            val_str = str(val).replace('\n', ' ').strip()
            if date_format:
                try:
                    cleaned_val = val_str.replace('.', '/').replace('-', '/')
                    clean_format = date_format.replace('.', '/').replace('-', '/')
                    return pd.to_datetime(cleaned_val, format=clean_format)
                except Exception:
                    pass
            # Try standard patterns including 2-digit and 4-digit years with optional time
            for fmt in (
                '%d/%m/%Y %H:%M:%S', '%d-%m-%Y %H:%M:%S', '%d/%m/%y %H:%M:%S', '%d-%m-%y %H:%M:%S',
                '%d/%m/%Y %H:%M', '%d-%m-%Y %H:%M', '%d/%m/%y %H:%M', '%d-%m-%y %H:%M',
                '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%Y-%m-%d', '%Y/%m/%d'
            ):
                try:
                    return pd.to_datetime(val_str, format=fmt)
                except Exception:
                    pass
            try:
                return pd.to_datetime(val_str, dayfirst=True)
            except Exception:
                return None

        final_df['date'] = final_df['date'].apply(parse_date)

        # Drop rows with unparseable/missing dates (e.g. PDF footer legends, disclaimer lines)
        final_df = final_df.dropna(subset=['date'])

        if final_df.empty or 'date' not in final_df.columns:
            logger.warning(f"No valid transaction rows found with valid dates in {file_path.name}")
            empty = pd.DataFrame(columns=target_schema_cols)
            empty.attrs["extraction_diagnostics"] = {**diagnostics, "rows_extracted": 0}
            return empty

        # Deduplicate based on date, description, and balance
        final_df = final_df.drop_duplicates(subset=['date', 'description', 'balance'])

        # Filter out noisy summary/total/balance rows
        def is_noise(desc):
            if not desc: return False
            desc_upper = str(desc).upper().strip()
            exact_noise = ['TOTAL', 'SUMMARY', 'BROUGHT FORWARD', 'CARRIED FORWARD', 'OPENING BALANCE', 'CLOSING BALANCE', 'TRANSACTION TOTAL', 'SUB TOTAL', 'STATEMENT SUMMARY', 'ACCOUNT SUMMARY']
            if desc_upper in exact_noise:
                return True
            starts_noise = ['BROUGHT FORWARD', 'CARRIED FORWARD', 'OPENING BALANCE', 'CLOSING BALANCE', 'TRANSACTION TOTAL', 'STATEMENT SUMMARY']
            if any(desc_upper.startswith(w) for w in starts_noise):
                return True
            return False
        
        final_df = final_df[~final_df['description'].apply(is_noise)]

        if final_df.empty or 'date' not in final_df.columns:
            logger.warning(f"No valid transaction rows remaining after filtering noise in {file_path.name}")
            empty = pd.DataFrame(columns=target_schema_cols)
            empty.attrs["extraction_diagnostics"] = {**diagnostics, "rows_extracted": 0}
            return empty
        
        # Clean up date representations with ISO timestamp support
        def _fmt_date(x):
            if pd.isnull(x):
                return None
            if hasattr(x, "strftime"):
                if x.hour != 0 or x.minute != 0 or x.second != 0:
                    return x.strftime('%Y-%m-%d %H:%M:%S')
                return x.strftime('%Y-%m-%d')
            parsed = pd.to_datetime(x, errors="coerce", dayfirst=True)
            if pd.notnull(parsed):
                if parsed.hour != 0 or parsed.minute != 0 or parsed.second != 0:
                    return parsed.strftime('%Y-%m-%d %H:%M:%S')
                return parsed.strftime('%Y-%m-%d')
            return str(x).strip()

        final_df['date'] = final_df['date'].apply(_fmt_date)
        
        # Standardize Output Schema to exact requested column headers:
        # ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
        schema_mapping = {
            'date': 'Date',
            'description': 'Description',
            'debit': 'Withdrawal Amt.',
            'credit': 'Deposit Amt.',
            'balance': 'Closing Balance'
        }

        final_df = final_df.rename(columns=schema_mapping)

        for col in target_schema_cols:
            if col not in final_df.columns:
                final_df[col] = ""

        result = final_df[target_schema_cols]
        result.attrs["extraction_diagnostics"] = {**diagnostics, "rows_extracted": len(result)}
        return result


    def process_all_uploads(self):
        """Processes all PDF files in the uploads folder."""
        pdf_files = list(self.uploads_dir.glob("*.pdf"))
        
        if not pdf_files:
            logger.info("No PDF files found in 'uploads/' directory.")
            logger.info(f"Please copy your bank statement PDF files to: {self.uploads_dir}")
            return
            
        logger.info(f"Found {len(pdf_files)} PDF file(s) to process.")
        
        process_single_csv, TransactionClassifier = _import_pipeline()
        classifier_instance = None
        if TransactionClassifier is not None:
            try:
                logger.info("Initializing warm TransactionClassifier for PDF batch pipeline")
                classifier_instance = TransactionClassifier()
            except Exception as e:
                logger.warning(f"Could not pre-initialize warm classifier: {e}")

        for file_path in pdf_files:
            try:
                # 1. Detect Bank
                bank_name = self.detect_bank(file_path)
                
                # 2. Extract Data
                df = self.extract_with_template(file_path, bank_name)
                
                if df.empty:
                    logger.warning(f"No transactions extracted from {file_path.name}.")
                    continue
                
                # 3. Save outputs in different formats
                # 3. Save outputs in different formats concurrently
                base_name = file_path.stem
                csv_path = self.output_dir / f"{base_name}_extracted.csv"
                xlsx_path = self.output_dir / f"{base_name}_extracted.xlsx"
                json_path = self.output_dir / f"{base_name}_extracted.json"
                txt_path = self.output_dir / f"{base_name}_table.txt"

                from concurrent.futures import ThreadPoolExecutor

                def _save_outputs_concurrently():
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        def _save_csv():
                            df.to_csv(csv_path, index=False)
                            logger.info(f"Saved CSV output to: {csv_path}")

                        def _save_xlsx():
                            try:
                                df.to_excel(xlsx_path, index=False)
                                logger.info(f"Saved Excel output to: {xlsx_path}")
                            except Exception as ex:
                                logger.warning(f"Could not save Excel output: {ex}")

                        def _save_json():
                            records = df.to_dict(orient="records")
                            with open(json_path, "w", encoding="utf-8") as f:
                                json.dump(records, f, indent=2, ensure_ascii=False)
                            logger.info(f"Saved JSON output to: {json_path}")

                        def _save_txt():
                            with open(txt_path, "w", encoding="utf-8") as f:
                                f.write(df.to_string(index=False))
                            logger.info(f"Saved Formatted TXT table to: {txt_path}")

                        executor.submit(_save_csv)
                        executor.submit(_save_xlsx)
                        executor.submit(_save_json)
                        executor.submit(_save_txt)

                _save_outputs_concurrently()

                logger.info(f"Successfully processed {file_path.name}! Extracted {len(df)} transactions.")
                print(f"\n--- SUCCESS: Processed {file_path.name} ({len(df)} transactions) ---")
                print(f"Output files written to: {self.output_dir}")
                print("-" * 50 + "\n")
                
                # -------------------------------------------------------
                # 4. Run Feature Extraction Pipeline on the extracted DataFrame
                # -------------------------------------------------------
                if process_single_csv:
                    try:
                        logger.info(f"Running feature extraction pipeline on {file_path.name} (in-memory)...")
                        fe_output_dir = str(_FE_DIR / "outputs")
                        features = process_single_csv(
                            csv_path=str(csv_path),
                            bank_name=bank_name,
                            output_dir=fe_output_dir,
                            classifier=classifier_instance,
                            input_df=df,
                        )
                        logger.info(f"Feature extraction complete for {bank_name}!")
                        print(f"--- FEATURES: {bank_name} analysis saved to Feature Extraction/outputs/ ---")
                        print("-" * 50 + "\n")
                    except Exception as e:
                        logger.error(f"Feature extraction failed for {file_path.name}: {e}")
                        logger.error(traceback.format_exc())
                        print(f"--- WARNING: Feature extraction failed (PDF extraction still succeeded) ---\n")

            except Exception as e:
                logger.error(f"Error processing file {file_path.name}: {e}")
                logger.error(traceback.format_exc())

    def extract_multiple_statements(self, file_paths: list, bank_name: str = None, password: str = None) -> pd.DataFrame:
        """
        Extracts and chronologically merges transactions from multiple statement PDFs.

        - Extracts each PDF independently with its matched or detected template.
        - Checks account number consistency across all files.
        - Deduplicates identical transactions across overlapping date boundaries.
        - Chronologically orders the entire combined ledger.
        - Attaches unified extraction diagnostics metadata.
        """
        target_schema_cols = ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
        if not file_paths:
            empty = pd.DataFrame(columns=target_schema_cols)
            empty.attrs["extraction_diagnostics"] = {"merged_files_count": 0, "rows_extracted": 0}
            return empty

        dfs = []
        accounts = []
        all_diagnostics = []

        for fp in file_paths:
            p = Path(fp)
            file_bank = bank_name
            if not file_bank or file_bank.lower() in ("auto-detect", "auto", "unknown", "other"):
                file_bank = self.detect_bank(p, password)

            try:
                acc_info = self.extract_account_holder(p, password)
                if acc_info and acc_info.get("account_number"):
                    accounts.append((p.name, acc_info["account_number"]))
            except Exception:
                pass

            df = self.extract_with_template(p, file_bank, password)
            if not df.empty:
                dfs.append((p.name, df))
                all_diagnostics.append(getattr(df, "attrs", {}).get("extraction_diagnostics", {}))

        if not dfs:
            logger.warning("No transactions extracted from any of the provided statements.")
            empty = pd.DataFrame(columns=target_schema_cols)
            empty.attrs["extraction_diagnostics"] = {"merged_files_count": len(file_paths), "rows_extracted": 0}
            return empty

        # Check account consistency across statements
        unique_accounts = set(acc[1] for acc in accounts if acc[1])
        if len(unique_accounts) > 1:
            logger.warning(
                f"Multi-statement upload contains transactions from different account numbers: {unique_accounts}. "
                f"Statements should belong to the same borrower account."
            )

        combined_rows = []
        for fname, df in dfs:
            df_copy = df.copy()
            df_copy["_source_file"] = fname
            combined_rows.append(df_copy)

        merged_df = pd.concat(combined_rows, ignore_index=True)

        # Parse date temporarily for sorting and deduplication
        def _parse_sort_date(s):
            if not s or pd.isna(s):
                return pd.NaT
            s_str = str(s).strip()
            if re.match(r'^\d{4}-\d{2}-\d{2}', s_str):
                return pd.to_datetime(s_str[:10], format="%Y-%m-%d", errors="coerce")
            return pd.to_datetime(s_str, dayfirst=True, errors="coerce")

        merged_df["_dt"] = merged_df["Date"].apply(_parse_sort_date)
        merged_df = merged_df.sort_values(by="_dt", kind="mergesort").reset_index(drop=True)

        # Deduplicate across identical transactions: same Date, Description, Withdrawal, Deposit, Closing Balance
        dedup_subset = ['Date', 'Description', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
        existing_cols = [c for c in dedup_subset if c in merged_df.columns]
        before_count = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=existing_cols).reset_index(drop=True)
        deduped_count = before_count - len(merged_df)
        if deduped_count > 0:
            logger.info(f"Multi-statement merge: deduplicated {deduped_count} overlapping transactions across statements.")

        merged_df = merged_df.drop(columns=["_dt", "_source_file"], errors="ignore")

        for col in target_schema_cols:
            if col not in merged_df.columns:
                merged_df[col] = ""

        merged_df = merged_df[target_schema_cols]
        merged_df.attrs["extraction_diagnostics"] = {
            "merged_files_count": len(file_paths),
            "rows_extracted": len(merged_df),
            "deduplicated_overlapping_rows": deduped_count,
            "account_numbers_found": list(unique_accounts),
            "all_file_diagnostics": all_diagnostics,
        }
        return merged_df


def extract_multiple_statements(file_paths: list, bank_name: str = None, password: str = None) -> pd.DataFrame:
    """Helper entry point for extracting and chronologically merging multiple statements."""
    extractor = StandalonePDFExtractor()
    return extractor.extract_multiple_statements(file_paths, bank_name, password)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("   BANK STATEMENT EXTRACTOR + FEATURE ANALYSIS PIPELINE   ")
    print("="*60 + "\n")
    
    try:
        extractor = StandalonePDFExtractor()
        extractor.process_all_uploads()
    except Exception as e:
        logger.critical(f"Initialization failed: {e}")