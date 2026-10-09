"""
Shared recurrence detection.

Most of what a bank statement will not tell you in words, it tells you in shape.
A narration like `BIL/NEFT/ICICN.../SURYODAYA /ABHYUDAYA CO-OP` names nothing --
the bank truncated the payee at 10 characters and the identifying token is gone
before the PDF is written. But twelve payments of Rs 1,300 arriving 31 days apart
are unmistakably a standing obligation, and that is the fact a lender needs.

Measured on the current corpus: 79.9% of unresolved debit value sits in a
counterparty group with three or more payments.

Two deliberate departures from the reference implementation in
the recurring-payment specification:

1. **Median inter-arrival gap, not mean.** The reference computes `avg_interval`,
   requires it to fall in 25-35 days, and only then counts missed payments. That
   is self-defeating: a group with missed months has its mean dragged outside the
   window, so it is rejected and the misses are never counted -- precisely the
   risk-relevant case. One real statement pays Rs 50,000 monthly with two months
   missed; mean gap 47.6 (rejected), median gap 32.0 (accepted, 4 misses found).

2. **Piecewise-constant amounts, not one tolerance band.** Standing obligations
   get revised: 1300 -> 1325 (+1.9%), 1884 -> 2043 -> 2206, 20000 -> 25000 ->
   50000. A single global tolerance (or a coefficient of variation) treats the
   revision as noise and demotes the group to "variable", which is backwards --
   the step is itself evidence of an administered price. Amounts are segmented
   into runs and each run must be internally consistent.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Defaults follow the recurring-payment specification where they are not actively harmful.
DEFAULTS = {
    "min_occurrences": 3,
    "amount_tolerance_pct": 5.0,     # within a constant run
    "amount_tolerance_abs": 50.0,    # floor, so small amounts are not over-strict
    "cadence_monthly_min": 25.0,
    "cadence_monthly_max": 35.0,
    "cadence_quarterly_min": 80.0,
    "cadence_quarterly_max": 100.0,
    "cadence_weekly_min": 5.0,
    "cadence_weekly_max": 9.0,
    "nominal_month_days": 30.0,
    "min_run_length": 2,             # a "step" needs at least this many either side
    "max_amount_runs": 3,            # more runs than this means several payments, not one revised obligation
}

MONTHLY = "MONTHLY"
QUARTERLY = "QUARTERLY"
WEEKLY = "WEEKLY"
IRREGULAR = "IRREGULAR"


@dataclass
class RecurringGroup:
    """One counterparty's repeating payment pattern."""

    key: str
    cadence: str                     # MONTHLY / QUARTERLY / WEEKLY / IRREGULAR
    occurrences: int
    median_amount: float
    total_amount: float
    median_gap_days: float
    first_date: pd.Timestamp
    last_date: pd.Timestamp
    is_fixed: bool                   # amounts constant, allowing for revisions
    amount_steps: List[float] = field(default_factory=list)
    expected_occurrences: int = 0
    missed: int = 0
    regularity_pct: float = 100.0
    confidence: float = 0.0
    indices: List[Any] = field(default_factory=list)

    @property
    def has_revision(self) -> bool:
        return len(self.amount_steps) > 1

    def describe(self) -> str:
        cadence = self.cadence.lower()
        base = f"{self.occurrences} payments of ~{self.median_amount:,.0f} ({cadence})"
        if self.has_revision:
            steps = " -> ".join(f"{s:,.0f}" for s in self.amount_steps)
            base += f", revised {steps}"
        if self.missed:
            base += f", {self.missed} missed"
        return base


