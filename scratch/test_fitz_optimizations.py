import fitz
import time
import os
import math
from concurrent.futures import ProcessPoolExecutor

def parse_words_page(args):
    pdf_path, pages = args
    doc = fitz.open(pdf_path)
    res = []
    for p_idx in pages:
        page = doc[p_idx]
        words = page.get_text("words")  # returns list of (x0, y0, x1, y1, "word", block_no, line_no, word_no)
        res.append((p_idx, words))
    doc.close()
    return res

def parse_tables_fast(args):
    pdf_path, pages = args
    doc = fitz.open(pdf_path)
    res = []
    for p_idx in pages:
        page = doc[p_idx]
        tabs = page.find_tables(strategy="lines", snap_tolerance=1, edge_min_length=10)
        grids = [t.extract() for t in tabs.tables] if tabs else []
        res.append((p_idx, grids))
    doc.close()
    return res

if __name__ == '__main__':
    pdf_path = 'uploads/synthetic_icici.pdf'
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    
    num_workers = min(os.cpu_count() or 4, 16)
    chunk_size = math.ceil(total_pages / num_workers)
    chunks = [(pdf_path, list(range(i, min(i + chunk_size, total_pages)))) for i in range(0, total_pages, chunk_size)]
    
    # Method A: get_text("words") in parallel
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=num_workers) as ex:
        res_words = list(ex.map(parse_words_page, chunks))
    t_words_mp = time.time() - t0
    
    # Method B: find_tables(snap_tolerance=1, edge_min_length=10) in parallel
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=num_workers) as ex:
        res_tables = list(ex.map(parse_tables_fast, chunks))
    t_tables_mp = time.time() - t0
    
    print("=" * 60)
    print(f"BENCHMARK RESULTS FOR {total_pages} PAGES ({num_workers} WORKERS):")
    print(f"  1. Parallel get_text('words'): {t_words_mp:.3f} seconds ({total_pages/t_words_mp:.1f} pages/sec)")
    print(f"  2. Parallel find_tables(fast): {t_tables_mp:.3f} seconds ({total_pages/t_tables_mp:.1f} pages/sec)")
    print("=" * 60)
