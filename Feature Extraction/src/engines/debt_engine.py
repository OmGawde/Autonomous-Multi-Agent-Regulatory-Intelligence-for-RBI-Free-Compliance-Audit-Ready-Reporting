import re
import math
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
try:
    # pyrefly: ignore [missing-import]
    from rapidfuzz import process as fuzzy_process, fuzz
except ImportError:
    import difflib
    class fuzzy_process:
        @staticmethod
        def extractOne(query, choices, scorer=None):
            matches = difflib.get_close_matches(query, choices, n=1, cutoff=0.6)
            if matches:
                match = matches[0]
                ratio = difflib.SequenceMatcher(None, query, match).ratio() * 100.0
                return (match, ratio)
            return None
    class fuzz:
        partial_ratio = None

try:
    from common_utils import ConfigManager, DataSufficiencyEvaluator, EvidencePackager, FeatureFormatter
except ImportError:
    from .common_utils import ConfigManager, DataSufficiencyEvaluator, EvidencePackager, FeatureFormatter

class DebtEngine:
    """
    Production-Grade Liability Reconstruction & Debt Engine for Bank Statement Analyzer (BSA).
    Detects loan disbursements, EMI payment streams, credit card bills, running facilities (OD/CC),
    tracks loan lifecycles, and computes debt burden, DTI, FOIR, and loan stacking metrics.
    Exposes process(df, monthly_income) as standard feature extraction interface.
    """

    def __init__(self, config_path=None):
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get("debt_engine_config", {})
        self.lender_dict = self.config_manager.get("lender_dictionary", {})
        self.pct_tol = self.config.get("amount_tolerance_percent", 2.0)
        self.abs_tol = self.config.get("amount_tolerance_abs", 100.0)
        self.date_tol_days = self.config.get("date_tolerance_days", 5)

    def process(self, df: pd.DataFrame, monthly_income: float = 0.0) -> dict:
        """Standard production-grade Feature Extraction interface."""
        if df.empty:
            return self._empty_process_response()

        sufficiency = DataSufficiencyEvaluator.evaluate(df)
        
        # 1. Normalize lenders & classify transactions
        df_analyzed = self._annotate_lenders_and_types(df)

        # 2. Extract loan disbursement credits
        disbursements = self._detect_disbursements(df_analyzed)

        # 3. Mine recurring EMI streams & cluster loan facilities
        loan_objects = self._mine_loan_facilities(df_analyzed, disbursements)

        # 4. Separate running facilities (OD/CC) & credit cards from amortising loans
        running_facilities = self._extract_running_facilities(df_analyzed)
        credit_card_bills = self._extract_credit_cards(df_analyzed)

        # 5. Compute portfolio metrics (DTI, FOIR, Burden, Stacking)
        portfolio_summary = self._compute_portfolio_metrics(
            loan_objects, running_facilities, credit_card_bills, monthly_income, sufficiency
        )

        # 6. Annotate transaction dataframe
        df_annotated = self._annotate_transaction_level_debt(
            df_analyzed, loan_objects, running_facilities, credit_card_bills, disbursements
        )

        # 7. Reconstruct entity objects
        entities = self._reconstruct_entities(loan_objects, running_facilities, credit_card_bills, disbursements)

        # 8. Format engineered features dictionary
        features = self._build_feature_dictionary(
            portfolio_summary, loan_objects, running_facilities, credit_card_bills, disbursements, sufficiency
        )

        return {
            "engine": "DebtEngine",
            "version": "1.0.0",
            "transaction_annotations": df_annotated,
            "entities": entities,
            "features": features,
            "metadata": {
                "processed_at": datetime.now().isoformat(),
                "total_transactions": len(df),
                "data_sufficiency": sufficiency
            }
        }

    def analyze(self, df: pd.DataFrame, monthly_income: float = 0.0) -> dict:
        """Legacy compatibility wrapper around process()."""
        if df.empty:
            return self._empty_response()

        res = self.process(df, monthly_income=monthly_income)
        entities = res["entities"]
        all_loans = entities["active_loans"] + entities["closed_loans"]
        
        return {
            "engine": "DebtEngine",
            "version": "1.0.0",
            "data_sufficiency": res["metadata"]["data_sufficiency"],
            "portfolio_summary": self._compute_portfolio_metrics(
                all_loans, entities["running_facilities"], entities["credit_card_payments"], monthly_income, res["metadata"]["data_sufficiency"]
            ),
            "detected_loans": all_loans,
            "running_facilities": entities["running_facilities"],
            "credit_card_payments": entities["credit_card_payments"],
            "disbursements_detected": entities["disbursements"]
        }

    def _annotate_lenders_and_types(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["detected_lender"] = None
        df["loan_category"] = None
        df["is_borrowing_credit"] = False

        lender_flat = []
        for cat, keywords in self.lender_dict.items():
            for kw in keywords:
                lender_flat.append((kw.upper(), cat))

        RAIL_PREFIXES = {
            "UPI", "BIL", "CAM", "EBA", "NFS", "CLG", "NEFT", "RTGS",
            "POS", "ECOM", "MMT", "CMS", "ACH", "ATW", "ATM", "CWDR",
            "INT", "INT.PD", "CHQ", "CDM", "DMRC", "FASTAG", "DR", "CR"
        }

        for idx, row in df.iterrows():
            desc = str(row["description"]).upper()
            debit = float(row["debit"])
            credit = float(row["credit"])
            category = str(row.get("category", ""))
            subcategory = str(row.get("subcategory", ""))

            # Non-debt categories (Investments, Banking, Income) are not loans
            if category in ["Investment", "Banking", "Income"] and not ("DISB" in desc or "LOAN" in desc):
                continue

            # 1. Exact or keyword match against lender_dictionary
            matched_lender = None
            matched_cat = None
            for kw, cat in lender_flat:
                if kw in desc:
                    matched_lender = kw
                    matched_cat = cat
                    break
            
            # 2. Token-bounded match if keyword match failed
            if not matched_lender and len(desc) > 5:
                all_kws = [k[0] for k in lender_flat if len(k[0]) >= 4]
                if all_kws:
                    res = fuzzy_process.extractOne(desc, all_kws, scorer=fuzz.partial_ratio)
                    if res and res[1] >= self.config.get("lender_alias_similarity_threshold", 85.0):
                        matched_kw = res[0]
                        matched_lender = matched_kw
                        matched_cat = next(c for k, c in lender_flat if k == matched_kw)

            # 3. Only use payee fallback if subcategory or description explicitly indicates a loan
            if not matched_lender:
                is_loan_signal = (
                    "LOAN" in subcategory.upper()
                    or subcategory in ["Loan / EMI", "Home Loan EMI", "Personal Loan EMI"]
                    or "LOAN" in desc
                    or "EMI" in desc
                )
                if is_loan_signal:
                    fallback = self._clean_payee_fallback(desc)
                    if fallback and fallback.upper() not in RAIL_PREFIXES:
                        matched_lender = fallback
                        matched_cat = "PERSONAL_LOAN" if "PL" in desc else "HOME_LOAN" if "HL" in desc else "OTHER_DEBT"

            if matched_lender:
                df.at[idx, "detected_lender"] = matched_lender
                df.at[idx, "loan_category"] = matched_cat or "OTHER_DEBT"

            # Check if disbursement credit
            if credit > 5000.0:
                if matched_cat and matched_cat not in ["CREDIT_CARD", "BNPL"]:
                    df.at[idx, "is_borrowing_credit"] = True
                elif "DISB" in desc or ("LOAN" in desc and "REPAY" not in desc):
                    df.at[idx, "is_borrowing_credit"] = True

        return df

    def _clean_payee_fallback(self, desc: str) -> str:
        RAIL_PREFIXES = {
            "UPI", "BIL", "CAM", "EBA", "NFS", "CLG", "NEFT", "RTGS",
            "POS", "ECOM", "MMT", "CMS", "ACH", "ATW", "ATM", "CWDR",
            "INT", "INT.PD", "CHQ", "CDM", "DMRC", "FASTAG", "DR", "CR"
        }
        parts = re.split(r'[/_\s-]+', desc)
        clean = [p for p in parts if len(p) > 2 and not p.isdigit() and p.upper() not in RAIL_PREFIXES]
        return clean[0] if clean else ""

    def _detect_disbursements(self, df: pd.DataFrame) -> list:
        disbursements = []
        disb_rows = df[df["is_borrowing_credit"] == True]
        for _, row in disb_rows.iterrows():
            disbursements.append({
                "txn_id": row["txn_id"],
                "date": str(row["date"])[:10],
                "amount": float(row["credit"]),
                "lender": row["detected_lender"],
                "category": row["loan_category"],
                "description": row["description"]
            })
        return disbursements

    def _mine_loan_facilities(self, df: pd.DataFrame, disbursements: list) -> list:
        """Groups recurring debits with amount & date tolerance to detect amortising loans."""
        debits = df[df["debit"] > 0].copy()
        debits["date_dt"] = pd.to_datetime(debits["date"])

        # End of the statement period, used to age each facility. This was
        # previously read as df["date_dt"], a column that only ever existed on
        # the local `debits` copy above -- so it was always None, every loan came
        # back "Active", and closed_loan_count/missed_emi_count were always 0.
        max_stmt_date = pd.to_datetime(df["date"]).max() if "date" in df.columns else None

        visited_ids = set()
        loan_objects = []

        # Group by exact or near-identical Mandate / Lender String
        lender_groups = debits.groupby("detected_lender")
        
        for lender, group in lender_groups:
            if not lender or str(lender).strip() in ["", "None", "nan", "UNKNOWN_LENDER"] or len(group) < 1:
                continue

            # Group transactions within amount tolerance
            amount_clusters = []
            for idx, row in group.iterrows():
                if row["txn_id"] in visited_ids:
                    continue
                
                amt = float(row["debit"])
                cluster_found = False
                for cluster in amount_clusters:
                    ref_amt = cluster["ref_amount"]
                    diff = abs(amt - ref_amt)
                    allowed_diff = max(self.abs_tol, ref_amt * (self.pct_tol / 100.0))
                    if diff <= allowed_diff:
                        cluster["rows"].append(row)
                        visited_ids.add(row["txn_id"])
                        cluster_found = True
                        break

                if not cluster_found:
                    amount_clusters.append({
                        "ref_amount": amt,
                        "rows": [row]
                    })
                    visited_ids.add(row["txn_id"])

            # Evaluate each cluster as a loan facility
            for cluster in amount_clusters:
                c_rows = cluster["rows"]
                if len(c_rows) >= self.config.get("min_emi_recurrence", 2):
                    loan_obj = self._build_loan_object(lender, c_rows, disbursements, max_stmt_date)
                    loan_objects.append(loan_obj)

        return loan_objects

    def _build_loan_object(self, lender: str, rows: list, disbursements: list, max_stmt_date=None) -> dict:
        rows_sorted = sorted(rows, key=lambda x: x["date_dt"])
        amounts = [float(r["debit"]) for r in rows_sorted]
        dates = [r["date_dt"] for r in rows_sorted]
        
        avg_emi = round(float(np.mean(amounts)), 2)
        loan_cat = rows_sorted[0]["loan_category"]
        if loan_cat == "OTHER_DEBT":
            loan_cat = self._infer_loan_category(lender, avg_emi)

        # Check date cadence
        date_diffs = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_cadence = round(float(np.mean(date_diffs)), 1) if date_diffs else 30.0

        # Lifecycle state machine determination relative to max statement date
        last_date = dates[-1]
        ref_date = max_stmt_date if max_stmt_date is not None else last_date
        days_since_last = (ref_date - last_date).days
        
        if days_since_last <= 35:
            status = "Active"
        elif 35 < days_since_last <= 65:
            status = "Grace"
        elif 65 < days_since_last <= 95:
            status = "Missed EMI"
        else:
            status = "Overdue / Closed"

        # Payment regularity
        regularity_scores = []
        for diff in date_diffs:
            if 27 <= diff <= 33:
                regularity_scores.append("On-Time")
            elif diff < 27:
                regularity_scores.append("Early")
            elif 33 < diff <= 40:
                regularity_scores.append("Late")
            else:
                regularity_scores.append("Skipped/Irregular")

        primary_regularity = max(set(regularity_scores), key=regularity_scores.count) if regularity_scores else "On-Time"

        # Check for top-up link
        is_topup = False
        matching_disb = [d for d in disbursements if d["lender"] == lender]
        if matching_disb:
            is_topup = True

        # Confidence Score calculation
        conf_score = min(1.0, round(0.4 * len(rows) + 0.3 * (1.0 if loan_cat != "OTHER_DEBT" else 0.5) + 0.3, 2))

        # Expected EMI calendar (next 3 expected dates)
        next_calendar = []
        curr_date = last_date
        for i in range(1, 4):
            next_date = curr_date + timedelta(days=30 * i)
            next_calendar.append(next_date.strftime("%Y-%m-%d"))

        is_secured = loan_cat in ["HOME_LOAN", "VEHICLE_LOAN", "GOLD_LOAN"]

        # Reconcile the expected monthly EMI calendar against what was actually
        # paid, so emi_discipline_score has real inputs. Without these two keys
        # the score defaulted to a constant 100.0 for every statement, which
        # disabled the largest single lever (-250) in the composite credit score.
        total_emis_paid = len(rows_sorted)
        observed_span_days = (last_date - dates[0]).days
        expected_emis = max(total_emis_paid, int(round(observed_span_days / 30.0)) + 1)
        missed_emis_count = max(0, expected_emis - total_emis_paid)

        return {
            "loan_id": f"LOAN_{lender[:8].replace(' ', '_')}_{int(avg_emi)}",
            "lender_name": lender,
            "loan_type": loan_cat,
            "is_secured": is_secured,
            "monthly_emi": avg_emi,
            "recurrence_count": len(rows),
            "avg_cadence_days": avg_cadence,
            "detected_start_date": dates[0].strftime("%Y-%m-%d"),
            "last_payment_date": last_date.strftime("%Y-%m-%d"),
            "status": status,
            "payment_regularity": primary_regularity,
            "confidence_score": conf_score,
            "is_topup_loan": is_topup,
            "expected_next_emi_dates": next_calendar,
            "total_emis_paid": total_emis_paid,
            "missed_emis_count": missed_emis_count,
            "sample_txn_ids": [r["txn_id"] for r in rows_sorted]
        }

    def _infer_loan_category(self, lender: str, emi: float) -> str:
        lender_u = lender.upper()
        if "HL" in lender_u or "HOUSING" in lender_u or emi > 20000:
            return "HOME_LOAN"
        elif "AUTO" in lender_u or "VEHICLE" in lender_u:
            return "VEHICLE_LOAN"
        elif "MUTHOOT" in lender_u or "MANAPPURAM" in lender_u:
            return "GOLD_LOAN"
        else:
            return "PERSONAL_LOAN"

    def _extract_running_facilities(self, df: pd.DataFrame) -> list:
        facilities = []
        od_kw = self.config.get("running_facility_keywords", [])
        for _, row in df.iterrows():
            desc = str(row["description"]).upper()
            if any(k in desc for k in od_kw):
                facilities.append({
                    "txn_id": row["txn_id"],
                    "date": str(row["date"])[:10],
                    "amount": float(row["debit"]),
                    "description": row["description"]
                })
        return facilities

    def _extract_credit_cards(self, df: pd.DataFrame) -> list:
        cc_payments = []
        cc_kws = self.lender_dict.get("CREDIT_CARD", [])
        for _, row in df.iterrows():
            desc = str(row["description"]).upper()
            debit = float(row["debit"])
            if debit > 0 and any(k in desc for k in cc_kws):
                cc_payments.append({
                    "txn_id": row["txn_id"],
                    "date": str(row["date"])[:10],
                    "amount": debit,
                    "lender": row["detected_lender"],
                    "description": row["description"]
                })
        return cc_payments

    def _compute_portfolio_metrics(self, loans: list, running_fac: list, cc_bills: list, monthly_income: float, sufficiency: dict) -> dict:
        active_loans = [l for l in loans if l["status"] in ["Active", "Grace"]]
        total_monthly_emi = sum(l["monthly_emi"] for l in active_loans)
        
        avg_cc_payment = round(np.mean([c["amount"] for c in cc_bills]), 2) if cc_bills else 0.0
        total_obligations = total_monthly_emi + (avg_cc_payment * 0.10)

        # No hardcoded income fallback. Ratios against an assumed salary are
        # worse than no ratio at all -- they look plausible and are wrong. The
        # previous default of Rs 1,50,000 drove DTI/FOIR for every statement.
        if monthly_income and monthly_income > 0:
            income = float(monthly_income)
            emi_burden = round(total_monthly_emi / income, 4)
            dti_ratio = round(total_obligations / income, 4)
            foir = round(total_monthly_emi / income, 4)
        else:
            logger.warning(
                "Debt Engine: monthly income unavailable; DTI/FOIR/EMI-burden reported as unknown"
            )
            emi_burden = None
            dti_ratio = None
            foir = None

        lenders = list(set([l["lender_name"] for l in loans]))
        secured_loans = [l for l in loans if l["is_secured"]]
        unsecured_loans = [l for l in loans if not l["is_secured"]]

        top_lender_emi = max([l["monthly_emi"] for l in active_loans], default=0.0)
        lender_concentration = round(top_lender_emi / total_monthly_emi, 4) if total_monthly_emi > 0 else 0.0

        recent_borrowing_velocity = len([l for l in loans if l["status"] == "Active" and l["recurrence_count"] <= 3])
        loan_stacking_detected = recent_borrowing_velocity >= 2

        return {
            "total_monthly_emi": round(total_monthly_emi, 2),
            "estimated_cc_monthly_payment": round(avg_cc_payment, 2),
            "total_monthly_obligations": round(total_obligations, 2),
            "emi_burden_ratio": emi_burden,
            "dti_ratio": dti_ratio,
            "foir_ready_metric": foir,
            "active_loan_count": len(active_loans),
            "total_loan_count_historical": len(loans),
            "distinct_lenders_count": len(lenders),
            "lender_concentration_ratio": lender_concentration,
            "secured_debt_ratio": round(len(secured_loans) / len(loans), 2) if loans else 0.0,
            "unsecured_debt_ratio": round(len(unsecured_loans) / len(loans), 2) if loans else 0.0,
            "loan_stacking_flag": loan_stacking_detected,
            "recent_borrowing_velocity_90d": recent_borrowing_velocity,
            "missed_emi_count": len([l for l in loans if l["status"] == "Missed EMI"])
        }

    def _annotate_transaction_level_debt(self, df: pd.DataFrame, loans: list, running_fac: list, cc_bills: list, disbursements: list) -> pd.DataFrame:
        df = df.copy()
        df["debt_id"] = None
        df["loan_type"] = df["loan_category"]
        df["lender"] = df["detected_lender"]
        df["payment_status"] = "N/A"
        df["emi_detected"] = False
        df["confidence"] = 0.0

        txn_to_loan = {}
        for loan in loans:
            for tid in loan.get("sample_txn_ids", []):
                txn_to_loan[tid] = loan

        cc_txn_ids = set([c["txn_id"] for c in cc_bills])
        fac_txn_ids = set([f["txn_id"] for f in running_fac])
        disb_txn_ids = set([d["txn_id"] for d in disbursements])

        for idx, row in df.iterrows():
            tid = row["txn_id"]
            if tid in txn_to_loan:
                l_obj = txn_to_loan[tid]
                df.at[idx, "debt_id"] = l_obj["loan_id"]
                df.at[idx, "loan_type"] = l_obj["loan_type"]
                df.at[idx, "lender"] = l_obj["lender_name"]
                df.at[idx, "payment_status"] = l_obj["payment_regularity"]
                df.at[idx, "emi_detected"] = True
                df.at[idx, "confidence"] = l_obj["confidence_score"]
            elif tid in cc_txn_ids:
                df.at[idx, "debt_id"] = f"CC_{row['detected_lender']}"
                df.at[idx, "loan_type"] = "CREDIT_CARD"
                df.at[idx, "lender"] = row["detected_lender"]
                df.at[idx, "payment_status"] = "On-Time"
                df.at[idx, "emi_detected"] = False
                df.at[idx, "confidence"] = 0.85
            elif tid in fac_txn_ids:
                df.at[idx, "debt_id"] = f"FAC_{row['detected_lender']}"
                df.at[idx, "loan_type"] = "RUNNING_FACILITY"
                df.at[idx, "lender"] = row["detected_lender"]
                df.at[idx, "payment_status"] = "Active"
                df.at[idx, "emi_detected"] = False
                df.at[idx, "confidence"] = 0.80
            elif tid in disb_txn_ids:
                df.at[idx, "debt_id"] = f"DISB_{row['detected_lender']}"
                df.at[idx, "loan_type"] = row["loan_category"] or "PERSONAL_LOAN"
                df.at[idx, "lender"] = row["detected_lender"]
                df.at[idx, "payment_status"] = "Disbursement"
                df.at[idx, "emi_detected"] = False
                df.at[idx, "confidence"] = 0.90

        return df

    def _reconstruct_entities(self, loans: list, running_fac: list, cc_bills: list, disbursements: list) -> dict:
        active_loans = [l for l in loans if l["status"] in ["Active", "Grace"]]
        closed_loans = [l for l in loans if l["status"] not in ["Active", "Grace"]]

        emi_schedule = []
        for l in active_loans:
            for date_str in l.get("expected_next_emi_dates", []):
                emi_schedule.append({
                    "loan_id": l["loan_id"],
                    "lender": l["lender_name"],
                    "amount": l["monthly_emi"],
                    "expected_date": date_str,
                    "loan_type": l["loan_type"]
                })

        lender_profiles = {}
        for l in loans:
            l_name = l["lender_name"]
            if l_name not in lender_profiles:
                lender_profiles[l_name] = {
                    "lender_name": l_name,
                    "active_loans": 0,
                    "closed_loans": 0,
                    "total_monthly_emi": 0.0,
                    "loan_categories": set()
                }
            if l["status"] in ["Active", "Grace"]:
                lender_profiles[l_name]["active_loans"] += 1
                lender_profiles[l_name]["total_monthly_emi"] += l["monthly_emi"]
            else:
                lender_profiles[l_name]["closed_loans"] += 1
            lender_profiles[l_name]["loan_categories"].add(l["loan_type"])

        profile_list = []
        for k, v in lender_profiles.items():
            v["loan_categories"] = list(v["loan_categories"])
            profile_list.append(v)

        return {
            "active_loans": active_loans,
            "closed_loans": closed_loans,
            "emi_schedule": sorted(emi_schedule, key=lambda x: x["expected_date"]),
            "lender_profiles": profile_list,
            "running_facilities": running_fac,
            "credit_card_payments": cc_bills,
            "disbursements": disbursements
        }

    def _build_feature_dictionary(self, summary: dict, loans: list, running_fac: list, cc_bills: list, disbursements: list, sufficiency: dict) -> dict:
        conf = sufficiency.get("confidence_multiplier", 1.0)
        active_loans = [l for l in loans if l["status"] in ["Active", "Grace"]]

        home_emi = sum(l["monthly_emi"] for l in active_loans if l["loan_type"] == "HOME_LOAN")
        personal_emi = sum(l["monthly_emi"] for l in active_loans if l["loan_type"] == "PERSONAL_LOAN")
        vehicle_emi = sum(l["monthly_emi"] for l in active_loans if l["loan_type"] == "VEHICLE_LOAN")
        gold_emi = sum(l["monthly_emi"] for l in active_loans if l["loan_type"] == "GOLD_LOAN")

        disb_amount = sum(d["amount"] for d in disbursements)
        cc_amount = sum(c["amount"] for c in cc_bills)
        fac_amount = sum(f["amount"] for f in running_fac)

        return {
            "monthly_emi": FeatureFormatter.format_feature(summary.get("total_monthly_emi", 0.0), confidence=conf),
            "total_monthly_obligations": FeatureFormatter.format_feature(summary.get("total_monthly_obligations", 0.0), confidence=conf),
            "estimated_cc_monthly_payment": FeatureFormatter.format_feature(summary.get("estimated_cc_monthly_payment", 0.0), confidence=conf),
            "loan_count": FeatureFormatter.format_feature(summary.get("total_loan_count_historical", 0), confidence=conf),
            "active_loan_count": FeatureFormatter.format_feature(summary.get("active_loan_count", 0), confidence=conf),
            "closed_loan_count": FeatureFormatter.format_feature(len(loans) - summary.get("active_loan_count", 0), confidence=conf),
            "distinct_lenders_count": FeatureFormatter.format_feature(summary.get("distinct_lenders_count", 0), confidence=conf),
            "secured_ratio": FeatureFormatter.format_feature(summary.get("secured_debt_ratio", 0.0), confidence=conf),
            "unsecured_ratio": FeatureFormatter.format_feature(summary.get("unsecured_debt_ratio", 0.0), confidence=conf),
            "dti": FeatureFormatter.format_feature(summary.get("dti_ratio", 0.0), confidence=conf),
            "foir": FeatureFormatter.format_feature(summary.get("foir_ready_metric", 0.0), confidence=conf),
            "credit_utilization": FeatureFormatter.missing_feature("NO_CREDIT_LIMIT_DATA"),
            "loan_stacking_score": FeatureFormatter.format_feature(1.0 if summary.get("loan_stacking_flag") else 0.0, confidence=conf, window="90D"),
            "loan_stacking_flag": FeatureFormatter.format_feature(summary.get("loan_stacking_flag", False), confidence=conf, window="90D"),
            "recent_borrowing_velocity_90d": FeatureFormatter.format_feature(summary.get("recent_borrowing_velocity_90d", 0), confidence=conf, window="90D"),
            "payment_regularity_score": FeatureFormatter.format_feature(
                1.0 if all(l["payment_regularity"] == "On-Time" for l in active_loans) else (0.70 if active_loans else 1.0),
                confidence=conf
            ),
            "lender_concentration_ratio": FeatureFormatter.format_feature(summary.get("lender_concentration_ratio", 0.0), confidence=conf),
            "missed_emi_count": FeatureFormatter.format_feature(summary.get("missed_emi_count", 0), confidence=conf),
            "home_loan_emi": FeatureFormatter.format_feature(home_emi, confidence=conf),
            "personal_loan_emi": FeatureFormatter.format_feature(personal_emi, confidence=conf),
            "vehicle_loan_emi": FeatureFormatter.format_feature(vehicle_emi, confidence=conf),
            "gold_loan_emi": FeatureFormatter.format_feature(gold_emi, confidence=conf),
            "disbursement_count_365d": FeatureFormatter.format_feature(len(disbursements), confidence=conf),
            "disbursement_total_amount_365d": FeatureFormatter.format_feature(disb_amount, confidence=conf),
            "credit_card_payment_count_365d": FeatureFormatter.format_feature(len(cc_bills), confidence=conf),
            "credit_card_total_payment_365d": FeatureFormatter.format_feature(cc_amount, confidence=conf),
            "running_facility_count": FeatureFormatter.format_feature(len(running_fac), confidence=conf),
            "running_facility_total_amount": FeatureFormatter.format_feature(fac_amount, confidence=conf)
        }

    def _empty_process_response(self) -> dict:
        return {
            "engine": "DebtEngine",
            "version": "1.0.0",
            "transaction_annotations": pd.DataFrame(),
            "entities": {
                "active_loans": [],
                "closed_loans": [],
                "emi_schedule": [],
                "lender_profiles": [],
                "running_facilities": [],
                "credit_card_payments": [],
                "disbursements": []
            },
            "features": {},
            "metadata": {
                "processed_at": datetime.now().isoformat(),
                "total_transactions": 0,
                "data_sufficiency": DataSufficiencyEvaluator.evaluate(pd.DataFrame())
            }
        }

    def _empty_response(self) -> dict:
        return {
            "engine": "DebtEngine",
            "version": "1.0.0",
            "portfolio_summary": {},
            "detected_loans": [],
            "running_facilities": [],
            "credit_card_payments": [],
            "disbursements_detected": []
        }


# ============================================================
# Module-level logger
# ============================================================
logger = logging.getLogger(__name__)


# ============================================================
# Helper: flatten FeatureFormatter wrapped values
# ============================================================
def _unwrap(val):
    """Extract raw value from FeatureFormatter dict or return as-is."""
    if isinstance(val, dict) and "value" in val:
        return val["value"]
    return val


# ============================================================
# Module-level process() — standard pipeline interface
# ============================================================
def process(transactions: pd.DataFrame, context=None) -> dict:
    """
    Analyze debt/liability features from classified transactions.

    Matches the interface of income.process(), expense.process(), etc.
    Returns a flat feature dictionary.
    """
    logger.info("Debt Engine: processing")

    if transactions.empty:
        logger.warning("Debt Engine: no transactions found")
        return {
            "total_monthly_emi": 0.0,
            "active_loan_count": 0,
            "total_loan_count": 0,
            "dti_ratio": 0.0,
            "foir": 0.0,
            "emi_burden_ratio": 0.0,
            "loan_stacking_flag": False,
            "missed_emi_count": 0,
            "secured_debt_ratio": 0.0,
            "unsecured_debt_ratio": 0.0,
            "distinct_lenders_count": 0,
            "credit_card_payment_count": 0,
            "disbursement_count": 0,
            "payment_regularity_score": 1.0,
        }

    # Get monthly income from context if available
    monthly_income = 0.0
    if context and "income" in context:
        monthly_income = context["income"].get("average_income", 0.0)

    # Ensure txn_id column exists (debt engine uses it for deduplication)
    df = transactions.copy()
    if "txn_id" not in df.columns:
        df["txn_id"] = [f"TXN_{i:06d}" for i in range(len(df))]

    engine = DebtEngine()
    raw = engine.process(df, monthly_income=monthly_income)

    # Flatten the FeatureFormatter-wrapped features dict
    raw_features = raw.get("features", {})
    features = {}
    for key, val in raw_features.items():
        features[key] = _unwrap(val)

    # Add portfolio summary metrics directly
    entities = raw.get("entities", {})
    active_loans = entities.get("active_loans", [])
    closed_loans = entities.get("closed_loans", [])

    features["total_loan_count"] = len(active_loans) + len(closed_loans)
    features["detected_loans"] = [
        {
            "loan_id": l.get("loan_id"),
            "lender": l.get("lender_name"),
            "type": l.get("loan_type"),
            "emi": l.get("monthly_emi"),
            "status": l.get("status"),
            "regularity": l.get("payment_regularity"),
        }
        for l in active_loans + closed_loans
    ]

    # --- FOIR Score & Risk Bands ---
    # FOIR = Fixed Obligations / Total True Income
    # Fixed Obligations = EMI + Insurance + NACH + Recurring Payments
    tags_col = df["tags"] if "tags" in df.columns else pd.Series([""] * len(df))
    subcat_col = df["subcategory"] if "subcategory" in df.columns else pd.Series([""] * len(df))
    
    # Calculate Total True Income (credit excluding loans, internal transfers, returns)
    is_loan_credit = (tags_col.str.contains("Loan", case=False, na=False) | subcat_col.str.contains("Loan", case=False, na=False)) & (df["credit"] > 0)
    is_return_credit = (tags_col.str.contains("Return", case=False, na=False)) & (df["credit"] > 0)
    is_internal_credit = (subcat_col.str.contains("Internal", case=False, na=False)) & (df["credit"] > 0)
    valid_income_mask = (df["credit"] > 0) & ~is_loan_credit & ~is_return_credit & ~is_internal_credit
    total_true_income = float(df[valid_income_mask]["credit"].sum())

    # Calculate Total Fixed Obligations (debits for EMI, Insurance, NACH, recurring)
    is_emi_debit = (tags_col.str.contains("EMI", case=False, na=False) | subcat_col.str.contains("Loan", case=False, na=False)) & (df["debit"] > 0)
    is_ins_debit = (tags_col.str.contains("Insurance", case=False, na=False) | subcat_col.str.contains("Insurance", case=False, na=False)) & (df["debit"] > 0)
    is_nach_debit = (tags_col.str.contains("NACH", case=False, na=False) | tags_col.str.contains("ECS", case=False, na=False)) & (df["debit"] > 0)
    fixed_obs_mask = is_emi_debit | is_ins_debit | is_nach_debit
    total_fixed_obligations = float(df[fixed_obs_mask]["debit"].sum())

    if total_true_income > 0:
        computed_foir = round(total_fixed_obligations / total_true_income, 4)
    else:
        computed_foir = 1.0 if total_fixed_obligations > 0 else 0.0

    features["foir"] = computed_foir
    features["total_fixed_obligations"] = round(total_fixed_obligations, 2)
    features["total_true_income"] = round(total_true_income, 2)

    if computed_foir < 0.30:
        features["foir_risk_band"] = "LOW_RISK"
    elif computed_foir <= 0.50:
        features["foir_risk_band"] = "MODERATE_RISK"
    elif computed_foir <= 0.70:
        features["foir_risk_band"] = "HIGH_RISK"
    else:
        features["foir_risk_band"] = "VERY_HIGH_RISK"

    # --- EMI Discipline Score ---
    all_loans = active_loans + closed_loans
    if all_loans:
        total_paid = sum(l.get("total_emis_paid", 1) for l in all_loans)
        missed = sum(l.get("missed_emis_count", 0) for l in all_loans)
        total_expected = total_paid + missed
        if total_expected > 0:
            emi_disc_score = round((total_paid / total_expected) * 100.0, 2)
        else:
            emi_disc_score = 100.0
    else:
        emi_disc_score = 100.0

    features["emi_discipline_score"] = emi_disc_score
    if emi_disc_score >= 90.0:
        features["emi_discipline_band"] = "GOOD"
    elif emi_disc_score >= 70.0:
        features["emi_discipline_band"] = "FAIR"
    else:
        features["emi_discipline_band"] = "POOR"

    # --- OD/CC Utilization ---
    running_fac = raw.get("entities", {}).get("running_facilities", [])
    features["running_facility_count"] = len(running_fac)

    logger.info(
        f"Debt Engine: EMI={features.get('monthly_emi', 0.0)}, "
        f"FOIR={features.get('foir', 0.0)} ({features.get('foir_risk_band')}), "
        f"EMI Discipline={features.get('emi_discipline_score', 100.0)}% ({features.get('emi_discipline_band')}), "
        f"active_loans={features.get('active_loan_count', 0)}"
    )

    return features
