"""
Score any bank statement without a labelled answer key.

Our six sample statements are also our test set, so the suite structurally
cannot detect a regression on a bank we have never seen. This harness closes
that gap: it grades a statement on evidence the document supplies about itself,
so it works on files nobody has ever looked at.

    python tools/evaluate_statements.py ../Real_Data
    python tools/evaluate_statements.py ~/statements --bank "Canara Bank"
    python tools/evaluate_statements.py ../Real_Data --json report.json

Three independent signals, none of which needs a human:

  fidelity    do the parsed rows agree with the totals, balances and counts the
              statement prints? (the strongest signal, and the only one whose
              reference values are not derived from our own extraction)
  chain       does every row satisfy balance = previous - debit + credit?
  coverage    what share of transactions were categorised by a rule rather than
              falling through to the model?

A statement that reads UNVERIFIED is not a failure -- some banks print nothing
to check against. It is a statement whose numbers we cannot corroborate, which
is worth knowing before anyone lends against them.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FE_DIR = REPO_ROOT / "Feature Extraction"
for p in (str(REPO_ROOT), str(FE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

RENAME = {"Date": "date", "Description": "description", "Withdrawal Amt.": "debit",
          "Deposit Amt.": "credit", "Closing Balance": "balance"}


def evaluate(pdf_path: Path, bank: str = None, password: str = None) -> dict:
    """Grade one statement. Never raises -- a crash is itself a result."""
    from extractor import StandalonePDFExtractor
    from src.utils import extraction_fidelity as ef
    from src.utils.anchors import extract_anchors
    from src.utils.validation import validate_and_clean

    result = {"file": pdf_path.name, "bank": bank, "status": "ok", "error": None,
              "rows": 0, "fidelity": None, "failed_checks": [], "anchors_found": 0,
              "chain_breaks": None, "deterministic_pct": None, "template_fallback": None}

    extractor = StandalonePDFExtractor()
    try:
        detected = bank or extractor.detect_bank(pdf_path, password)
        result["bank"] = detected

        raw = extractor.extract_with_template(pdf_path, detected, password)
        diagnostics = raw.attrs.get("extraction_diagnostics", {})
        result["template_fallback"] = diagnostics.get("template_fallback")
        result["rows"] = len(raw)
        if raw.empty:
            result["status"] = "no_rows"
            return result

        df, stats = validate_and_clean(raw.rename(columns=RENAME), detected)
        result["rows"] = len(df)
        result["chain_breaks"] = stats.get("balance_chain_mismatches")

        report = ef.check(df, extract_anchors(pdf_path, password), {**stats, **diagnostics})
        result["fidelity"] = report["status"]
        result["anchors_found"] = report["anchors_found"]
        result["failed_checks"] = [c["check"] for c in report["checks"] if not c["passed"]]

        # Classification coverage, when the pipeline is available.
        try:
            from src.classifier import TransactionClassifier

            classified = TransactionClassifier().classify_dataframe(df.copy(), detected)
            methods = classified["classification_method"].astype(str)
            non_deterministic = {"slm", "slm_low_confidence", "none", ""}
            result["deterministic_pct"] = round(
                float((~methods.isin(non_deterministic)).sum()) / len(classified) * 100, 1
            )
        except Exception as e:
            result["deterministic_pct"] = None
            result.setdefault("notes", []).append(f"classification skipped: {e}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a PDF, or a directory of PDFs")
    ap.add_argument("--bank", default=None, help="force a template instead of auto-detecting")
    ap.add_argument("--password", default=None, help="password for encrypted statements")
    ap.add_argument("--json", default=None, help="also write the full report here")
    args = ap.parse_args()

    target = Path(args.path).expanduser()
    if target.is_dir():
        pdfs = sorted(p for p in target.iterdir() if p.suffix.lower() == ".pdf")
    elif target.exists():
        pdfs = [target]
    else:
        print(f"No such path: {target}")
        return 2

    if not pdfs:
        print(f"No PDFs found in {target}")
        return 2

    results = [evaluate(p, args.bank, args.password) for p in pdfs]

    header = f"{'FILE':<22} {'BANK':<15} {'ROWS':>6} {'FIDELITY':<11} {'CHAIN':>6} {'RULES%':>7}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        fidelity = r["fidelity"] or r["status"].upper()
        chain = "-" if r["chain_breaks"] is None else str(r["chain_breaks"])
        pct = "-" if r["deterministic_pct"] is None else f"{r['deterministic_pct']:.1f}"
        print(f"{r['file'][:22]:<22} {str(r['bank'])[:15]:<15} {r['rows']:>6} "
              f"{fidelity:<11} {chain:>6} {pct:>7}")
        if r["failed_checks"]:
            print(f"{'':<22} failed: {', '.join(r['failed_checks'])}")
        if r["error"]:
            print(f"{'':<22} error: {r['error']}")

    verified = sum(r["fidelity"] == "VERIFIED" for r in results)
    failed = sum(r["fidelity"] == "FAILED" for r in results)
    unverified = sum(r["fidelity"] == "UNVERIFIED" for r in results)
    broken = sum(r["status"] != "ok" for r in results)
    print("-" * len(header))
    print(f"{len(results)} statement(s): {verified} verified, {failed} contradicted, "
          f"{unverified} unverifiable, {broken} could not be read")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"Full report written to {args.json}")

    # Non-zero when a statement's parsed figures contradict the document, or it
    # could not be read at all. UNVERIFIED is not an error.
    return 1 if (failed or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
