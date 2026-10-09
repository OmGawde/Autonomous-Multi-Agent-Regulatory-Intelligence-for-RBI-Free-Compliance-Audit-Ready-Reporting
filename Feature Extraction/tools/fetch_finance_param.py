"""Download BharatGen FinanceParam weights for fully offline use.

Run once per machine:

    cd "Feature Extraction"
    python -m tools.fetch_finance_param

Everything afterwards loads from disk -- `ParamModelLoader` passes
`local_files_only=True`, so the pipeline never reaches the network at runtime.

Why this exists: the adapter previously pointed at the hub id
"bharatgen/param-1-finance", which is not a real repository (the organisation is
`bharatgenai` and the model is `FinanceParam`). Every load failed and silently
fell through to the keyword heuristic, so the "Param-Finance" branding in the
UI never corresponded to a model. Vendoring the weights locally, next to the
DistilBERT classifier that is already bundled, removes both the wrong id and the
runtime network dependency.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ID = "bharatgenai/FinanceParam"
TARGET = Path(__file__).resolve().parents[1] / "models" / "finance-param"

# ~5.8 GB of weights, plus the tokenizer and the custom modelling code that
# `trust_remote_code=True` executes. The stale tokenizer_config backup in the
# repo is skipped.
IGNORE = ["*.bak", ".gitattributes"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=str(TARGET), help="destination directory")
    parser.add_argument("--repo", default=REPO_ID, help="HuggingFace repo id")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is required: pip install huggingface_hub", file=sys.stderr)
        return 1

    target = Path(args.target)
    print(f"Downloading {args.repo} -> {target}")
    print("About 5.8 GB; this is a one-time fetch.")

    path = snapshot_download(
        args.repo,
        local_dir=str(target),
        ignore_patterns=IGNORE,
        max_workers=4,
    )

    weights = sorted(Path(path).glob("*.safetensors"))
    if not weights:
        print("No .safetensors found after download -- the fetch is incomplete.", file=sys.stderr)
        return 1

    total = sum(w.stat().st_size for w in weights)
    print(f"Done. {len(weights)} shard(s), {total / 1e9:.2f} GB at {path}")
    print("The pipeline will pick these up automatically on next start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