def _segment_constant_runs(amounts: List[float], pct_tol: float, abs_tol: float,
                           min_run: int) -> List[List[float]]:
    """
    Split a sequence into runs of (near-)constant value.

    A new run starts when a value departs from the current run's reference by
    more than the tolerance. Runs shorter than `min_run` are folded back into the
    preceding run, so a single outlier does not manufacture a false "revision".
    """
    if not amounts:
        return []

    runs: List[List[float]] = [[amounts[0]]]
    for value in amounts[1:]:
        ref = float(np.median(runs[-1]))
        allowed = max(abs_tol, ref * pct_tol / 100.0)
        if abs(value - ref) <= allowed:
            runs[-1].append(value)
        else:
            runs.append([value])

    # A series where almost every value starts its own run is not stepped, it is
    # simply noisy -- folding there would collapse wildly different amounts into
    # one bogus "run". Only fold when the runs look like a real ladder.
    singletons = sum(1 for r in runs if len(r) < min_run)
    if singletons > len(runs) / 2:
        return runs

    merged: List[List[float]] = []
    for run in runs:
        if merged and len(run) < min_run:
            merged[-1].extend(run)
        else:
            merged.append(run)
    return merged


def _detect_level_shift(amounts: List[float], min_shift_pct: float = 1.0) -> List[float]:
    """
    Find a sustained change in level, e.g. 1300 -> 1325.

    Kept separate from the grouping tolerance on purpose. Grouping has to be
    loose enough that a re-rated charge stays one obligation (a 5% band), but
    that same band is far too wide to *notice* a 1.9% annual revision. This looks
    instead for a step that persists: the series is split at each point and a
    split counts only when both sides are internally tight and their levels
    differ by more than `min_shift_pct`.

    Returns the level of each segment, or [] when the level never shifts.
    """
    n = len(amounts)
    if n < 4:
        return []

    def tight(values: List[float]) -> bool:
        med = float(np.median(values))
        return med > 0 and (max(values) - min(values)) / med <= min_shift_pct / 100.0

    for cut in range(2, n - 1):
        left, right = amounts[:cut], amounts[cut:]
        if not (tight(left) and tight(right)):
            continue
        lmed, rmed = float(np.median(left)), float(np.median(right))
        if lmed <= 0:
            continue
        if abs(rmed - lmed) / lmed * 100.0 >= min_shift_pct:
            return [round(lmed, 2), round(rmed, 2)]
    return []


def _classify_cadence(median_gap: float, cfg: Dict[str, Any]) -> str:
    if cfg["cadence_weekly_min"] <= median_gap <= cfg["cadence_weekly_max"]:
        return WEEKLY
    if cfg["cadence_monthly_min"] <= median_gap <= cfg["cadence_monthly_max"]:
        return MONTHLY
    if cfg["cadence_quarterly_min"] <= median_gap <= cfg["cadence_quarterly_max"]:
        return QUARTERLY
    return IRREGULAR


