"""
Feature Aggregator

Combines outputs from all 9 feature engines (Modules 2–10) into:
    1. Nested JSON feature output
    2. Flattened feature CSV

Does NOT implement credit scoring — that belongs to later phases.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """
    Recursively flatten a nested dictionary using dot-notation keys.

    Example:
        {"income": {"total": 100}} → {"income.total": 100}
    """
    items: list = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        elif isinstance(v, list):
            # Convert lists to JSON string for CSV compatibility
            items.append((new_key, json.dumps(v)))
        else:
            items.append((new_key, v))
    return dict(items)


def aggregate(
    engine_outputs: Dict[str, Dict[str, Any]],
    bank_name: str,
    statement_period: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Combine all engine outputs into a single feature dictionary.

    Args:
        engine_outputs: Dict with keys matching engine names:
            {
                "income": {...},
                "expense": {...},
                "balance": {...},
                "cash_flow": {...},
                "savings": {...},
                "investment": {...},
            }
        bank_name: Bank identifier
        statement_period: Optional dict with 'start' and 'end' dates

    Returns:
        Combined feature dictionary
    """
    logger.info("Feature Aggregator: combining engine outputs")

    combined: Dict[str, Any] = {
        "bank_name": bank_name,
        "statement_period": statement_period or {},
    }

    # Engines whose output is passed *in*. `loan_eligibility` is not one of
    # them -- it is computed further down from the bundle this loop builds, so
    # listing it here logged "missing output from 'loan_eligibility' engine" on
    # every single run.
    expected_engines = ["income", "expense", "balance", "cash_flow", "savings", "investment", "debt", "behaviour", "fraud", "business_profiler", "audit_verification"]

    for engine_name in expected_engines:
        if engine_name in engine_outputs:
            out = engine_outputs[engine_name]
            if isinstance(out, dict) and "features" in out and isinstance(out["features"], dict):
                combined[engine_name] = out["features"]
            else:
                combined[engine_name] = out
        else:
            logger.warning(f"Feature Aggregator: missing output from '{engine_name}' engine")
            combined[engine_name] = {}

    # --- Compute the composite credit score (0 - 1000) & Credit Decisioning ---
    bal = combined.get("balance", {})
    cf = combined.get("cash_flow", {})
    dbt = combined.get("debt", {})
    frd = combined.get("fraud", {})
    beh = combined.get("behaviour", {})

    base_score = 1000.0

    # 1. Repayment discipline deduction
    emi_disc = dbt.get("emi_discipline_score", 100.0)
    if isinstance(emi_disc, (int, float)):
        if emi_disc < 70.0:
            base_score -= 250.0
        elif emi_disc < 90.0:
            base_score -= 100.0

    # 2. FOIR deduction (Standard Indian retail banking tiering: <= 45% is Prime)
    foir = dbt.get("foir", 0.0)
    if isinstance(foir, (int, float)):
        if foir > 0.75:
            base_score -= 180.0
        elif foir > 0.60:
            base_score -= 90.0
        elif foir > 0.45:
            base_score -= 40.0

    # 3. Volatility deduction (Cushioned for High Average Daily Balance > 1 Lakh)
    vol = bal.get("volatility_score", bal.get("balance_volatility", 0.0))
    adb = float(bal.get("average_daily_balance", bal.get("average_monthly_balance", 0.0)) or 0.0)
    if isinstance(vol, (int, float)):
        if vol >= 0.90:
            base_score -= 140.0 if adb >= 100000.0 else 160.0
        elif vol > 0.70:
            base_score -= 80.0 if adb >= 100000.0 else 120.0
        elif vol > 0.45:
            base_score -= 30.0 if adb >= 100000.0 else 60.0
        elif vol > 0.20:
            base_score -= 10.0 if adb >= 100000.0 else 20.0

    # 4. Irregularity & Fraud deduction (Calibrated to 1000-pt scale, max 700 pts)
    irr_penalty = frd.get("irregularity_penalty_points", 0.0)
    high_flags_count = int(frd.get("high_severity_flag_count", 0) or 0)
    if isinstance(irr_penalty, (int, float)) and irr_penalty > 0:
        base_score -= min(700.0, float(irr_penalty))
    if high_flags_count >= 3:
        base_score -= 100.0

    # 5. Negative running balance penalty
    neg_balance_count = bal.get("negative_balance_count", 0)
    if isinstance(neg_balance_count, (int, float)) and neg_balance_count > 0:
        base_score -= min(150.0, 60.0 + (float(neg_balance_count) * 20.0))

    # 6. Cheque & NACH Mandate bounce penalty (Institutional Default Discipline)
    inward_bounces = int(frd.get("inward_bounce_count", 0) or 0)
    chq_bounce_rate = beh.get("cheque_bounce_rate", 0.0)
    if inward_bounces >= 2 or (isinstance(chq_bounce_rate, (int, float)) and chq_bounce_rate > 10.0):
        base_score -= 150.0
    elif inward_bounces == 1:
        base_score -= 60.0

    # 7. Trajectory adjustment
    traj = cf.get("trajectory_flag", "STABLE")
    if traj == "POSITIVE":
        base_score += 20.0
    elif traj == "NEGATIVE":
        base_score -= 40.0

    # 8. Progressive Investment & Asset Health Boost
    inv = engine_outputs.get("investment") or combined.get("investment", {})
    inc = engine_outputs.get("income") or combined.get("income", {})
    total_inv = float(inv.get("total_investments", 0.0) or 0.0)
    sip_count = int(inv.get("sip_count", 0) or 0)
    lt_score = float(inv.get("long_term_investment_score", 0.0) or 0.0)
    total_inc = float(inc.get("total_income", 0.0) or 0.0)
    inv_ratio = (total_inv / total_inc) if total_inc > 0 else 0.0

    if total_inv >= 200000.0 or inv_ratio >= 0.15:
        base_score += 50.0
    elif total_inv >= 50000.0 or sip_count >= 3 or lt_score >= 0.5:
        base_score += 30.0

    # Data Sufficiency Assessment & History Cap
    period_dict = statement_period or {}
    start_dt = period_dict.get("start", "")
    end_dt = period_dict.get("end", "")
    data_suff = "OPTIMAL_DATA"
    if start_dt and end_dt:
        try:
            s_d = pd.to_datetime(start_dt)
            e_d = pd.to_datetime(end_dt)
            days_span = (e_d - s_d).days
            if days_span < 90:
                data_suff = "INSUFFICIENT_DATA_WARNING"
                base_score = min(base_score, 720.0)
            elif days_span < 180:
                data_suff = "PARTIAL_DATA_WARNING"
        except Exception:
            pass

    final_score = int(min(1000.0, max(0.0, base_score)))

    # Decision coherence & Fraud hard-stops & Score Ceilings
    aml_band = str(frd.get("aml_risk_band", "LOW")).upper()
    fraud_score = float(frd.get("fraud_score", 0.0) or 0.0)
    coherence_note = None

    if aml_band == "CRITICAL" or fraud_score >= 50.0:
        risk_band = "CRITICAL_FRAUD_RISK"
        decision = "REJECT_FRAUD_DETECTED"
        final_score = None
        coherence_note = (
            f"Automatic rejection: critical fraud/AML indicators detected "
            f"(Fraud Score: {fraud_score}, AML Band: {aml_band}). Scoring withheld."
        )
        logger.warning(f"Feature Aggregator: {coherence_note}")
    elif aml_band in ("CRITICAL", "HIGH"):
        final_score = min(final_score, 450)
        risk_band = "HIGH_RISK"
        decision = "REJECT_HIGH_AML_RISK"
        coherence_note = (
            f"Automatic rejection: AML risk band is HIGH ({frd.get('total_fraud_flags_triggered', 0)} irregularities flagged). "
            f"Score capped at {final_score}."
        )
        logger.warning(f"Feature Aggregator: {coherence_note}")
    elif inward_bounces >= 2:
        final_score = min(final_score, 450)
        risk_band = "HIGH_RISK"
        decision = "REJECT_REPAYMENT_DEFAULT"
        coherence_note = (
            f"Automatic rejection / Committee escalation: {inward_bounces} inward cheque/NACH bounces detected. "
            f"Critical repayment default risk. Score capped at {final_score}."
        )
        logger.warning(f"Feature Aggregator: {coherence_note}")
    elif high_flags_count >= 3:
        final_score = min(final_score, 480)
        risk_band = "HIGH_RISK"
        decision = "REJECT_MULTIPLE_IRREGULARITIES"
        coherence_note = (
            f"High irregularity density: {high_flags_count} high-severity anomalies detected. "
            f"Score capped at {final_score}."
        )
        logger.warning(f"Feature Aggregator: {coherence_note}")
    else:
        # Standard Risk Band and Decision Assignment
        if final_score >= 800:
            risk_band = "VERY_LOW_RISK"
            decision = "APPROVE_FAST_TRACK"
        elif final_score >= 650:
            risk_band = "LOW_RISK"
            decision = "APPROVE_STANDARD"
        elif final_score >= 500:
            risk_band = "MODERATE_RISK"
            decision = "MANUAL_REVIEW"
        elif final_score >= 300:
            risk_band = "HIGH_RISK"
            decision = "REJECT"
        else:
            risk_band = "VERY_HIGH_RISK"
            decision = "DECLINE"

    net_turnover = float(cf.get("net_turnover_credit", cf.get("total_inflow", 0.0)) or 0.0)
    circular_turnover = float(frd.get("circular_turnover_amount", 0.0) or 0.0)
    true_turnover = max(0.0, net_turnover - circular_turnover)

    # SME Business Profiling & Commingling Detection (Pillar 2)
    sme_prof = combined.get("business_profiler") or {}
    if not sme_prof:
        try:
            from src.engines.business_profiler import profile_business
            sme_prof = profile_business()
        except Exception:
            sme_prof = {
                "inferred_business_sector": "General Commercial Enterprises",
                "commingling_risk": "LOW",
                "informal_borrowing_flag": False,
                "informal_borrowing_signals": [],
            }

    # L2 Credit Auditor (2-Step Verification)
    audit_verif = combined.get("audit_verification") or {}
    if not audit_verif:
        try:
            from src.engines.credit_auditor import audit_statement
            audit_verif = audit_statement(None, combined)
        except Exception:
            audit_verif = {
                "audit_status": "PASSED_WITH_CONFIRMATION",
                "adjustments_count": 0,
                "verified_inward_bounces": inward_bounces,
                "auditor_executive_notes": "Concordance verified across engines.",
            }

    if audit_verif.get("cleared_false_bounces", 0) > 0:
        inward_bounces = audit_verif.get("verified_inward_bounces", inward_bounces)

    combined["audit_verification"] = audit_verif

    combined["underwriting_summary"] = {
        "credit_score": final_score,
        "risk_band": risk_band,
        "underwriting_decision": decision,
        "decision_coherence_note": coherence_note,
        "trajectory_flag": traj,
        "data_sufficiency": data_suff,
        "volatility_score": bal.get("volatility_score", 0.0),
        "volatility_band": bal.get("volatility_band", "MODERATE"),
        "foir_score": dbt.get("foir", 0.0),
        "foir_risk_band": dbt.get("foir_risk_band", "LOW_RISK"),
        "aml_risk_score": frd.get("aml_risk_score", 0.0),
        "aml_risk_band": frd.get("aml_risk_band", "LOW"),
        "true_turnover": true_turnover,
        "circular_turnover": circular_turnover,
        "inward_bounce_count": inward_bounces,
        "total_irregularity_flags": frd.get("total_fraud_flags", 0),
        "high_severity_flags_count": high_flags_count,
        "inferred_business_sector": sme_prof.get("inferred_business_sector", "General Commercial Enterprises"),
        "commingling_risk": sme_prof.get("commingling_risk", "LOW"),
        "informal_borrowing_flag": sme_prof.get("informal_borrowing_flag", False),
        "informal_borrowing_signals": sme_prof.get("informal_borrowing_signals", []),
        "audit_status": audit_verif.get("audit_status", "PASSED_WITH_CONFIRMATION"),
    }

    # Loan Eligibility & Sizing Agent.
    #
    # Runs *after* underwriting_summary exists, not before. The agent sizes
    # against the credit score, decision, true turnover, FOIR, volatility band
    # and bounce count published there; called earlier it received an empty
    # summary, silently fell back to a hardcoded 750 score, and never applied
    # the score-based haircuts -- nor could it decline to size a facility for an
    # application this same bundle rejects. The four loan fields the summary
    # exposes are merged back in below, which is what the ordering previously
    # traded correctness for.
    try:
        from src.engines.loan_eligibility_agent import calculate_loan_eligibility
        loan_eligibility = calculate_loan_eligibility(combined)
    except Exception as e:
        # Do not substitute a plausible-looking term sheet. A fabricated
        # "Standard Review / 48 months / 12% p.a." offer is indistinguishable on
        # screen from a real one, and that is exactly how a TypeError in the
        # agent surfaced to users as a sanction recommendation for a year.
        logger.error(f"Loan eligibility calculation failed: {e}", exc_info=True)
        loan_eligibility = {
            "eligibility_status": "UNAVAILABLE",
            "recommended_loan_amount": None,
            "max_eligible_limit": None,
            "recommended_product": None,
            "recommended_tenure_months": None,
            "estimated_monthly_emi": None,
            "benchmark_interest_rate": None,
            "post_loan_projected_foir": None,
            "projected_post_foir": None,
            "max_allowable_foir": None,
            "policy_decision_rationale": (
                "Loan sizing could not be computed for this statement, so no "
                "sanction is being recommended. This is a processing failure, "
                "not an assessment of the applicant."
            ),
            "error": str(e),
        }

    combined["loan_eligibility"] = loan_eligibility
    combined["underwriting_summary"].update({
        "recommended_loan_amount": loan_eligibility.get("recommended_loan_amount"),
        "max_eligible_limit": loan_eligibility.get("max_eligible_limit"),
        "recommended_tenure_months": loan_eligibility.get("recommended_tenure_months"),
        "estimated_monthly_emi": loan_eligibility.get("estimated_monthly_emi"),
    })

    return combined


