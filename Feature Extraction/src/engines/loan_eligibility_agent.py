"""Module 11 — Loan Eligibility & Sizing Agent.

Computes maximum allowable borrowing capacity and sanction term sheet using:
1. Salaried Sizing: FOIR headroom against policy cap, converted to present value.
2. MSME / Business Sizing: True Turnover surrogate (18%) & ADB Multiplier (3.0x).
3. Liquid Asset Buffer: Investment & savings cushion bonus (+5% to +15% headroom).
4. Risk & Dishonour Haircuts: Automatic constraint on low scores or inward bounces.

Every figure this module reads comes from another engine's published output, so
the key names below must match what those engines actually emit -- see
`_pick()` for why that is spelled out rather than assumed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Coerce an engine-published value to a float, or `default` if unusable.

    Two shapes make a bare `float()` unsafe here:

    * Several engines publish a figure as a `{month: value}` series rather than
      a scalar -- `balance.average_monthly_balance` is twelve months of them.
      `float()` on a dict raises TypeError. This module used to do exactly that,
      and the caller's blanket `except` swallowed the raise and substituted a
      hardcoded zero term sheet, so every application in the system rendered a
      fabricated "Standard Review / 48 months / 12% / Rs 0" offer. Mean the
      series instead, which is what a monthly average of monthly averages is.
    * `FeatureFormatter` wraps some values as `{"value": x, "confidence": y}`.

    Booleans are rejected rather than silently counted as 1.0.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        # A formatter envelope carries the real figure under "value".
        if "value" in value:
            return _num(value["value"], default)
        nums = [
            float(v) for v in value.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        return (sum(nums) / len(nums)) if nums else default
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("₹", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def _pick(mapping: Dict[str, Any], *keys: str) -> Optional[float]:
    """First key in `keys` that yields a usable number, else None.

    Callers list the key the engine really publishes first, then any historical
    alias. The aliases are not decoration: this module was originally written
    against key names no engine ever emitted (`average_monthly_income`,
    `total_emi_amount`, `total_savings`, `mean_balance`), and the unit tests
    were written from the same assumption -- so the suite passed while
    production read 0.0 for every sizing input. Keeping the aliases means the
    fixtures and any external caller still resolve.
    """
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping:
            got = _num(mapping[key])
            if got is not None:
                return got
    return None


def _present_value(monthly_emi: float, annual_roi_pct: float, tenure_months: int) -> float:
    """Calculate the present value (principal loan amount) for a given monthly EMI."""
    if monthly_emi <= 0 or tenure_months <= 0:
        return 0.0
    r = (annual_roi_pct / 100.0) / 12.0
    if r <= 0:
        return monthly_emi * tenure_months
    factor = (1.0 - (1.0 + r) ** (-tenure_months)) / r
    return round(monthly_emi * factor, 2)


def _emi_for(principal: float, annual_roi_pct: float, tenure_months: int) -> float:
    """Monthly instalment amortising `principal` over `tenure_months`."""
    if principal <= 0 or tenure_months <= 0:
        return 0.0
    r = (annual_roi_pct / 100.0) / 12.0
    if r <= 0:
        return round(principal / tenure_months, 2)
    growth = (1.0 + r) ** tenure_months
    return round(principal * r * growth / (growth - 1.0), 2)


def _to_10k(amount: float) -> float:
    """Sanction amounts are quoted in multiples of Rs 10,000."""
    return round(amount / 10000.0) * 10000.0


def _no_facility(reason: str, **extra: Any) -> Dict[str, Any]:
    """Term sheet for an application that must not be offered a facility."""
    sheet = {
        "eligibility_status": "NO_FACILITY",
        "recommended_loan_amount": 0.0,
        "max_eligible_limit": 0.0,
        "recommended_product": "No facility recommended",
        "recommended_tenure_months": None,
        "estimated_monthly_emi": 0.0,
        "benchmark_interest_rate": None,
        "policy_decision_rationale": reason,
    }
    sheet.update(extra)
    return sheet


def calculate_loan_eligibility(
    features: Dict[str, Any],
    requested_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate institutional loan eligibility, sanction capacity, and terms.

    Args:
        features: Aggregated bundle containing income, debt, balance, cash_flow,
                  fraud, investment, savings, and underwriting_summary.
        requested_amount: Optional applicant requested amount in INR.

    Returns:
        Structured sanction term sheet dictionary.
    """
    income = features.get("income") or {}
    debt = features.get("debt") or {}
    balance = features.get("balance") or {}
    cash_flow = features.get("cash_flow") or {}
    fraud = features.get("fraud") or {}
    investment = features.get("investment") or {}
    savings = features.get("savings") or {}
    summary = features.get("underwriting_summary") or {}

    # ------------------------------------------------------------------
    # 0. Decision gate
    # ------------------------------------------------------------------
    # The aggregator suppresses the credit score outright on critical fraud/AML
    # and issues a REJECT decision. Sizing a facility anyway -- which is what
    # happened while `summary` was empty at call time and the score silently
    # defaulted to 750 -- puts a sanction recommendation on screen for an
    # applicant the same report rejects two panels above.
    decision = str(summary.get("underwriting_decision") or "").upper()
    if decision.startswith("REJECT") or decision.startswith("DECLINE"):
        note = summary.get("decision_coherence_note") or f"Underwriting decision: {decision}."
        return _no_facility(
            f"No sanction sized: the application was declined at underwriting. {note}",
            borrower_classification="Not assessed",
            current_foir=_pick(summary, "foir_score") or _pick(debt, "foir") or 0.0,
        )

    # ------------------------------------------------------------------
    # 1. Applicant profile (salaried vs MSME commercial)
    # ------------------------------------------------------------------
    avg_monthly_income = _pick(
        income,
        "average_income",          # income engine: mean of the monthly series
        "monthly_income",          # the series itself; _num means it
        "average_monthly_income",  # legacy alias
        "monthly_income_mean",     # legacy alias
    ) or 0.0
    salary_income = _pick(income, "salary_income") or 0.0
    total_income = _pick(income, "total_income") or 0.0
    inferred_sector = (
        summary.get("inferred_business_sector")
        or (features.get("business_profiler") or {}).get("inferred_business_sector")
        or "General Commercial Enterprises"
    )

    is_salaried = False
    if total_income > 0 and (salary_income / total_income >= 0.50):
        is_salaried = True
    else:
        # `income_sources` is a count in the current engine output, not a list.
        # Only inspect it when it really is a list or a string.
        sources = income.get("income_sources")
        if isinstance(sources, (list, tuple, str)) and "salary" in str(sources).lower():
            is_salaried = True

    # ------------------------------------------------------------------
    # 2. Baseline financial indicators
    # ------------------------------------------------------------------
    true_turnover = (
        _pick(summary, "true_turnover")
        or _pick(cash_flow, "net_turnover_credit")
        or total_income
    )
    adb = _pick(
        balance,
        "average_daily_balance",     # the scalar the balance engine publishes
        "average_monthly_balance",   # a {month: value} series; _num means it
        "mean_balance",              # legacy alias
    ) or 0.0
    existing_emi = _pick(
        debt,
        "monthly_emi",                 # debt engine's monthly obligation figure
        "total_monthly_obligations",
        "total_emi_amount",            # legacy alias
        "monthly_obligations",         # legacy alias
    ) or 0.0

    # The debt engine computes FOIR over the whole statement period
    # (total fixed obligations / total true income), which is a more stable
    # basis than one month's EMI over one month's income -- and it is the
    # figure the scorecard already shows the user. Size against that same
    # number so the term sheet and the scorecard cannot disagree.
    current_foir = _pick(summary, "foir_score")
    if current_foir is None:
        current_foir = _pick(debt, "foir")
    if current_foir is None:
        current_foir = (existing_emi / avg_monthly_income) if avg_monthly_income > 0 else 0.0
    current_foir = max(0.0, float(current_foir))

    credit_score = _pick(summary, "credit_score")
    if credit_score is None:
        # Absent because this bundle has no summary yet (a direct caller), not
        # because scoring was suppressed -- that path returned above.
        credit_score = 750.0
    inward_bounces = int(
        _pick(summary, "inward_bounce_count") or _pick(fraud, "inward_bounce_count") or 0
    )
    volatility = str(
        summary.get("volatility_band") or balance.get("volatility_band") or "MODERATE"
    ).upper()

    # ------------------------------------------------------------------
    # 3. Sizing
    # ------------------------------------------------------------------
    if is_salaried:
        max_foir_policy = 0.60 if avg_monthly_income >= 100000.0 else 0.50
        # Headroom expressed in FOIR terms, so post-sanction FOIR lands exactly
        # on the policy cap rather than somewhere unrelated to the published one.
        foir_headroom = max(0.0, max_foir_policy - current_foir)
        max_allowable_emi = avg_monthly_income * foir_headroom
        benchmark_rate = 12.0
        tenure_months = 48
        product_name = "Unsecured Personal Loan"

        raw_sanction = _present_value(max_allowable_emi, benchmark_rate, tenure_months)
        max_limit = _present_value(max_allowable_emi, benchmark_rate, 60)  # 5-year stretch
    else:
        max_foir_policy = 0.65
        turnover_capacity = true_turnover * 0.18   # 18% of true annual turnover
        adb_capacity = adb * 3.0                   # 3x average daily balance

        raw_sanction = max(turnover_capacity, adb_capacity)
        benchmark_rate = 13.5                      # MSME unsecured
        tenure_months = 36 if volatility in ("HIGH", "SEVERE") else 48
        product_name = (
            "MSME Working Capital Dropline Overdraft" if volatility == "LOW"
            else "MSME Business Term Loan"
        )
        max_limit = raw_sanction * 1.25
        max_allowable_emi = _emi_for(raw_sanction, benchmark_rate, tenure_months)

    raw_sanction = _to_10k(raw_sanction)
    max_limit = _to_10k(max_limit)

    # ------------------------------------------------------------------
    # 4. Liquid wealth cushion
    # ------------------------------------------------------------------
    liquid_investments = _pick(investment, "total_investment", "total_investments") or 0.0
    # The savings engine publishes a monthly *flow* (`average_savings`), not a
    # balance, and it goes negative on a deficit account. Annualise only the
    # positive part -- a negative flow is not a liability against wealth here,
    # it is already reflected in the balance and FOIR inputs.
    monthly_savings_flow = _pick(savings, "average_savings") or 0.0
    savings_accumulated = max(0.0, monthly_savings_flow) * 12.0
    legacy_savings_stock = _pick(savings, "total_savings")
    if legacy_savings_stock is not None:
        savings_accumulated = legacy_savings_stock
    sip_annualized = (_pick(investment, "monthly_sip_amount") or 0.0) * 12.0
    total_liquid_wealth = liquid_investments + savings_accumulated + sip_annualized

    asset_cushion_score = "LIMITED"
    enhancement_bonus_pct = 0.0
    rate_discount = 0.0

    if raw_sanction > 0 and total_liquid_wealth >= raw_sanction * 1.5:
        asset_cushion_score = "STRONG"
        enhancement_bonus_pct = 15.0
        rate_discount = 0.50  # 50 bps
    elif raw_sanction > 0 and total_liquid_wealth >= raw_sanction * 0.5:
        asset_cushion_score = "MODERATE"
        enhancement_bonus_pct = 5.0
        rate_discount = 0.25

    final_rate = max(9.5, benchmark_rate - rate_discount)
    enhanced_sanction = _to_10k(raw_sanction * (1.0 + (enhancement_bonus_pct / 100.0)))

    # ------------------------------------------------------------------
    # 5. Risk & dishonour haircuts
    # ------------------------------------------------------------------
    risk_haircut_pct = 0.0
    haircut_reasons = []

    if inward_bounces >= 2:
        risk_haircut_pct = 80.0
        haircut_reasons.append(
            f"{inward_bounces} inward cheque/NACH dishonours detected (severe default risk)"
        )
    elif inward_bounces == 1:
        risk_haircut_pct = 20.0
        haircut_reasons.append("1 inward dishonour event detected (precautionary covenant applied)")

    if credit_score < 500:
        risk_haircut_pct = max(risk_haircut_pct, 70.0)
        haircut_reasons.append(f"Credit score {credit_score:.0f} below standard prime cutoff")
    elif credit_score < 650:
        risk_haircut_pct = max(risk_haircut_pct, 25.0)
        haircut_reasons.append(f"Credit score {credit_score:.0f} in moderate risk band")

    recommended_amount = _to_10k(enhanced_sanction * (1.0 - (risk_haircut_pct / 100.0)))

    if inward_bounces >= 2:
        recommended_amount = min(recommended_amount, 50000.0)

    if requested_amount is not None:
        asked = _num(requested_amount, 0.0) or 0.0
        if asked > 0:
            recommended_amount = min(recommended_amount, _to_10k(asked))

    # ------------------------------------------------------------------
    # 6. FOIR containment
    # ------------------------------------------------------------------
    # Whatever the sizing route, the proposal must not breach the policy cap it
    # is quoted against. The turnover/ADB route does not consider FOIR at all,
    # so without this an MSME sanction could be recommended at a post-loan FOIR
    # well beyond the cap printed beside it.
    effective_income = max(avg_monthly_income, true_turnover / 12.0, 1.0)
    foir_constrained = False
    if recommended_amount > 0:
        affordable_emi = max(0.0, (max_foir_policy * effective_income) - (current_foir * effective_income))
        proposed_emi = _emi_for(recommended_amount, final_rate, tenure_months)
        if proposed_emi > affordable_emi:
            capped = _to_10k(_present_value(affordable_emi, final_rate, tenure_months))
            if capped < recommended_amount:
                recommended_amount = capped
                foir_constrained = True

    final_monthly_emi = _emi_for(recommended_amount, final_rate, tenure_months)

    projected_foir = round(current_foir + (final_monthly_emi / effective_income), 4)

    # ------------------------------------------------------------------
    # 7. Rationale
    # ------------------------------------------------------------------
    borrower_type_label = (
        "Salaried professional" if is_salaried else f"MSME enterprise in {inferred_sector}"
    )
    rationale_parts = [f"Borrower profile evaluated as {borrower_type_label}."]

    if is_salaried:
        rationale_parts.append(
            f"Current FOIR of {current_foir * 100:.1f}% against a policy cap of "
            f"{max_foir_policy * 100:.0f}% leaves {max(0.0, max_foir_policy - current_foir) * 100:.1f}% "
            f"of monthly income (Rs {max_allowable_emi:,.0f}) available for a new instalment."
        )
    else:
        rationale_parts.append(
            f"Sized on the higher of 18% of true annual turnover (Rs {true_turnover * 0.18:,.0f}) "
            f"and 3x average daily balance (Rs {adb * 3.0:,.0f})."
        )
    rationale_parts.append(
        f"Base eligibility generated at Rs {raw_sanction:,.0f} across {tenure_months} months "
        f"at {final_rate:.1f}% p.a."
    )

    if enhancement_bonus_pct > 0:
        rationale_parts.append(
            f"Liquid wealth cushion of Rs {total_liquid_wealth:,.0f} ({asset_cushion_score}) qualified "
            f"the account for a +{enhancement_bonus_pct:.0f}% limit enhancement and "
            f"{rate_discount * 100:.0f} bps pricing discount."
        )
    if risk_haircut_pct > 0:
        rationale_parts.append(
            f"Policy risk adjustment (-{risk_haircut_pct:.0f}%) applied due to: "
            f"{'; '.join(haircut_reasons)}."
        )
    if foir_constrained:
        rationale_parts.append(
            f"Sanction further constrained so post-loan FOIR stays within the "
            f"{max_foir_policy * 100:.0f}% policy cap."
        )
    if recommended_amount <= 0:
        rationale_parts.append(
            "No headroom remains under the policy debt-burden cap, so no facility is sized."
            if is_salaried and current_foir >= max_foir_policy
            else "Verified cash flows do not support a quantifiable facility."
        )
    else:
        rationale_parts.append(
            f"Projected post-sanction debt burden (FOIR) remains contained at "
            f"{projected_foir * 100:.1f}%."
        )

    return {
        "eligibility_status": "SIZED" if recommended_amount > 0 else "NO_HEADROOM",
        "recommended_loan_amount": recommended_amount,
        "max_eligible_limit": max(max_limit, recommended_amount),
        "recommended_product": product_name if recommended_amount > 0 else "No facility recommended",
        "recommended_tenure_months": tenure_months,
        "estimated_monthly_emi": final_monthly_emi,
        "benchmark_interest_rate": final_rate,
        "borrower_classification": "Salaried" if is_salaried else "MSME_Self_Employed",
        "liquid_asset_cushion_score": asset_cushion_score,
        "liquid_assets_verified": round(total_liquid_wealth, 2),
        "enhancement_bonus_pct": enhancement_bonus_pct,
        "risk_haircut_pct": risk_haircut_pct,
        "current_foir": round(current_foir, 4),
        "max_allowable_foir": max_foir_policy,
        # `post_loan_projected_foir` is the name the report UI reads; the
        # original `projected_post_foir` is kept so existing consumers and
        # stored bundles do not break.
        "post_loan_projected_foir": projected_foir,
        "projected_post_foir": projected_foir,
        "monthly_income_basis": round(effective_income, 2),
        "policy_decision_rationale": " ".join(rationale_parts),
    }