def detect_recurring_groups(
    df: pd.DataFrame,
    *,
    key_col: str,
    amount_col: str,
    date_col: str = "date",
    config: Optional[Dict[str, Any]] = None,
    min_occurrences: Optional[int] = None,
    require_fixed: bool = False,
    cadences: Optional[List[str]] = None,
) -> List[RecurringGroup]:
    """
    Group rows by `key_col` and describe each group's repeating structure.

    Args:
        key_col: counterparty / lender / amount-bucket column to group on
        amount_col: "debit" or "credit"
        require_fixed: keep only groups whose amounts are piecewise constant
        cadences: keep only these cadences (e.g. [MONTHLY]); None keeps all

    Returns every qualifying group. Callers apply their own reduction -- income
    takes the largest by value, investment counts them, debt builds facilities.
    """
    cfg = {**DEFAULTS, **(config or {})}
    floor = min_occurrences if min_occurrences is not None else cfg["min_occurrences"]

    required = {key_col, amount_col, date_col}
    if df.empty or not required.issubset(df.columns):
        return []

    work = df.copy()
    work[key_col] = work[key_col].fillna("").astype(str).str.strip()
    work = work[work[key_col] != ""]
    work["_date"] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=["_date"])
    work = work[pd.to_numeric(work[amount_col], errors="coerce").fillna(0) > 0]
    if work.empty:
        return []

    groups: List[RecurringGroup] = []
    for key, grp in work.groupby(key_col):
        if len(grp) < floor:
            continue

        grp = grp.sort_values("_date")
        amounts = [float(a) for a in grp[amount_col]]
        median_amount = float(np.median(amounts))
        if median_amount <= 0:
            continue

        runs = _segment_constant_runs(
            amounts, cfg["amount_tolerance_pct"], cfg["amount_tolerance_abs"],
            int(cfg["min_run_length"]),
        )
        # "Fixed" means the amount holds constant, allowing for a small number of
        # administered revisions. The run count is capped hard: a genuine
        # standing obligation is revised once or twice over a statement, so many
        # runs means this key mixes several different payments rather than one
        # obligation being re-rated. Without the cap, 181 mutual-fund SIPs of
        # assorted amounts to one broker were reported as a 42-step "revision".
        runs_consistent = all(
            max(r) - min(r) <= max(cfg["amount_tolerance_abs"],
                                   float(np.median(r)) * cfg["amount_tolerance_pct"] / 100.0)
            for r in runs
        )
        is_fixed = runs_consistent and len(runs) <= int(cfg["max_amount_runs"])

        if require_fixed and not is_fixed:
            continue

        gaps = grp["_date"].diff().dt.days.dropna()
        if gaps.empty:
            continue
        median_gap = float(gaps.median())
        cadence = _classify_cadence(median_gap, cfg)
        if cadences and cadence not in cadences:
            continue

        span_days = (grp["_date"].max() - grp["_date"].min()).days
        if cadence == MONTHLY and span_days > 0:
            expected = int(round(span_days / cfg["nominal_month_days"])) + 1
        elif median_gap > 0 and span_days > 0:
            expected = int(round(span_days / median_gap)) + 1
        else:
            expected = len(grp)
        expected = max(expected, len(grp))
        missed = max(0, expected - len(grp))
        regularity = round(len(grp) / expected * 100.0, 2) if expected else 100.0

        # Confidence rises with occurrences and regularity, falls with amount
        # spread. Deliberately conservative -- this feeds a suggestion, not a
        # label.
        conf = min(1.0, 0.35 + 0.08 * len(grp))
        if is_fixed:
            conf += 0.15
        if cadence != IRREGULAR:
            conf += 0.10
        conf *= regularity / 100.0
        conf = round(min(max(conf, 0.0), 0.95), 2)

        groups.append(RecurringGroup(
            key=str(key),
            cadence=cadence,
            occurrences=len(grp),
            median_amount=round(median_amount, 2),
            total_amount=round(float(sum(amounts)), 2),
            median_gap_days=round(median_gap, 1),
            first_date=grp["_date"].min(),
            last_date=grp["_date"].max(),
            is_fixed=bool(is_fixed),
            # Report a revision only for a sustained level shift. The grouping
            # tolerance is deliberately wider than a typical revision, so the
            # run boundaries alone cannot see one.
            amount_steps=(_detect_level_shift(amounts) if is_fixed else []),
            expected_occurrences=expected,
            missed=missed,
            regularity_pct=regularity,
            confidence=conf,
            indices=list(grp.index),
        ))

    groups.sort(key=lambda g: -g.total_amount)
    return groups


def summarise(groups: List[RecurringGroup]) -> Dict[str, Any]:
    """Statement-level view of every detected obligation."""
    monthly = [g for g in groups if g.cadence == MONTHLY]
    return {
        "recurring_group_count": len(groups),
        "monthly_obligation_count": len(monthly),
        "monthly_obligation_total": round(sum(g.median_amount for g in monthly), 2),
        "total_recurring_value": round(sum(g.total_amount for g in groups), 2),
        "missed_payment_count": sum(g.missed for g in groups),
        "obligations": [
            {
                "counterparty": g.key,
                "cadence": g.cadence,
                "amount": g.median_amount,
                "occurrences": g.occurrences,
                "total": g.total_amount,
                "missed": g.missed,
                "regularity_pct": g.regularity_pct,
                "has_revision": g.has_revision,
                "amount_steps": g.amount_steps,
                "confidence": g.confidence,
                "description": g.describe(),
            }
            for g in groups
        ],
    }