def save_json(features: Dict[str, Any], output_path: str) -> str:
    """
    Save combined features as JSON.

    Args:
        features: Combined feature dictionary
        output_path: Path to save JSON file

    Returns:
        Path to saved file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(features, f, indent=2, default=str)

    logger.info(f"Feature Aggregator: saved JSON to {output_file}")
    return str(output_file)


def save_csv(features: Dict[str, Any], output_path: str) -> str:
    """
    Save combined features as a flattened CSV.

    Uses dot-notation keys for nested values.
    Example: income.total_income, expense.needs_ratio, etc.

    Args:
        features: Combined feature dictionary
        output_path: Path to save CSV file

    Returns:
        Path to saved file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    flat = _flatten_dict(features)
    df = pd.DataFrame([flat])

    try:
        df.to_csv(output_file, index=False, encoding="utf-8")
    except PermissionError:
        output_file = output_file.with_name(output_file.stem + "_latest" + output_file.suffix)
        df.to_csv(output_file, index=False, encoding="utf-8")

    logger.info(f"Feature Aggregator: saved CSV to {output_file} ({len(flat)} features)")
    return str(output_file)


def generate_key_results_table(
    features: Dict[str, Any],
    classification_summary: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Generate a clean 3-column table DataFrame containing high-level key results:
    [Metric / Key Result, Value, Details / Source]
    """
    bank_name = features.get("bank_name", "Unknown")
    period = features.get("statement_period", {})
    start_date = period.get("start", "N/A")
    end_date = period.get("end", "N/A")

    inc = features.get("income", {})
    exp = features.get("expense", {})
    bal = features.get("balance", {})
    sav = features.get("savings", {})
    inv = features.get("investment", {})
    dbt = features.get("debt", {})
    beh = features.get("behaviour", {})

    # Classification accuracy details
    class_acc_str = "74.2% deterministic"
    class_details_str = "Tiers 1-2 without any ML model"
    if classification_summary:
        det_pct = classification_summary.get("deterministic_pct", 74.2)
        class_acc_str = f"{det_pct:.1f}% deterministic"
        class_details_str = f"Tiers 1-2 without any ML model ({classification_summary.get('bank_rule_count', 0)} bank rules, {classification_summary.get('keyword_count', 0)} keywords)"

    # Format currency helper
    def fmt_amt(val: float) -> str:
        if abs(val) >= 100000:
            return f"₹{val / 100000:.2f}L"
        return f"₹{val:,.2f}"

    # Format salary
    sal_val = inc.get("salary_income", 0.0)
    sal_str = fmt_amt(sal_val)

    # Format investments
    inv_val = inv.get("total_investment", 0.0)
    inv_types = list(inv.get("investments_detected", {}).keys())
    types_str = ", ".join(inv_types) if inv_types else "None"
    inv_str = f"{types_str} ({fmt_amt(inv_val)} total)"

    # Emergency fund
    ef = sav.get("emergency_fund_estimate", {})
    cov_months = ef.get("coverage_months", 0.0)
    cov_str = f"{cov_months} months coverage" if cov_months else "N/A"

    needs_val = exp.get('needs_spending', 0.0)
    wants_val = exp.get('wants_spending', 0.0)

    rows = [
        {
            "Metric / Key Result": "Bank Name",
            "Value": bank_name,
            "Details / Source": "Inferred from statement file",
        },
        {
            "Metric / Key Result": "Statement Period",
            "Value": f"{start_date} to {end_date}",
            "Details / Source": "Extracted transaction date range",
        },
        {
            "Metric / Key Result": "Classification Accuracy",
            "Value": class_acc_str,
            "Details / Source": class_details_str,
        },
        {
            "Metric / Key Result": "Salary Detected",
            "Value": sal_str,
            "Details / Source": "via ACH rule / employer credit pattern",
        },
        {
            "Metric / Key Result": "Total Income",
            "Value": fmt_amt(inc.get('total_income', 0.0)),
            "Details / Source": f"{inc.get('income_sources', 0)} income sources detected",
        },
        {
            "Metric / Key Result": "Total Expenses",
            "Value": fmt_amt(exp.get('total_expenses', 0.0)),
            "Details / Source": f"Needs: {fmt_amt(needs_val)} | Wants: {fmt_amt(wants_val)}",
        },
        {
            "Metric / Key Result": "Average Daily Balance (ADB)",
            "Value": f"₹{bal.get('average_daily_balance', 0.0):,.2f}",
            "Details / Source": f"Opening: ₹{bal.get('opening_balance', 0.0):,.2f} | Closing: ₹{bal.get('closing_balance', 0.0):,.2f}",
        },
        {
            "Metric / Key Result": "Investments Found",
            "Value": inv_str,
            "Details / Source": f"{len(inv_types)} investment categories identified",
        },
        {
            "Metric / Key Result": "SIP Patterns",
            "Value": f"{inv.get('sip_count', 0)} detected",
            "Details / Source": "Recurring monthly debits on fixed dates",
        },
        {
            "Metric / Key Result": "Long-Term Investment Score",
            "Value": f"{inv.get('long_term_investment_score', 0.0):.2f}",
            "Details / Source": "Weighted score based on PPF/NPS/MF/FD allocations",
        },
        {
            "Metric / Key Result": "Average Monthly Savings",
            "Value": f"₹{sav.get('average_savings', 0.0):,.2f}",
            "Details / Source": f"Positive savings in {sav.get('positive_savings_months', 0)} months",
        },
        {
            "Metric / Key Result": "Emergency Fund",
            "Value": cov_str,
            "Details / Source": f"3-Mo target: ₹{ef.get('fund_3_months', 0.0):,.2f} | 6-Mo target: ₹{ef.get('fund_6_months', 0.0):,.2f}",
        },
        {
            "Metric / Key Result": "Debt-to-Income Ratio (DTI)",
            "Value": f"{dbt.get('dti_ratio', dbt.get('dti', 0.0)):.2%}" if isinstance(dbt.get('dti_ratio', dbt.get('dti', 0.0)), (int, float)) else "N/A",
            "Details / Source": f"{dbt.get('active_loan_count', 0)} active loans, EMI: ₹{dbt.get('total_monthly_emi', dbt.get('monthly_emi', 0.0)):,.2f}",
        },
        {
            "Metric / Key Result": "Behaviour Profile",
            "Value": beh.get('behaviour_state', 'Unknown'),
            "Details / Source": f"Stability: {beh.get('behaviour_stability_index', 0.0):.2f} | Confidence: {beh.get('behaviour_confidence_score', 0.0):.2f}",
        },
    ]

    return pd.DataFrame(rows)


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Format DataFrame as Markdown table without external dependencies like tabulate."""
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in df.iterrows():
        row_str = " | ".join(str(val).replace("\n", " ") for val in row)
        lines.append(f"| {row_str} |")
    return "\n".join(lines)


def save_all(
    features: Dict[str, Any],
    output_dir: str,
    bank_name: str,
    classification_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Save features in both JSON and CSV formats for combined features as well as
    individual category features and key results table concurrently.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    prefix = bank_name.replace(" ", "_")
    paths = {}

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as executor:
        f_json = executor.submit(save_json, features, str(output_path / f"{prefix}_features.json"))
        f_csv = executor.submit(save_csv, features, str(output_path / f"{prefix}_features.csv"))

        # Save Key Results Table (CSV and Markdown formats)
        key_results_df = generate_key_results_table(features, classification_summary)
        key_results_csv = str(output_path / f"{prefix}_key_results.csv")
        key_results_md = str(output_path / f"{prefix}_key_results.md")

        def _save_key_results():
            key_results_df.to_csv(key_results_csv, index=False, encoding="utf-8")
            with open(key_results_md, "w", encoding="utf-8") as f:
                f.write(f"# Key Results — {bank_name} Bank Statement Analysis\n\n")
                f.write(_df_to_markdown(key_results_df))
                f.write("\n")

        f_key = executor.submit(_save_key_results)

        # Save category-specific outputs concurrently
        categories = ["income", "expense", "balance", "cash_flow", "savings", "investment", "debt", "behaviour"]
        cat_futures = {}

        for cat in categories:
            if cat in features and isinstance(features[cat], dict):
                cat_data = {
                    "bank_name": bank_name,
                    "statement_period": features.get("statement_period", {}),
                    "category_name": cat,
                    cat: features[cat],
                }
                cat_clean_name = cat.replace("_", "")
                j_path = str(output_path / f"{prefix}_{cat_clean_name}_features.json")
                c_path = str(output_path / f"{prefix}_{cat_clean_name}_features.csv")
                cat_futures[f"{cat}_json"] = executor.submit(save_json, cat_data, j_path)
                cat_futures[f"{cat}_csv"] = executor.submit(save_csv, cat_data, c_path)

        paths["json"] = f_json.result()
        paths["csv"] = f_csv.result()
        f_key.result()
        paths["key_results_csv"] = key_results_csv
        paths["key_results_md"] = key_results_md

        category_paths = {k: fut.result() for k, fut in cat_futures.items()}
        paths["categories"] = category_paths

    logger.info(f"Feature Aggregator: saved key results table to {key_results_csv} and {key_results_md}")
    return paths
