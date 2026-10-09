import re
import math
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

try:
    from common_utils import ConfigManager, DataSufficiencyEvaluator, EvidencePackager, FeatureFormatter
except ImportError:
    from .common_utils import ConfigManager, DataSufficiencyEvaluator, EvidencePackager, FeatureFormatter

class FraudEngine:
    """
    Production-Grade Statement-Only Fraud & Anomaly Detection Engine for Bank Statement Analyzer (BSA).
    Detects rapid transfer pass-throughs, structuring, circular transactions, round amount patterns,
    cash cycling, velocity spikes, and statistical Z-score/MAD anomalies.
    Exposes process(df) as standard feature extraction interface.
    """
    _LEGITIMATE_PAYDAY_CATEGORIES = {"Investment", "Expense", "Debt / Loans", "Taxes", "Transfers"}
    _LEGITIMATE_PAYDAY_SUBCATS = (
        "EMI", "SIP", "Mutual Fund", "Insurance", "PPF", "NPS", "FD", "RD",
        "Loan", "Rent", "Credit Card", "Securities", "Trading", "Direct", "Tax"
    )

    def __init__(self, config_path=None):
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get("fraud_engine_config", {})
        self.round_modulus = self.config.get("round_txn_modulus", 1000)
        self.struct_min = self.config.get("structuring_min_amount", 40000.0)
        self.struct_max = self.config.get("structuring_max_amount", 50000.0)
        self.struct_high_min = self.config.get("structuring_high_min", 900000.0)
        self.struct_high_max = self.config.get("structuring_high_max", 1000000.0)
        self.rtgs_min = self.config.get("rtgs_min_threshold", 200000.0)
        self.atm_high = self.config.get("atm_high_threshold", 20000.0)
        self.severity_penalties = self.config.get("severity_penalties", {"LOW": 15, "MEDIUM": 40, "HIGH": 85, "CRITICAL": 200})
        self.compounding_thresh = self.config.get("compounding_high_flag_threshold", 3)
        self.compounding_mult = self.config.get("compounding_high_flag_multiplier", 1.25)

    def process(self, df: pd.DataFrame) -> dict:
        """Standard production-grade Feature Extraction interface."""
        if df.empty:
            return self._empty_process_response()

        sufficiency = DataSufficiencyEvaluator.evaluate(df)
        # Stable sort. The default quicksort reshuffles rows that share a date,
        # discarding the intra-day order recovered from the running balance in
        # validation, and the balance-mismatch detector below then reported the
        # resulting arithmetic breaks as document tampering.
        df_sorted = df.sort_values("date", kind="mergesort").reset_index(drop=True)

        flags = []
        # Standard AML & Statistical detectors
        flags.extend(self._detect_structuring(df_sorted))
        flags.extend(self._detect_high_structuring(df_sorted))
        flags.extend(self._detect_rapid_transfers(df_sorted))
        flags.extend(self._detect_cash_cycling(df_sorted))
        flags.extend(self._detect_round_transactions(df_sorted))
        flags.extend(self._detect_circular_mirroring(df_sorted))
        flags.extend(self._detect_statistical_anomalies(df_sorted))
        flags.extend(self._detect_beneficiary_concentration(df_sorted))

        # Specific irregularity checks
        flags.extend(self._detect_inward_bounces(df_sorted))
        flags.extend(self._detect_rtgs_below_minimum(df_sorted))
        flags.extend(self._detect_round_figure_tax(df_sorted))
        flags.extend(self._detect_atm_anomalies(df_sorted))
        flags.extend(self._detect_negative_computed_balance(df_sorted))
        flags.extend(self._detect_balance_mismatches(df_sorted))
        flags.extend(self._detect_counterparty_both_sides(df_sorted))
        flags.extend(self._detect_duplicate_utr(df_sorted))
        flags.extend(self._detect_cash_vs_salary(df_sorted))
        flags.extend(self._detect_quick_debit_after_salary(df_sorted))
        flags.extend(self._detect_equal_debits_credits(df_sorted))

        account_risk_level, fraud_score, conf_score = self._compute_account_fraud_scores(flags, sufficiency)

        df_annotated = self._annotate_transaction_level_fraud(df_sorted, flags)
        entities = self._reconstruct_entities(flags, account_risk_level, fraud_score, conf_score)
        features = self._build_feature_dictionary(flags, account_risk_level, fraud_score, conf_score, df_sorted, sufficiency)

        return {
            "engine": "FraudEngine",
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

    def analyze(self, df: pd.DataFrame) -> dict:
        """Legacy compatibility wrapper around process()."""
        if df.empty:
            return self._empty_response()

        res = self.process(df)
        summary = {
            "account_risk_level": res["entities"]["fraud_summary"]["account_risk_level"],
            "suspicious_score": res["entities"]["fraud_summary"]["suspicious_score"],
            "fraud_confidence_score": res["entities"]["fraud_summary"]["fraud_confidence_score"],
            "total_flags_triggered": len(res["entities"]["evidence_packages"])
        }

        return {
            "engine": "FraudEngine",
            "version": "1.0.0",
            "data_sufficiency": res["metadata"]["data_sufficiency"],
            "fraud_summary": summary,
            "flags": res["entities"]["evidence_packages"]
        }

    @staticmethod
    def _cash_rows(df: pd.DataFrame) -> pd.DataFrame:
        """Rows that moved physical cash (ATM, cash deposit machine, teller)."""
        mask = pd.Series(False, index=df.index)
        if "rail_type" in df.columns:
            mask |= df["rail_type"] == "ATM_CASH"
        if "subcategory" in df.columns:
            mask |= df["subcategory"].fillna("").str.contains(
                "ATM Withdrawal|Cash Deposit|Cash Withdrawal", case=False, na=False
            )
        return df[mask]

    def _detect_structuring(self, df: pd.DataFrame) -> list:
        """
        the structuring rule -- cash broken into amounts just under the
        Rs 50,000 reporting threshold.

        Scoped to cash movements. Applied to every transaction type it fired
        HIGH severity on any account holding two ordinary transfers in the
        Rs 40-50k band, including salary credits and mutual-fund purchases.
        """
        flags = []
        cash = self._cash_rows(df)
        if cash.empty:
            return flags

        matches = cash[((cash["debit"] >= self.struct_min) & (cash["debit"] <= self.struct_max)) |
                       ((cash["credit"] >= self.struct_min) & (cash["credit"] <= self.struct_max))]

        if len(matches) >= 2:
            txns = matches.to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_STRUCT_{len(flags)+1:03d}",
                rule_name="Structured Deposits / Withdrawals",
                severity="HIGH",
                confidence=0.85,
                explanation=f"Detected {len(matches)} transactions structured just below the ₹50,000 regulatory reporting threshold.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    @staticmethod
    def _is_reversal(row) -> bool:
        """A refund/reversal leg -- the mirror of an earlier failed transaction."""
        text = f"{row.get('subcategory', '')} {row.get('tags', '')} {row.get('description', '')}".upper()
        return any(t in text for t in ("RVSL", "REVERSAL", "REFUND", "RETURN"))

    def _detect_rapid_transfers(self, df: pd.DataFrame) -> list:
        """
        Money in and straight back out to a different party -- the classic
        pass-through/conduit pattern.

        Excludes three things that are not pass-throughs:
          * reversal pairs, where a failed ATM withdrawal is credited back and
            immediately retried (both legs are the same transaction)
          * outflows to an identified obligation such as a loan EMI or a SIP
          * matches where either leg is cash at the same ATM

        Also raises a single aggregated flag rather than one per occurrence.
        """
        flags = []
        credits = df[df["credit"] >= 20000.0].copy()
        occurrences = []

        for _, c_row in credits.iterrows():
            if self._is_reversal(c_row):
                continue
            c_date = c_row["date"]
            c_amt = c_row["credit"]
            c_payee = c_row.get("parsed_payee", "")

            # Look for debits occurring on the same day or next day matching > 85% of amount
            same_window_debits = df[(df["date"] >= c_date) & (df["date"] <= c_date + pd.Timedelta(days=1)) & (df["debit"] > 0)]

            for _, d_row in same_window_debits.iterrows():
                d_amt = d_row["debit"]
                d_payee = d_row.get("parsed_payee", "")

                if "EBA_" in str(d_payee) or "PPF" in str(d_payee):
                    continue
                if self._is_reversal(d_row):
                    continue
                # Both legs cash at the same ATM: a retry, not a transfer.
                if c_row.get("rail_type") == "ATM_CASH" and d_row.get("rail_type") == "ATM_CASH":
                    continue
                # Outflow to a recognised obligation is a payment, not a conduit.
                d_sub = str(d_row.get("subcategory", ""))
                if str(d_row.get("category", "")) == "Investment" or \
                        any(t.upper() in d_sub.upper() for t in self._LEGITIMATE_PAYDAY_SUBCATS):
                    continue

                ratio = d_amt / c_amt
                if 0.85 <= ratio <= 1.05 and c_payee != d_payee:
                    occurrences.append((c_row, d_row))
                    break

        if occurrences:
            c_row, d_row = occurrences[0]
            ev = EvidencePackager.create_evidence(
                flag_id="FRD_RAPID_001",
                rule_name="Rapid Inflow-Outflow Pass-through",
                severity="HIGH",
                confidence=0.88,
                explanation=(
                    f"{len(occurrences)} inflows were transferred out to a different "
                    f"counterparty within 24 hours at 85-105% of the amount received "
                    f"(e.g. ₹{c_row['credit']:,.2f} from {c_row.get('parsed_payee', '')} "
                    f"out to {d_row.get('parsed_payee', '')})."
                ),
                supporting_txns=[c_row.to_dict(), d_row.to_dict()]
            )
            flags.append(ev)
        return flags

    def _detect_cash_cycling(self, df: pd.DataFrame) -> list:
        flags = []
        if "rail_type" not in df.columns:
            return flags
        atm_rows = df[df["rail_type"] == "ATM_CASH"]
        large_cash = atm_rows[atm_rows["debit"] >= 25000.0]

        if len(large_cash) >= 3:
            txns = large_cash.to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_CASH_{len(flags)+1:03d}",
                rule_name="High Velocity ATM Cash Withdrawals",
                severity="MEDIUM",
                confidence=0.75,
                explanation=f"Detected {len(large_cash)} large cash withdrawals exceeding ₹25,000 in short duration.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_round_transactions(self, df: pd.DataFrame) -> list:
        flags = []
        # Systematic investing is round by design -- a Rs 5,000 monthly SIP is
        # not a laundering signal. Excluding investments stops disciplined
        # savers being penalised for the very behaviour that makes them
        # creditworthy (one statement had 173 round SIP debits).
        candidates = df
        if "category" in df.columns:
            candidates = df[df["category"] != "Investment"]
        round_rows = candidates[(candidates["debit"] > 10000.0)
                                & (candidates["debit"] % self.round_modulus == 0)]
        
        round_ratio = len(round_rows) / len(df) if len(df) > 0 else 0.0
        if round_ratio > 0.25 and len(round_rows) >= 5:
            txns = round_rows.head(10).to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_ROUND_{len(flags)+1:03d}",
                rule_name="High Frequency Round Transactions",
                severity="LOW",
                confidence=0.65,
                explanation=f"{round_ratio*100:.1f}% of transactions are exact multiples of ₹{self.round_modulus}.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_circular_mirroring(self, df: pd.DataFrame) -> list:
        flags = []
        entity_series = None
        for col in ["merchant_entity", "counterparty_key", "parsed_payee"]:
            if col in df.columns:
                s = df[col].fillna("").astype(str).str.strip()
                if (s != "").any():
                    entity_series = s
                    break
        if entity_series is None:
            if "description" not in df.columns:
                return flags
            def _extract_cp(desc):
                d = str(desc or "").upper()
                m = re.search(r'(?:UPI/[A-Z0-9_\-\.]+/|NEFT[-/ ]|RTGS[-/ ]|IMPS[-/ ]|INF/|TPC/)([A-Z0-9_ \.\-]+)', d)
                if m:
                    return m.group(1).strip()
                return ""
            entity_series = df["description"].apply(_extract_cp)
            if not (entity_series != "").any():
                return flags

        work = df.copy()
        work["_entity"] = entity_series
        work = work[work["_entity"] != ""]
        # Exclude internal sweeps, self-transfers, bank interest, and tax refunds
        excluded_entities = {"SELF", "INTERNAL", "HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "PPF", "EBA_", "SWEEP", "MOD", "TAX", "INTEREST"}
        work = work[~work["_entity"].str.upper().apply(lambda x: any(k in x for k in excluded_entities))]
        if work.empty:
            return flags

        credits_by_payee = work.groupby("_entity")["credit"].sum()
        debits_by_payee = work.groupby("_entity")["debit"].sum()

        common_payees = set(credits_by_payee[credits_by_payee > 10000.0].index).intersection(
            set(debits_by_payee[debits_by_payee > 10000.0].index)
        )

        for payee in common_payees:
            c_amt = float(credits_by_payee[payee])
            d_amt = float(debits_by_payee[payee])
            diff_pct = abs(c_amt - d_amt) / max(c_amt, d_amt)

            if diff_pct <= 0.15:
                matching_rows = work[work["_entity"] == payee].to_dict("records")
                circ_amt = min(c_amt, d_amt) * 2
                ev = EvidencePackager.create_evidence(
                    flag_id=f"FRD_CIRCULAR_{len(flags)+1:03d}",
                    rule_name="Inflow-Outflow Mirroring / Circular Transfers",
                    severity="HIGH",
                    confidence=0.90,
                    explanation=(
                        f"Symmetric money movement detected with entity {payee} "
                        f"(Total Inflow: ₹{c_amt:,.2f}, Outflow: ₹{d_amt:,.2f}, Mirrored Turnover: ₹{circ_amt:,.2f})."
                    ),
                    supporting_txns=matching_rows
                )
                ev["circular_amount"] = circ_amt
                flags.append(ev)
        return flags

    def _detect_statistical_anomalies(self, df: pd.DataFrame) -> list:
        flags = []
        debit_mask = df["debit"] > 0
        debits = df[debit_mask]["debit"]
        if len(debits) < 10:
            return flags

        median = float(np.median(debits))
        mad = float(np.median(np.abs(debits - median)))

        if mad == 0:
            return flags

        # Exclude recognized legitimate obligations (EMIs, SIPs, Investments, Taxes) from being flagged as anomalous outliers
        cat_col = df["category"].fillna("").astype(str) if "category" in df.columns else pd.Series([""] * len(df))
        sub_col = df["subcategory"].fillna("").astype(str) if "subcategory" in df.columns else pd.Series([""] * len(df))
        tags_col = df["tags"].fillna("").astype(str) if "tags" in df.columns else pd.Series([""] * len(df))
        is_obligation = cat_col.str.contains("Investment|Debt|Loan|Tax|Insurance|Transfer|Savings", case=False, na=False) | \
                        sub_col.str.contains("Loan|EMI|SIP|Mutual|NPS|PPF|Tax|Insurance|Card|Securities|Trading", case=False, na=False) | \
                        tags_col.str.contains("Loan|EMI|SIP|Investment|Tax|Insurance", case=False, na=False)

        mod_z_scores = 0.6745 * np.abs(df["debit"] - median) / mad
        anomalies = df[debit_mask & (~is_obligation) & (mod_z_scores > self.config.get("mad_multiplier", 6.0))]

        if len(anomalies) >= 3:
            txns = anomalies.head(5).to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_MAD_{len(flags)+1:03d}",
                rule_name="Statistical Outlier (Median Absolute Deviation)",
                severity="MEDIUM",
                confidence=0.80,
                explanation=f"Detected {len(anomalies)} unexplained transaction amounts deviating significantly (>6x MAD) from account baseline median.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_beneficiary_concentration(self, df: pd.DataFrame) -> list:
        flags = []
        if "parsed_payee" not in df.columns:
            return flags
        debit_rows = df[df["debit"] > 0]
        total_debits = debit_rows["debit"].sum()

        if total_debits == 0:
            return flags

        top_beneficiary = debit_rows.groupby("parsed_payee")["debit"].sum().sort_values(ascending=False)
        if not top_beneficiary.empty:
            top_payee = top_beneficiary.index[0]
            top_amount = top_beneficiary.iloc[0]
            ratio = top_amount / total_debits

            if ratio > 0.45 and not any(k in str(top_payee) for k in ["HDFC", "ICICI", "SBI", "EBA_", "PPF"]):
                txns = debit_rows[debit_rows["parsed_payee"] == top_payee].head(5).to_dict("records")
                ev = EvidencePackager.create_evidence(
                    flag_id=f"FRD_CONC_{len(flags)+1:03d}",
                    rule_name="High Beneficiary Concentration",
                    severity="MEDIUM",
                    confidence=0.72,
                    explanation=f"{ratio*100:.1f}% of total debits (₹{top_amount:,.2f}) were sent to a single entity ({top_payee}).",
                    supporting_txns=txns
                )
                flags.append(ev)
        return flags

    def _detect_high_structuring(self, df: pd.DataFrame) -> list:
        flags = []
        high_struct = df[
            (df["credit"] >= self.struct_high_min) & (df["credit"] <= self.struct_high_max) |
            (df["debit"] >= self.struct_high_min) & (df["debit"] <= self.struct_high_max)
        ]
        if not high_struct.empty:
            txns = high_struct.to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_HIGH_STRUCT_{len(flags)+1:03d}",
                rule_name="High Value Structuring (₹9L - ₹10L)",
                severity="HIGH",
                confidence=0.92,
                explanation=f"Detected {len(high_struct)} transactions structured just below the ₹10 Lakh statutory AML reporting threshold.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_rtgs_below_minimum(self, df: pd.DataFrame) -> list:
        flags = []
        tags_col = df["tags"] if "tags" in df.columns else pd.Series([""] * len(df))
        desc_col = df["description"].astype(str)
        is_rtgs = tags_col.str.contains("RTGS", case=False, na=False) | desc_col.str.startswith("RTGS")
        small_rtgs = df[is_rtgs & (df["debit"] > 0) & (df["debit"] < self.rtgs_min)]
        if not small_rtgs.empty:
            txns = small_rtgs.to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_RTGS_MIN_{len(flags)+1:03d}",
                rule_name="RTGS Payment Below Minimum Threshold",
                severity="MEDIUM",
                confidence=0.85,
                explanation=f"Detected {len(small_rtgs)} RTGS debits below the RBI statutory minimum of ₹2,00,000.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_round_figure_tax(self, df: pd.DataFrame) -> list:
        flags = []
        tags_col = df["tags"] if "tags" in df.columns else pd.Series([""] * len(df))
        desc_col = df["description"].astype(str)
        is_tax = tags_col.str.contains("Tax", case=False, na=False) | desc_col.str.contains("TAX PAYMENT", case=False, na=False)
        round_tax = df[is_tax & (df["debit"] > 0) & (df["debit"] % 1000 == 0)]
        if len(round_tax) >= 2:
            txns = round_tax.to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_ROUND_TAX_{len(flags)+1:03d}",
                rule_name="Round Figure Tax Payments",
                severity="LOW",
                confidence=0.70,
                explanation=f"Detected {len(round_tax)} tax payment debits that are exact multiples of ₹1,000.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_atm_anomalies(self, df: pd.DataFrame) -> list:
        flags = []
        tags_col = df["tags"] if "tags" in df.columns else pd.Series([""] * len(df))
        desc_col = df["description"].astype(str)
        is_atm = tags_col.str.contains("ATM", case=False, na=False) | desc_col.str.contains("ATM", case=False, na=False)
        atm_txns = df[is_atm & (df["debit"] > 0)].sort_values("date")
        if atm_txns.empty:
            return flags

        # 1. Single massive ATM withdrawal (> 50k)
        huge_atm = atm_txns[atm_txns["debit"] >= 50000.0]
        if not huge_atm.empty:
            txns = huge_atm.head(5).to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_ATM_HIGH_{len(flags)+1:03d}",
                rule_name="Massive Single ATM Cash Withdrawal",
                severity="MEDIUM",
                confidence=0.80,
                explanation=f"Detected {len(huge_atm)} single ATM cash withdrawals exceeding ₹50,000.",
                supporting_txns=txns
            )
            flags.append(ev)

        # 2. Rolling 7-day high-frequency ATM cash velocity (>= 3 large withdrawals within 7 days)
        large_atm = atm_txns[atm_txns["debit"] >= self.atm_high]
        if len(large_atm) >= 3:
            clustered = []
            dates = large_atm["date"].values
            for i in range(len(large_atm) - 2):
                d_start = pd.to_datetime(dates[i])
                d_end = pd.to_datetime(dates[i + 2])
                if (d_end - d_start).days <= 7:
                    clustered.append(large_atm.iloc[i:i+3])
            if clustered:
                txns = pd.concat(clustered).drop_duplicates().head(5).to_dict("records")
                ev = EvidencePackager.create_evidence(
                    flag_id=f"FRD_ATM_VEL_{len(flags)+1:03d}",
                    rule_name="High Velocity ATM Cash Withdrawals",
                    severity="MEDIUM",
                    confidence=0.85,
                    explanation=f"Detected high velocity cash extraction: 3+ ATM withdrawals exceeding ₹{self.atm_high:,.0f} within a 7-day rolling window.",
                    supporting_txns=txns
                )
                flags.append(ev)
        return flags

    def _detect_negative_computed_balance(self, df: pd.DataFrame) -> list:
        flags = []
        if "balance" not in df.columns or df.empty:
            return flags
        neg_rows = df[df["balance"] < 0]
        if not neg_rows.empty:
            txns = neg_rows.head(5).to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_NEG_BAL_{len(flags)+1:03d}",
                rule_name="Negative Computed Running Balance",
                severity="HIGH",
                confidence=0.95,
                explanation=f"Account balance dropped below zero in {len(neg_rows)} instances without overdraft authorization.",
                supporting_txns=txns
            )
            flags.append(ev)
        return flags

    def _detect_balance_mismatches(self, df: pd.DataFrame) -> list:
        flags = []
        if len(df) < 2 or "balance" not in df.columns:
            return flags
        
        # Verify running balance: Balance[i] = Balance[i-1] + Credit[i] - Debit[i]
        calc_bal = df["balance"].iloc[0]
        mismatch_count = 0
        mismatch_rows = []

        for i in range(1, len(df)):
            row = df.iloc[i]
            expected = calc_bal + float(row.get("credit", 0)) - float(row.get("debit", 0))
            actual = float(row.get("balance", 0))
            if abs(actual) > 0 and abs(expected - actual) / abs(actual) > 0.02:
                mismatch_count += 1
                if len(mismatch_rows) < 5:
                    mismatch_rows.append(row.to_dict())
            # Resynchronise on the printed balance so a single genuine break
            # is reported once instead of cascading into every later row.
            calc_bal = actual

        if mismatch_count > 0:
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_BAL_MISMATCH_{len(flags)+1:03d}",
                rule_name="Running Balance Mathematical Mismatch",
                severity="HIGH",
                confidence=0.95,
                explanation=f"Detected {mismatch_count} instances where computed running balance differs by >2% from printed statement balance (potential document tampering).",
                supporting_txns=mismatch_rows
            )
            flags.append(ev)
        return flags

    def _detect_counterparty_both_sides(self, df: pd.DataFrame) -> list:
        flags = []
        cp_col = "merchant_entity" if "merchant_entity" in df.columns else ("parsed_payee" if "parsed_payee" in df.columns else "")
        if not cp_col:
            return flags
        valid_df = df[df[cp_col].astype(str).str.strip() != ""]
        credit_cps = set(valid_df[valid_df["credit"] > 10000.0][cp_col])
        debit_cps = set(valid_df[valid_df["debit"] > 10000.0][cp_col])
        overlap = credit_cps.intersection(debit_cps)
        # Exclude self/bank/standard entities
        overlap = {c for c in overlap if not any(k in c.upper() for k in ["SELF", "INTERNAL", "HDFC", "ICICI", "SBI", "AXIS", "PPF", "EBA_"])}
        if overlap:
            matched_txns = valid_df[valid_df[cp_col].isin(overlap)].head(10).to_dict("records")
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_CP_ROTATION_{len(flags)+1:03d}",
                rule_name="Counterparty Money Rotation (Both Credits & Debits)",
                severity="MEDIUM",
                confidence=0.85,
                explanation=f"Identified {len(overlap)} counterparties ({', '.join(list(overlap)[:3])}) present on both inflow and outflow sides.",
                supporting_txns=matched_txns
            )
            flags.append(ev)
        return flags

    def _detect_duplicate_utr(self, df: pd.DataFrame) -> list:
        flags = []
        if "description" not in df.columns:
            return flags
        import re
        # A reference repeating across months is a recurring mandate, not a
        # duplicate: a monthly SIP or EMI reuses its mandate reference by
        # design. Genuine double-posting means the same reference AND the same
        # amount AND the same date. Requiring all three stops standing
        # instructions being reported as tampering.
        utr_pattern = re.compile(r'\b[A-Z0-9]{12,22}\b')
        seen = {}
        dup_txns = []

        for _, row in df.iterrows():
            if str(row.get("category", "")) == "Investment":
                continue
            amount = float(row.get("debit", 0) or 0) + float(row.get("credit", 0) or 0)
            date_key = str(row.get("date", ""))
            for utr in utr_pattern.findall(str(row["description"])):
                if len(utr) >= 12 and not utr.isdigit():
                    key = (utr, round(amount, 2), date_key)
                    if key in seen:
                        dup_txns.append(row.to_dict())
                    else:
                        seen[key] = row.to_dict()

        if len(dup_txns) >= 1:
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_DUP_UTR_{len(flags)+1:03d}",
                rule_name="Duplicate UTR / Transaction Reference",
                severity="HIGH",
                confidence=0.90,
                explanation=(
                    f"Detected {len(dup_txns)} transactions sharing an identical "
                    f"UTR/reference, amount and date."
                ),
                supporting_txns=dup_txns[:5]
            )
            flags.append(ev)
        return flags

    def _detect_cash_vs_salary(self, df: pd.DataFrame) -> list:
        flags = []
        tags_col = df["tags"] if "tags" in df.columns else pd.Series([""] * len(df))
        is_cash = tags_col.str.contains("Cash", case=False, na=False)
        is_sal = tags_col.str.contains("Salary", case=False, na=False)

        total_cash = float(df[is_cash & (df["credit"] > 0)]["credit"].sum())
        total_sal = float(df[is_sal & (df["credit"] > 0)]["credit"].sum())

        if total_sal > 0 and total_cash > (1.5 * total_sal):
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_CASH_SAL_{len(flags)+1:03d}",
                rule_name="Cash Deposits Exceed 1.5x Salary",
                severity="MEDIUM",
                confidence=0.80,
                explanation=f"Total cash deposits (₹{total_cash:,.2f}) exceed declared salary inflow (₹{total_sal:,.2f}) by {(total_cash/total_sal):.1f}x.",
                supporting_txns=df[is_cash & (df["credit"] > 0)].head(5).to_dict("records")
            )
            flags.append(ev)
        return flags

    def _detect_quick_debit_after_salary(self, df: pd.DataFrame) -> list:
        """
        the conduit-account rule -- salary arriving and leaving immediately, which
        can indicate the account is being used as a conduit.

        Excludes legitimate obligations: EMIs, SIPs, Tax, Insurance, Brokerage/Investments,
        and recognized recurring mandates.
        """
        flags = []
        tags_col = df["tags"].fillna("").astype(str) if "tags" in df.columns else pd.Series([""] * len(df))
        desc_col = df["description"].fillna("").astype(str) if "description" in df.columns else pd.Series([""] * len(df))
        is_sal = tags_col.str.contains("Salary", case=False, na=False) & (df["credit"] > 0)
        sal_txns = df[is_sal]
        if sal_txns.empty:
            return flags

        cat_col = df["category"].fillna("").astype(str) if "category" in df.columns else pd.Series([""] * len(df), index=df.index)
        sub_col = df["subcategory"].fillna("").astype(str) if "subcategory" in df.columns else pd.Series([""] * len(df), index=df.index)
        is_obligation = (
            cat_col.str.contains("Investment|Debt|Loan|Tax|Insurance|Savings|Transfer", case=False, na=False) |
            sub_col.str.contains("Loan|EMI|SIP|Mutual|NPS|PPF|Tax|Insurance|Direct|Card|Securities|Trading", case=False, na=False) |
            tags_col.str.contains("Loan|EMI|SIP|Investment|Tax|Insurance|Self-Transfer", case=False, na=False) |
            desc_col.str.contains("LOAN|EMI|SIP|MUTUAL|ACH|NACH|INSURANCE|TAX|DIRECT|SECURITIES|BROKING|PPF|NPS", case=False, na=False)
        )

        occurrences = []
        for _, sal_row in sal_txns.iterrows():
            sal_date = sal_row["date"]
            sal_amt = sal_row["credit"]
            next_day = sal_date + pd.Timedelta(days=1)
            window = (df["date"] >= sal_date) & (df["date"] <= next_day)
            quick_debits = df[window & (df["debit"] > (0.50 * sal_amt)) & (~is_obligation)]
            for _, d_row in quick_debits.iterrows():
                occurrences.append((sal_row, d_row))

        if occurrences:
            sal_row, d_row = occurrences[0]
            total = sum(float(d["debit"]) for _, d in occurrences)
            ev = EvidencePackager.create_evidence(
                flag_id="FRD_SAL_QUICK_DR_001",
                rule_name="Immediate Large Debit After Salary (>50% in 1 Day)",
                severity="MEDIUM",
                confidence=0.82,
                explanation=(
                    f"{len(occurrences)} salary credits were followed within 24 hours by an "
                    f"unidentified debit exceeding 50% of the credit (total ₹{total:,.2f}). "
                    f"Payments to recognised obligations are excluded."
                ),
                supporting_txns=[sal_row.to_dict(), d_row.to_dict()]
            )
            flags.append(ev)
        return flags

    def _detect_equal_debits_credits(self, df: pd.DataFrame) -> list:
        flags = []
        if len(df) < 15:
            return flags
        total_dr = float(df["debit"].sum())
        total_cr = float(df["credit"].sum())
        if total_cr > 100000.0 and abs(total_dr - total_cr) / total_cr < 0.02:
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_EQUAL_DR_CR_{len(flags)+1:03d}",
                rule_name="Symmetric Pass-Through (Equal Debits & Credits)",
                severity="LOW",
                confidence=0.75,
                explanation=f"Total debits (₹{total_dr:,.2f}) match total credits (₹{total_cr:,.2f}) within 2% margin in high volume account.",
                supporting_txns=df.head(5).to_dict("records")
            )
            flags.append(ev)
        return flags

    def _detect_inward_bounces(self, df: pd.DataFrame) -> list:
        """
        Detects inward cheque bounces, NACH / ECS mandate dishonours, and return charges.
        Inward bounces occur when an issued payment or recurring mandate fails due to insufficient funds,
        representing the strongest institutional signal of repayment default.
        """
        flags = []
        if df.empty or "description" not in df.columns:
            return flags

        desc_col = df["description"].fillna("").astype(str).str.upper()

        inward_bounce_patterns = [
            r'\bCHQ\s+(?:RET(?:URN)?|RTN)\b',
            r'\bINW(?:ARD)?\s+(?:RET(?:URN)?|RTN|CLG\s+RET)\b',
            r'\bNACH\s+(?:RET(?:URN)?|RTN|REJECT|FAIL)\b',
            r'\bECS\s+(?:RET(?:URN)?|RTN|REJECT|FAIL)\b',
            r'\bBOUNCE\s+CH(?:AR)?G',
            r'\bRETURN\s+CH(?:AR)?G',
            r'\bRET(?:URN)?\s+CHARGES?\b',
            r'\bDISHONO?UR\b',
            r'\bMANDATE\s+(?:REJECT|FAIL|RETURN)\b',
            r'\bINSUFFICIENT\s+FUNDS?\b',
            r'\bCHEQUE\s+BOUNCE\b',
            r'\bCHQ\s+BOUNCE\b',
            r'\bACH\s+DEBIT\s+RETURN\b',
        ]
        combined_pattern = '|'.join(inward_bounce_patterns)
        outward_pattern = r'\b(?:OUT(?:WARD)?\s+RET|DEP\s+RET|CLG\s+RET\s+DEP)\b'

        mask = desc_col.str.contains(combined_pattern, regex=True, na=False) & (
            ~desc_col.str.contains(outward_pattern, regex=True, na=False)
        )
        bounce_txns = df[mask]

        if not bounce_txns.empty:
            count = len(bounce_txns)
            total_amt = float(bounce_txns["debit"].sum() + bounce_txns["credit"].sum())
            severity = "CRITICAL" if count >= 2 else "HIGH"
            ev = EvidencePackager.create_evidence(
                flag_id=f"FRD_BOUNCE_{len(flags)+1:03d}",
                rule_name="Inward Cheque / NACH Mandate Dishonour (Insufficient Funds)",
                severity=severity,
                confidence=0.95,
                explanation=(
                    f"Detected {count} inward cheque / NACH mandate dishonour or bounce event(s) "
                    f"(Total Impact: ₹{total_amt:,.2f}). Inward returns indicate repayment default risk."
                ),
                supporting_txns=bounce_txns.head(10).to_dict("records")
            )
            ev["bounce_count"] = count
            ev["bounce_amount"] = total_amt
            flags.append(ev)

        return flags

    def _compute_account_fraud_scores(self, flags: list, sufficiency: dict) -> tuple:
        if not flags:
            return "LOW", 0.0, 1.0

        # Weights come from rules_config.json ("severity_penalties"), which was
        # previously defined and never read while the code used a much steeper
        # hardcoded scale (LOW 10 / MEDIUM 25 / HIGH 45 / CRITICAL 70). On that
        # scale any two HIGH findings summed past the CRITICAL threshold, so
        # every statement examined -- including stable salaried accounts with
        # SIPs and a home loan -- came back CRITICAL and the score carried no
        # information.
        # Normalized weights for 0-100 fraud score scale (distinct from 1000-pt credit score point deductions)
        fraud_weights = self.config.get("fraud_risk_weights", {"LOW": 2.5, "MEDIUM": 6.0, "HIGH": 15.0, "CRITICAL": 35.0})
        total_score = sum(fraud_weights.get(f.get("severity", "LOW"), 2.5) * f.get("confidence", 0.8)
                          for f in flags)
        fraud_score = round(min(100.0, total_score), 2)

        if fraud_score >= 65.0:
            risk_level = "CRITICAL"
        elif fraud_score >= 40.0:
            risk_level = "HIGH"
        elif fraud_score >= 20.0:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        conf_mult = sufficiency.get("confidence_multiplier", 1.0)
        avg_flag_conf = float(np.mean([f["confidence"] for f in flags])) if flags else 1.0
        conf_score = round(min(1.0, max(0.5, avg_flag_conf * conf_mult)), 2)

        return risk_level, fraud_score, conf_score

    def _annotate_transaction_level_fraud(self, df: pd.DataFrame, flags: list) -> pd.DataFrame:
        df = df.copy()
        df["fraud_flags"] = [[] for _ in range(len(df))]
        df["suspicious_score"] = 0.0
        df["severity"] = "NONE"
        df["rule_triggered"] = "NONE"
        df["confidence"] = 0.0

        txn_map = {}
        for flag in flags:
            rule = flag.get("rule_name")
            sev = flag.get("severity")
            conf = flag.get("confidence", 0.8)
            for st in flag.get("supporting_transactions", []):
                tid = st.get("txn_id")
                if tid:
                    if tid not in txn_map:
                        txn_map[tid] = []
                    txn_map[tid].append({"rule": rule, "severity": sev, "confidence": conf, "flag_id": flag.get("flag_id")})

        sev_order = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

        for idx, row in df.iterrows():
            tid = row.get("txn_id")
            if tid in txn_map:
                matched_flags = txn_map[tid]
                flag_names = [f["rule"] for f in matched_flags]
                highest_sev = max(matched_flags, key=lambda x: sev_order.get(x["severity"], 0))
                
                df.at[idx, "fraud_flags"] = flag_names
                df.at[idx, "rule_triggered"] = highest_sev["rule"]
                df.at[idx, "severity"] = highest_sev["severity"]
                df.at[idx, "confidence"] = highest_sev["confidence"]
                df.at[idx, "suspicious_score"] = round(sev_order.get(highest_sev["severity"], 0) * 25.0, 2)

        return df

    def _reconstruct_entities(self, flags: list, risk_level: str, fraud_score: float, conf_score: float) -> dict:
        fraud_chains = []
        suspicious_beneficiaries = []
        high_risk_merchants = []

        for flag in flags:
            rule = flag.get("rule_name", "")
            txns = flag.get("supporting_transactions", [])
            
            if "Pass-through" in rule or "Mirroring" in rule:
                fraud_chains.append({
                    "flag_id": flag.get("flag_id"),
                    "rule": rule,
                    "severity": flag.get("severity"),
                    "chain_length": len(txns),
                    "transactions": txns
                })
            
            if "Concentration" in rule or "Mirroring" in rule:
                for t in txns:
                    desc = t.get("description", "")
                    suspicious_beneficiaries.append({
                        "payee_description": desc,
                        "flag_id": flag.get("flag_id"),
                        "severity": flag.get("severity")
                    })

        return {
            "fraud_events": [
                {
                    "flag_id": f["flag_id"],
                    "rule_name": f["rule_name"],
                    "severity": f["severity"],
                    "confidence": f["confidence"],
                    "explanation": f["explanation"]
                } for f in flags
            ],
            "fraud_chains": fraud_chains,
            "suspicious_beneficiaries": suspicious_beneficiaries,
            "high_risk_merchants": high_risk_merchants,
            "evidence_packages": flags,
            "fraud_summary": {
                "account_risk_level": risk_level,
                "suspicious_score": fraud_score,
                "fraud_confidence_score": conf_score
            }
        }

    def _build_feature_dictionary(self, flags: list, risk_level: str, fraud_score: float, conf_score: float, df: pd.DataFrame, sufficiency: dict) -> dict:
        conf = sufficiency.get("confidence_multiplier", 1.0)
        risk_map = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.0, "CRITICAL": 4.0}

        structuring_flags = [f for f in flags if "Structured" in f["rule_name"]]
        rapid_flags = [f for f in flags if "Pass-through" in f["rule_name"]]
        cash_flags = [f for f in flags if "Cash" in f["rule_name"]]
        round_flags = [f for f in flags if "Round" in f["rule_name"]]
        circular_flags = [f for f in flags if "Mirroring" in f["rule_name"]]
        mad_flags = [f for f in flags if "Statistical" in f["rule_name"]]
        conc_flags = [f for f in flags if "Concentration" in f["rule_name"]]

        round_txns = df[(df["debit"] > 10000.0) & (df["debit"] % self.round_modulus == 0)]
        round_ratio = round(len(round_txns) / len(df), 4) if len(df) > 0 else 0.0

        bounce_flags = [f for f in flags if "Dishonour" in f.get("rule_name", "") or "BOUNCE" in f.get("flag_id", "")]
        inward_bounce_count = sum(f.get("bounce_count", 1) for f in bounce_flags)
        inward_bounce_amount = sum(f.get("bounce_amount", 0.0) for f in bounce_flags)
        circular_turnover_amt = sum(f.get("circular_amount", 0.0) for f in circular_flags)

        top_payee_ratio = 0.0
        debit_rows = df[df["debit"] > 0]
        if not debit_rows.empty and debit_rows["debit"].sum() > 0 and "parsed_payee" in debit_rows.columns:
            top_amt = debit_rows.groupby("parsed_payee")["debit"].sum().max()
            top_payee_ratio = round(top_amt / debit_rows["debit"].sum(), 4)

        # Calibrated Severity Point Deductions
        severity_penalty_map = self.severity_penalties
        high_flags_count = sum(1 for f in flags if f.get("severity") in ("HIGH", "CRITICAL"))
        base_penalty_pts = sum(severity_penalty_map.get(f.get("severity", "LOW"), 15) for f in flags)
        if high_flags_count >= self.compounding_thresh:
            total_penalty_pts = int(round(base_penalty_pts * self.compounding_mult))
        else:
            total_penalty_pts = int(round(base_penalty_pts))

        # AML Risk Score (0 - 100)
        aml_score = min(100.0, round(float(fraud_score * 0.85 + (len(circular_flags) * 15.0) + (len(structuring_flags) * 10.0)), 2))
        if aml_score <= 25.0:
            aml_band = "LOW"
        elif aml_score <= 50.0:
            aml_band = "MODERATE"
        elif aml_score <= 75.0:
            aml_band = "HIGH"
        else:
            aml_band = "CRITICAL"

        return {
            "fraud_score": FeatureFormatter.format_feature(fraud_score, confidence=conf_score),
            "account_risk_level_numeric": FeatureFormatter.format_feature(risk_map.get(risk_level, 1.0), confidence=conf_score),
            "aml_risk_score": FeatureFormatter.format_feature(aml_score, confidence=conf_score),
            "aml_risk_band": FeatureFormatter.format_feature(aml_band, confidence=conf_score),
            "irregularity_penalty_points": FeatureFormatter.format_feature(total_penalty_pts, confidence=conf),
            "high_severity_flag_count": FeatureFormatter.format_feature(high_flags_count, confidence=conf),
            "inward_bounce_count": FeatureFormatter.format_feature(inward_bounce_count, confidence=conf),
            "inward_bounce_amount": FeatureFormatter.format_feature(inward_bounce_amount, confidence=conf),
            "circular_turnover_amount": FeatureFormatter.format_feature(circular_turnover_amt, confidence=conf),
            "velocity_score": FeatureFormatter.format_feature(1.0 if rapid_flags or cash_flags else 0.0, confidence=conf),
            "cash_cycling_score": FeatureFormatter.format_feature(min(100.0, len(cash_flags) * 35.0), confidence=conf),
            "rapid_transfer_score": FeatureFormatter.format_feature(min(100.0, len(rapid_flags) * 45.0), confidence=conf),
            "rapid_transfer_count": FeatureFormatter.format_feature(len(rapid_flags), confidence=conf),
            "merchant_risk_score": FeatureFormatter.format_feature(min(100.0, len(conc_flags) * 30.0), confidence=conf),
            "round_transaction_score": FeatureFormatter.format_feature(round(round_ratio * 100.0, 2), confidence=conf),
            "round_transaction_ratio": FeatureFormatter.format_feature(round_ratio, confidence=conf),
            "beneficiary_concentration": FeatureFormatter.format_feature(top_payee_ratio, confidence=conf),
            "structuring_score": FeatureFormatter.format_feature(min(100.0, len(structuring_flags) * 40.0), confidence=conf),
            "structuring_flag_count": FeatureFormatter.format_feature(len(structuring_flags), confidence=conf),
            "circular_mirroring_score": FeatureFormatter.format_feature(min(100.0, len(circular_flags) * 50.0), confidence=conf),
            "statistical_anomaly_count": FeatureFormatter.format_feature(len(mad_flags), confidence=conf),
            "total_fraud_flags_triggered": FeatureFormatter.format_feature(len(flags), confidence=conf)
        }

    def _empty_process_response(self) -> dict:
        return {
            "engine": "FraudEngine",
            "version": "1.0.0",
            "transaction_annotations": pd.DataFrame(),
            "entities": {
                "fraud_events": [],
                "fraud_chains": [],
                "suspicious_beneficiaries": [],
                "high_risk_merchants": [],
                "evidence_packages": [],
                "fraud_summary": {"account_risk_level": "LOW", "suspicious_score": 0.0, "fraud_confidence_score": 1.0}
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
            "engine": "FraudEngine",
            "version": "1.0.0",
            "fraud_summary": {
                "account_risk_level": "LOW",
                "suspicious_score": 0.0,
                "fraud_confidence_score": 1.0,
                "total_flags_triggered": 0
            },
            "flags": []
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
    Analyze fraud/anomaly features from classified transactions.

    Matches the interface of income.process(), expense.process(), etc.
    Returns a flat feature dictionary.
    """
    logger.info("Fraud Engine: processing")

    if transactions.empty:
        logger.warning("Fraud Engine: no transactions found")
        return {
            "fraud_score": 0.0,
            "account_risk_level": "LOW",
            "total_fraud_flags": 0,
            "structuring_score": 0.0,
            "rapid_transfer_score": 0.0,
            "cash_cycling_score": 0.0,
            "circular_mirroring_score": 0.0,
            "circular_turnover_amount": 0.0,
            "inward_bounce_count": 0,
            "inward_bounce_amount": 0.0,
            "beneficiary_concentration": 0.0,
            "round_transaction_ratio": 0.0,
        }

    # Ensure txn_id column exists (fraud engine references it)
    df = transactions.copy()
    if "txn_id" not in df.columns:
        df["txn_id"] = [f"TXN_{i:06d}" for i in range(len(df))]

    engine = FraudEngine()
    raw = engine.process(df)

    # Flatten the FeatureFormatter-wrapped features dict
    raw_features = raw.get("features", {})
    features = {}
    for key, val in raw_features.items():
        features[key] = _unwrap(val)

    features["inward_bounce_count"] = int(_unwrap(raw_features.get("inward_bounce_count", 0)) or 0)
    features["inward_bounce_amount"] = float(_unwrap(raw_features.get("inward_bounce_amount", 0.0)) or 0.0)
    features["circular_turnover_amount"] = float(_unwrap(raw_features.get("circular_turnover_amount", 0.0)) or 0.0)

    # Add summary-level fields
    entities = raw.get("entities", {})
    summary = entities.get("fraud_summary", {})
    features["account_risk_level"] = summary.get("account_risk_level", "LOW")
    features["total_fraud_flags"] = len(entities.get("evidence_packages", []))

    # Add fraud events list for detailed output
    features["fraud_events"] = [
        {
            "rule": e.get("rule_name"),
            "severity": e.get("severity"),
            "confidence": e.get("confidence"),
            "explanation": e.get("explanation"),
        }
        for e in entities.get("fraud_events", [])
    ]

    logger.info(
        f"Fraud Engine: score={features.get('fraud_score', 0.0)}, "
        f"risk={features.get('account_risk_level', 'LOW')}, "
        f"flags={features.get('total_fraud_flags', 0)}"
    )

    return features
