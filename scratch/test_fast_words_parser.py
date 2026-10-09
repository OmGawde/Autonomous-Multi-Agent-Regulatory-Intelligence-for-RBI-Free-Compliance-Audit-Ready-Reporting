import fitz
import time
import os
import math
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

def parse_words_table(page, col_boundaries=None):
    """
    Ultra-fast C-level text layout parser using page.get_text('words').
    Groups words into lines by y-coordinate and bins into table columns by x-coordinate.
    """
    words = page.get_text("words") # (x0, y0, x1, y1, text, block_no, line_no, word_no)
    if not words:
        return []

    # Group words by line (y0 coordinate rounded to 2pt tolerance)
    lines = {}
    for w in words:
        y_key = round(w[1] / 2.5) * 2.5
        if y_key not in lines:
            lines[y_key] = []
        lines[y_key].append(w)

    rows = []
    sorted_y = sorted(lines.keys())

    if col_boundaries:
        # Use explicit column boundaries [x0, x1, x2, ...]
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
        # Simple space-based/word-line layout text grid
        for y in sorted_y:
            line_words = sorted(lines[y], key=lambda x: x[0])
            line_text = " ".join(w[4] for w in line_words)
            if line_text.strip():
                rows.append([line_text])
                
    return rows

def mp_parse_pdf_words(args):
    pdf_path, pages, col_boundaries = args
    doc = fitz.open(pdf_path)
    page_rows = []
    for p_idx in pages:
        if p_idx >= len(doc):
            continue
        page = doc[p_idx]
        grid = parse_words_table(page, col_boundaries)
        if grid:
            page_rows.append((p_idx, grid))
    doc.close()
    return page_rows

def test_icici_speed():
    pdf_path = 'uploads/synthetic_icici.pdf'
    icici_vertical_lines = [20.0, 60.0, 115.0, 190.0, 415.0, 460.0, 525.0, 575.0]
    
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    
    num_workers = min(os.cpu_count() or 4, 16)
    chunk_size = math.ceil(total_pages / num_workers)
    chunks = [(pdf_path, list(range(i, min(i + chunk_size, total_pages))), icici_vertical_lines) for i in range(0, total_pages, chunk_size)]
    
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=num_workers) as ex:
        results = list(ex.map(mp_parse_pdf_words, chunks))
    dt = time.time() - t0
    
    total_rows = sum(len(grid) for sub in results for p_idx, grid in sub)
    print("=" * 70)
    print(f"C-FAST PyMuPDF WORDS PARSER BENCHMARK FOR {total_pages} PAGES:")
    print(f"  Execution Time:  {dt:.3f} seconds ({total_pages/dt:.1f} pages/sec)")
    print(f"  Extracted Rows:  {total_rows:,} raw table rows")
    print("=" * 70)

if __name__ == '__main__':
    test_icici_speed()
