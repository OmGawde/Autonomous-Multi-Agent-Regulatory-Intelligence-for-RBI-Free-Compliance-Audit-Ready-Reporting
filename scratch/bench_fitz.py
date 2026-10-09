import os
import time
import math
import glob
import fitz
from concurrent.futures import ProcessPoolExecutor

def parse_fitz_chunk(args):
    file_path, page_indices, is_icici, icici_vertical_lines = args
    doc = fitz.open(file_path)
    res = []
    for idx in page_indices:
        if idx >= len(doc):
            continue
        page = doc[idx]
        if is_icici:
            tabs = page.find_tables(vertical_strategy='explicit', vertical_lines=icici_vertical_lines)
        else:
            tabs = page.find_tables()
            if not tabs or not tabs.tables:
                tabs = page.find_tables(vertical_strategy='text', horizontal_strategy='lines')
        for t in (tabs.tables if tabs else []):
            extracted = t.extract()
            if extracted:
                res.append((idx, extracted))
    doc.close()
    return res

def main():
    pdf_files = glob.glob('uploads/*.pdf')
    for pdf_path in pdf_files:
        doc = fitz.open(pdf_path)
        total = len(doc)
        doc.close()
        is_icici = 'icici' in pdf_path.lower()
        icici_lines = [20.0, 60.0, 115.0, 190.0, 415.0, 460.0, 525.0, 575.0]
        
        num_workers = min(os.cpu_count() or 4, 16)
        chunk_size = math.ceil(total / num_workers)
        chunks = [(pdf_path, list(range(i, min(i+chunk_size, total))), is_icici, icici_lines) for i in range(0, total, chunk_size)]
        
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=num_workers) as ex:
            results = ex.map(parse_fitz_chunk, chunks)
            all_tables = [t for sub in results for t in sub]
        dt = time.time() - t0
        print(f"{os.path.basename(pdf_path)} ({total} pages): extracted {len(all_tables)} page-tables in {dt:.3f}s")

if __name__ == '__main__':
    main()
