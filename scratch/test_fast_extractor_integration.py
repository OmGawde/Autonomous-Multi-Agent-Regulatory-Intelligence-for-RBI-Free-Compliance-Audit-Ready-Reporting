import fitz
import time
import os
import math
import re
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

def parse_words_table_fast(page, col_boundaries=None):
    """
    Ultra-fast C-level text layout parser using page.get_text('words').
    Extracts word coordinate tuples (x0, y0, x1, y1, text) directly from MuPDF C-engine.
    Groups words into lines by y-coordinate tolerance and bins into columns by x-coordinate.
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, text, block_no, line_no, word_no)
    if not words:
        return []

    # Group words into line buckets (2.5pt y-tolerance)
    lines = {}
    for w in words:
        y_key = round(w[1] / 2.5) * 2.5
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(w)

    rows = []
    sorted_y = sorted(lines.keys())

    if col_boundaries and len(col_boundaries) > 1:
        # Bin words into explicit column boundaries [x0, x1, x2, ...]
        for y in sorted_y:
            line_words = sorted(lines[y], key=lambda x: x[0])
            row_cells = [[] for _ in range(len(col_boundaries) - 1)]
            for w in line_words:
                x_mid = (w[0] + w[2]) / 2.0
                for c_idx in range(len(col_boundaries) - 1):
                    if col_boundaries[c_idx] <= x_mid < col_boundaries[c_idx + 1]:
                        row_cells[c_idx].append(w[4])
                        break
            row_str = [" ".join(cell) for cell in row_cells]
            if any(c.strip() for c in row_str):
                rows.append(row_str)
    else:
        # Dynamic gap-based column binning for borderless table layouts
        for y in sorted_y:
            line_words = sorted(lines[y], key=lambda x: x[0])
            # Merge adjacent words into cell tokens if x gap < 12pt
            cells = []
            curr_cell = []
            last_x1 = -1.0
            for w in line_words:
                if last_x1 >= 0 and (w[0] - last_x1) > 12.0:
                    cells.append(" ".join(curr_cell))
                    curr_cell = [w[4]]
                else:
                    curr_cell.append(w[4])
                last_x1 = w[2]
            if curr_cell:
                cells.append(" ".join(curr_cell))
            if any(c.strip() for c in cells):
                rows.append(cells)
                
    return rows

def _extract_page_table_fitz_fast(page, is_icici: bool, icici_vertical_lines: list = None):
    """
    Hybrid PyMuPDF extractor: Uses ultra-fast C word-binning for explicit vertical lines (ICICI),
    with fallback to PyMuPDF find_tables().
    """
    if is_icici and icici_vertical_lines:
        grid = parse_words_table_fast(page, icici_vertical_lines)
        if grid and len(grid) > 1:
            return [grid]

    # Primary vector find_tables
    extracted_tables = []
    try:
        tabs = page.find_tables()
        if tabs and tabs.tables:
            for tab in tabs.tables:
                grid = tab.extract()
                if grid and len(grid) > 1:
                    extracted_tables.append(grid)

        if not extracted_tables and not is_icici:
            tabs_text = page.find_tables(vertical_strategy="text", horizontal_strategy="lines")
            if tabs_text and tabs_text.tables:
                for tab in tabs_text.tables:
                    grid = tab.extract()
                    if grid:
                        extracted_tables.append(grid)
    except:
        pass

    if not extracted_tables:
        grid = parse_words_table_fast(page)
        if grid and len(grid) > 1:
            extracted_tables.append(grid)

    return extracted_tables

def mp_worker_fast(args):
    file_path_str, page_indices, is_icici, icici_vertical_lines = args
    doc = fitz.open(file_path_str)
    page_tables = []
    for page_idx in page_indices:
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        tables = _extract_page_table_fitz_fast(page, is_icici, icici_vertical_lines)
        for t in tables:
            if t:
                page_tables.append((page_idx, t))
    doc.close()
    return page_tables

def benchmark_fast_extraction():
    import glob
    pdf_files = sorted(glob.glob('uploads/*.pdf'))
    
    print("=" * 90)
    print("        ULTRA-FAST PyMuPDF WORD-BINNING TABLE EXTRACTION BENCHMARK")
    print("=" * 90)
    print(f"{'Filename':<22} | {'Pages':<6} | {'Raw Extracted Time':<20} | {'Pages / Sec':<12}")
    print("-" * 90)
    
    icici_lines = [20.0, 60.0, 115.0, 190.0, 415.0, 460.0, 525.0, 575.0]
    
    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        is_icici = "icici" in filename.lower()
        
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()
        
        num_workers = min(os.cpu_count() or 4, 16)
        chunk_size = math.ceil(total_pages / num_workers)
        chunks = [(pdf_path, list(range(i, min(i + chunk_size, total_pages))), is_icici, icici_lines) for i in range(0, total_pages, chunk_size)]
        
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=num_workers) as ex:
            results = list(ex.map(mp_worker_fast, chunks))
        dt = time.time() - t0
        
        pages_per_sec = total_pages / dt
        print(f"{filename:<22} | {total_pages:<6} | {dt:.3f} seconds       | {pages_per_sec:.1f} p/s")
    print("=" * 90)

if __name__ == '__main__':
    benchmark_fast_extraction()
