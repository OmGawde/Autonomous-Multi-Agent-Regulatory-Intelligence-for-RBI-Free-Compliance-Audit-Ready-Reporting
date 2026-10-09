import fitz
import glob

def extract_smart_fitz(page):
    # Try default first
    tabs = page.find_tables()
    grids = []
    if tabs and tabs.tables:
        for t in tabs.tables:
            g = t.extract()
            if g and len(g) > 1:
                grids.append(g)
                
    # Check if grids are degenerate:
    # 1. No tables found
    # 2. Only 1-2 data rows but cells have lots of newlines (collapsed rows)
    is_degenerate = False
    if not grids:
        is_degenerate = True
    else:
        # Check for multi-line lumped cells
        for g in grids:
            for r in g[1:min(5, len(g))]:
                if any(isinstance(c, str) and c.count('\n') >= 3 for c in r if c):
                    is_degenerate = True
                    break
            if is_degenerate:
                break
                
    if is_degenerate:
        # Try horizontal_strategy="text"
        tabs_htext = page.find_tables(horizontal_strategy="text")
        grids_htext = [t.extract() for t in tabs_htext.tables if t.extract() and len(t.extract()) > 2]
        if grids_htext and max(len(g) for g in grids_htext) > (max(len(g) for g in grids) if grids else 0):
            return grids_htext
            
        # Try vertical_strategy="text", horizontal_strategy="text"
        tabs_vhtext = page.find_tables(vertical_strategy="text", horizontal_strategy="text")
        grids_vhtext = [t.extract() for t in tabs_vhtext.tables if t.extract() and len(t.extract()) > 2]
        if grids_vhtext and max(len(g) for g in grids_vhtext) > (max(len(g) for g in grids) if grids else 0):
            return grids_vhtext
            
    return grids

files = sorted(glob.glob("New_Data/**/*.pdf", recursive=True))

for f in files:
    doc = fitz.open(f)
    if len(doc) == 0:
        continue
    page = doc[0]
    res = extract_smart_fitz(page)
    row_counts = [len(g) for g in res]
    print(f"{f}: {len(doc)} pages | p0 tables: {row_counts}")
    doc.close()
