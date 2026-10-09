import math
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

try:
    from common_utils import ConfigManager, DataSufficiencyEvaluator, FeatureFormatter
except ImportError:
    from .common_utils import ConfigManager, DataSufficiencyEvaluator, FeatureFormatter

class BehaviourEngine:
    """
    Production-Grade Behavioural Profiling & Personality Engine for Bank Statement Analyzer (BSA).
    Performs temporal enrichment, discretionary vs essential expenditure profiling, salary exhaustion tracking,
    multi-window rolling statistics, and assigns deterministic financial state labels.
    Exposes process(df) as standard feature extraction interface.
    """

    def __init__(self, config_path=None):
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get("behaviour_engine_config", {})
        self.taxonomies = self.config_manager.get("taxonomies", {})
        self.night_start = self.config.get("night_hours_start", 21)
        self.night_end = self.config.get("night_hours_end", 5)

    def process(self, df: pd.DataFrame) -> dict:
        """Standard production-grade Feature Extraction interface."""
        if df.empty:
            return self._empty_process_response()

        sufficiency = DataSufficiencyEvaluator.evaluate(df)
        
        # 1. Temporal enrichment & tagging
        df_enriched = self._enrich_temporal_and_category(df)

        # 2. Salary cycle detection & primary income velocity
        salary_info = self._detect_salary_cycles(df_enriched)

        # 3. Multi-window features computation (30D, 90D, 180D, 365D)
        windowed_metrics = self._compute_multi_window_metrics(df_enriched, salary_info)

        # 4. Aggregate macro behavioural metrics
        overall_features = self._compute_overall_features(df_enriched, salary_info, windowed_metrics)

        # 5. Behaviour state classification & stability index
        state_label, bsi, confidence_score = self._classify_behaviour_state(overall_features, sufficiency)

        # 6. Annotate transaction dataframe
        df_annotated = self._annotate_transaction_level_behaviour(df_enriched, salary_info)

        # 7. Reconstruct entity objects
        entities = self._reconstruct_entities(df_annotated, salary_info, state_label, bsi, confidence_score, windowed_metrics)

        # 8. Build formatted features dictionary
        features = self._build_feature_dictionary(overall_features, salary_info, windowed_metrics, state_label, bsi, confidence_score, sufficiency)

        return {
            "engine": "BehaviourEngine",
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
        entities = res["entities"]
        b_state = entities["behaviour_states"]

        df_enriched = self._enrich_temporal_and_category(df)
        salary_info = self._detect_salary_cycles(df_enriched)
        windowed_metrics = self._compute_multi_window_metrics(df_enriched, salary_info)
        overall_features = self._compute_overall_features(df_enriched, salary_info, windowed_metrics)

        return {
            "engine": "BehaviourEngine",
            "version": "1.0.0",
            "data_sufficiency": res["metadata"]["data_sufficiency"],
            "behaviour_profile": {
                "primary_state_label": b_state["primary_state_label"],
                "behaviour_stability_index": b_state["behaviour_stability_index"],
                "behaviour_confidence_score": b_state["behaviour_confidence_score"],
                "overall_features": overall_features
            },
            "salary_cycle_info": salary_info,
            "windowed_metrics": windowed_metrics
        }

    def _enrich_temporal_and_category(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["date_dt"] = pd.to_datetime(df["date"])
        df["day_of_week"] = df["date_dt"].dt.day_name()
        df["is_weekend"] = df["date_dt"].dt.dayofweek.isin([5, 6])
        df["hour"] = df["date_dt"].dt.hour

        # Bank statements carry a date but no time, so every row parses to
        # 00:00 and the night-window test (h >= 23 or h <= 5) matched every
        # transaction -- night_spend_ratio was a constant 1.0 on every account.
        # Only compute it when the source actually has a time component.
        self.has_timestamps = bool(
            (df["date_dt"].dt.hour != 0).any() or (df["date_dt"].dt.minute != 0).any()
        )
        if self.has_timestamps:
            df["is_night_spend"] = df["hour"].apply(lambda h: h >= self.night_start or h <= self.night_end)
        else:
            df["is_night_spend"] = False

        df["spending_category"] = "UNCLASSIFIED"
        df["sub_category"] = "OTHER"

        needs_dict = self.taxonomies.get("NEEDS", {})
        wants_dict = self.taxonomies.get("WANTS", {})
        invest_dict = self.taxonomies.get("INVESTMENT", {})

        for idx, row in df.iterrows():
            desc = str(row["description"]).upper()

            cat = "UNCLASSIFIED"
            sub_cat = "OTHER"

            for sub, kws in needs_dict.items():
                if any(k in desc for k in kws):
                    cat = "NEEDS"
                    sub_cat = sub
                    break

            if cat == "UNCLASSIFIED":
                for sub, kws in wants_dict.items():
                    if any(k in desc for k in kws):
                        cat = "WANTS"
                        sub_cat = sub
                        break

            if cat == "UNCLASSIFIED":
                for sub, kws in invest_dict.items():
                    if any(k in desc for k in kws):
                        cat = "INVESTMENT"
                        sub_cat = sub
                        break

            if row.get("rail_type") == "ATM_CASH":
                cat = "NEEDS"
                sub_cat = "CASH_WITHDRAWAL"

            df.at[idx, "spending_category"] = cat
            df.at[idx, "sub_category"] = sub_cat

        return df

    def _detect_salary_cycles(self, df: pd.DataFrame) -> dict:
        """Detects primary recurring income credit (salary) and dates."""
        credits = df[df["credit"] > 5000.0].copy()
        if credits.empty:
            return {"primary_monthly_income": 0.0, "salary_dates": [], "salary_detected": False}

        salary_kws = self.config.get("salary_keywords", [])
        salary_rows = credits[credits["description"].str.upper().apply(lambda d: any(k in d for k in salary_kws))]

        if not salary_rows.empty:
            amounts = salary_rows["credit"].tolist()
            dates = salary_rows["date"].astype(str).tolist()
            return {
                "primary_monthly_income": round(float(np.median(amounts)), 2),
                "salary_dates": dates,
                "salary_detected": True,
                "average_credit_amount": round(float(np.mean(amounts)), 2)
            }

        if "parsed_payee" in credits.columns:
            group_payee = credits.groupby("parsed_payee")["credit"].agg(["count", "median", "mean"])
            group_payee = group_payee[group_payee["count"] >= 2].sort_values(by="median", ascending=False)

            if not group_payee.empty:
                primary_payee = group_payee.index[0]
                sal_df = credits[credits["parsed_payee"] == primary_payee]
                return {
                    "primary_monthly_income": round(float(group_payee.iloc[0]["median"]), 2),
                    "salary_dates": sal_df["date"].astype(str).tolist(),
                    "salary_detected": True,
                    "primary_employer_or_source": primary_payee
                }

        return {
            "primary_monthly_income": round(float(credits["credit"].mean()), 2),
            "salary_dates": [],
            "salary_detected": False
        }

    def _compute_multi_window_metrics(self, df: pd.DataFrame, salary_info: dict) -> dict:
        max_date = df["date_dt"].max()
        window_results = {}

        for days in self.config.get("windows_days", [30, 90, 180, 365]):
            start_window = max_date - timedelta(days=days)
            w_df = df[df["date_dt"] >= start_window]

            if w_df.empty:
                continue

            total_debits = float(w_df["debit"].sum())
            total_credits = float(w_df["credit"].sum())
            wants_debits = float(w_df[w_df["spending_category"] == "WANTS"]["debit"].sum())
            needs_debits = float(w_df[w_df["spending_category"] == "NEEDS"]["debit"].sum())
            invest_debits = float(w_df[w_df["spending_category"] == "INVESTMENT"]["debit"].sum())
            weekend_debits = float(w_df[w_df["is_weekend"] == True]["debit"].sum())
            night_debits = float(w_df[w_df["is_night_spend"] == True]["debit"].sum())
            cash_debits = float(w_df[w_df["rail_type"] == "ATM_CASH"]["debit"].sum()) if "rail_type" in w_df.columns else 0.0

            window_results[f"{days}D"] = {
                "total_debits": round(total_debits, 2),
                "total_credits": round(total_credits, 2),
                "discretionary_wants_spend": round(wants_debits, 2),
                "essential_needs_spend": round(needs_debits, 2),
                "investment_spend": round(invest_debits, 2),
                "weekend_spend_ratio": round(weekend_debits / total_debits, 4) if total_debits > 0 else 0.0,
                "night_spend_ratio": (round(night_debits / total_debits, 4)
                                      if (total_debits > 0 and getattr(self, "has_timestamps", False)) else None),
                "cash_preference_ratio": round(cash_debits / total_debits, 4) if total_debits > 0 else 0.0,
                "discretionary_to_essential_ratio": round(wants_debits / needs_debits, 4) if needs_debits > 0 else 0.0,
                "net_savings": round(total_credits - total_debits, 2)
            }

        return window_results

    def _compute_overall_features(self, df: pd.DataFrame, salary_info: dict, windows: dict) -> dict:
        total_debits = float(df["debit"].sum())
        total_credits = float(df["credit"].sum())
        wants_spend = float(df[df["spending_category"] == "WANTS"]["debit"].sum())
        needs_spend = float(df[df["spending_category"] == "NEEDS"]["debit"].sum())

        weekend_spend = float(df[df["is_weekend"] == True]["debit"].sum())
        night_spend = float(df[df["is_night_spend"] == True]["debit"].sum())
        weekend_ratio = round(weekend_spend / total_debits, 4) if total_debits > 0 else 0.0
        night_ratio = (round(night_spend / total_debits, 4)
                       if (total_debits > 0 and getattr(self, "has_timestamps", False)) else None)

        cash_spend = float(df[df["rail_type"] == "ATM_CASH"]["debit"].sum()) if "rail_type" in df.columns else 0.0
        cash_ratio = round(cash_spend / total_debits, 4) if total_debits > 0 else 0.0

        unique_merchants = df["parsed_payee"].nunique() if "parsed_payee" in df.columns else 0
        merchant_diversity = int(unique_merchants)

        daily_debits = df.groupby("date")["debit"].sum()
        mean_daily = daily_debits.mean()
        std_daily = daily_debits.std()
        volatility = round(float(std_daily / mean_daily), 4) if mean_daily > 0 else 0.0

        income = salary_info.get("primary_monthly_income", 0.0)
        salary_exhaustion_days = 25
        if income > 0 and not df.empty:
            cum_debits = df["debit"].cumsum()
            target = income * 0.80
            match = df[cum_debits >= target]
            if not match.empty:
                start_d = df["date_dt"].min()
                exhaust_d = match["date_dt"].iloc[0]
                salary_exhaustion_days = max(1, (exhaust_d - start_d).days)

        amb_thresh = self.config.get("amb_threshold", 3000.0)
        low_bal_days = (df["balance"] < amb_thresh).sum() if "balance" in df.columns else 0

        return {
            "weekend_spend_ratio": weekend_ratio,
            "night_spend_ratio": night_ratio,
            "cash_preference_ratio": cash_ratio,
            "discretionary_vs_essential_ratio": round(wants_spend / needs_spend, 4) if needs_spend > 0 else 0.0,
            "spending_volatility": volatility,
            "salary_exhaustion_speed_days": salary_exhaustion_days,
            "merchant_diversity_score": merchant_diversity,
            "low_balance_days_count": int(low_bal_days),
            "discretionary_wants_total": round(wants_spend, 2),
            "essential_needs_total": round(needs_spend, 2),
            "total_credits_sum": round(total_credits, 2),
            "total_debits_sum": round(total_debits, 2)
        }

    def _classify_behaviour_state(self, features: dict, sufficiency: dict) -> tuple:
        cash_ratio = features["cash_preference_ratio"]
        disc_ratio = features["discretionary_vs_essential_ratio"]
        volatility = features["spending_volatility"]
        low_bal = features["low_balance_days_count"]
        exhaust_days = features["salary_exhaustion_speed_days"]

        # Whether the account is actually accumulating. The state was previously
        # decided on spending mix alone, so an account that burned through
        # Rs 2,79,478 over a year was still labelled "High Saver" purely because
        # its discretionary ratio was low and it never dipped to a low balance.
        total_credits = float(features.get("total_credits_sum", 0.0) or 0.0)
        total_debits = float(features.get("total_debits_sum", 0.0) or 0.0)
        savings_rate = ((total_credits - total_debits) / total_credits) if total_credits > 0 else 0.0

        if low_bal > 15 or exhaust_days < 7:
            state = "Financial Stress"
        elif cash_ratio > 0.35:
            state = "Cash Dependent"
        elif disc_ratio > 0.60 or features["weekend_spend_ratio"] > 0.40:
            state = "Impulsive"
        elif savings_rate < -0.05:
            state = "Depleting Balance"
        elif disc_ratio > 0.40:
            state = "Lifestyle Inflation"
        elif disc_ratio < 0.20 and low_bal == 0 and savings_rate > 0:
            state = "High Saver"
        elif volatility < 1.2:
            state = "Disciplined"
        else:
            state = "Stable"

        base_bsi = 100.0
        base_bsi -= min(30.0, volatility * 15.0)
        base_bsi -= min(25.0, low_bal * 2.0)
        base_bsi -= min(20.0, disc_ratio * 25.0)
        bsi = round(max(10.0, min(100.0, base_bsi)), 2)

        conf_multiplier = sufficiency.get("confidence_multiplier", 1.0)
        conf_score = round(min(1.0, max(0.4, (bsi / 100.0) * conf_multiplier)), 2)

        return state, bsi, conf_score

    def _annotate_transaction_level_behaviour(self, df_enriched: pd.DataFrame, salary_info: dict) -> pd.DataFrame:
        df = df_enriched.copy()
        df["weekend_flag"] = df["is_weekend"]
        df["night_flag"] = df["is_night_spend"]
        df["behaviour_category"] = df["spending_category"]
        df["behaviour_labels"] = df["sub_category"]
        df["salary_cycle_position"] = "Mid-Month"

        salary_dates = salary_info.get("salary_dates", [])
        if salary_dates:
            sal_dts = [pd.to_datetime(d) for d in salary_dates if pd.notnull(d)]
            positions = []
            for idx, row in df.iterrows():
                row_dt = row["date_dt"]
                prev_sal = [s for s in sal_dts if s <= row_dt]
                if prev_sal:
                    last_sal = max(prev_sal)
                    diff_days = (row_dt - last_sal).days
                    if diff_days <= 7:
                        pos = "Post-Salary-W1"
                    elif diff_days <= 15:
                        pos = "Post-Salary-W2"
                    elif diff_days <= 22:
                        pos = "Mid-Month"
                    else:
                        pos = "End-of-Month"
                else:
                    pos = "Pre-Salary"
                positions.append(pos)
            df["salary_cycle_position"] = positions

        return df

    def _reconstruct_entities(self, df_annotated: pd.DataFrame, salary_info: dict, state_label: str, bsi: float, conf_score: float, windowed_metrics: dict) -> dict:
        df = df_annotated.copy()
        df["year_month"] = df["date_dt"].dt.to_period("M").astype(str)
        monthly_profiles = []

        for ym, group in df.groupby("year_month"):
            tot_credit = float(group["credit"].sum())
            tot_debit = float(group["debit"].sum())
            wants = float(group[group["behaviour_category"] == "WANTS"]["debit"].sum())
            needs = float(group[group["behaviour_category"] == "NEEDS"]["debit"].sum())
            invest = float(group[group["behaviour_category"] == "INVESTMENT"]["debit"].sum())
            cash = float(group[group["behaviour_labels"] == "CASH_WITHDRAWAL"]["debit"].sum())
            savings = tot_credit - tot_debit

            monthly_profiles.append({
                "year_month": ym,
                "total_credits": round(tot_credit, 2),
                "total_debits": round(tot_debit, 2),
                "needs_spend": round(needs, 2),
                "wants_spend": round(wants, 2),
                "investment_spend": round(invest, 2),
                "cash_withdrawal": round(cash, 2),
                "net_savings": round(savings, 2),
                "savings_rate": round(savings / tot_credit, 4) if tot_credit > 0 else 0.0
            })

        spending_trends = {
            "wants_trend": "STABLE",
            "needs_trend": "STABLE",
            "monthly_wants_growth_rate": 0.0,
            "monthly_needs_growth_rate": 0.0
        }
        if len(monthly_profiles) >= 2:
            prev_wants = monthly_profiles[-2]["wants_spend"]
            curr_wants = monthly_profiles[-1]["wants_spend"]
            w_growth = (curr_wants - prev_wants) / prev_wants if prev_wants > 0 else 0.0
            spending_trends["monthly_wants_growth_rate"] = round(w_growth, 4)
            spending_trends["wants_trend"] = "INCREASING" if w_growth > 0.15 else ("DECREASING" if w_growth < -0.15 else "STABLE")

        m30 = windowed_metrics.get("30D", {})
        m365 = windowed_metrics.get("365D", m30)
        behaviour_drift = {
            "wants_ratio_drift": round(m30.get("discretionary_wants_spend", 0.0) - m365.get("discretionary_wants_spend", 0.0), 2),
            "weekend_spend_drift": round(m30.get("weekend_spend_ratio", 0.0) - m365.get("weekend_spend_ratio", 0.0), 4),
            "night_spend_drift": (
                round(m30["night_spend_ratio"] - m365["night_spend_ratio"], 4)
                if (m30.get("night_spend_ratio") is not None
                    and m365.get("night_spend_ratio") is not None)
                else None
            ),
            "savings_rate_drift": round(m30.get("net_savings", 0.0) - m365.get("net_savings", 0.0), 2)
        }

        return {
            "monthly_behaviour_profiles": monthly_profiles,
            "behaviour_states": {
                "primary_state_label": state_label,
                "behaviour_stability_index": bsi,
                "behaviour_confidence_score": conf_score
            },
            "salary_cycle_info": salary_info,
            "spending_trends": spending_trends,
            "behaviour_drift": behaviour_drift
        }

    def _build_feature_dictionary(self, overall: dict, salary_info: dict, windows: dict, state_label: str, bsi: float, conf_score: float, sufficiency: dict) -> dict:
        conf = sufficiency.get("confidence_multiplier", 1.0)
        w30 = windows.get("30D", {})
        w90 = windows.get("90D", {})
        w180 = windows.get("180D", {})
        w365 = windows.get("365D", {})

        tot_credits = overall.get("total_credits_sum", 0.0)
        tot_debits = overall.get("total_debits_sum", 0.0)
        savings_rate = (tot_credits - tot_debits) / tot_credits if tot_credits > 0 else 0.0
        wants = overall.get("discretionary_wants_total", 0.0)
        weekend_r = overall.get("weekend_spend_ratio", 0.0)
        impulse_score = round(min(100.0, (wants / tot_debits if tot_debits > 0 else 0.0) * weekend_r * 250.0), 2)

        w180_wants = w180.get("discretionary_wants_spend", 0.0)
        w30_wants = w30.get("discretionary_wants_spend", 0.0)
        lifestyle_inflation = round((w30_wants * 6.0) / w180_wants, 4) if w180_wants > 0 else 1.0

        return {
            "weekend_spend_ratio": FeatureFormatter.format_feature(overall.get("weekend_spend_ratio", 0.0), confidence=conf),
            "night_spend_ratio": FeatureFormatter.format_feature(overall.get("night_spend_ratio", 0.0), confidence=conf),
            "cash_preference": FeatureFormatter.format_feature(overall.get("cash_preference_ratio", 0.0), confidence=conf),
            "impulse_score": FeatureFormatter.format_feature(impulse_score, confidence=conf),
            "merchant_diversity": FeatureFormatter.format_feature(overall.get("merchant_diversity_score", 0), confidence=conf),
            "salary_exhaustion_days": FeatureFormatter.format_feature(overall.get("salary_exhaustion_speed_days", 0), confidence=conf, window="30D"),
            "behaviour_stability": FeatureFormatter.format_feature(bsi, confidence=conf_score),
            "behaviour_stability_index": FeatureFormatter.format_feature(bsi, confidence=conf_score),
            "savings_rate": FeatureFormatter.format_feature(round(savings_rate, 4), confidence=conf),
            "lifestyle_inflation": FeatureFormatter.format_feature(lifestyle_inflation, confidence=conf, window="180D"),
            "discretionary_vs_essential_ratio": FeatureFormatter.format_feature(overall.get("discretionary_vs_essential_ratio", 0.0), confidence=conf),
            "spending_volatility": FeatureFormatter.format_feature(overall.get("spending_volatility", 0.0), confidence=conf),
            "low_balance_days_count": FeatureFormatter.format_feature(overall.get("low_balance_days_count", 0), confidence=conf),
            "discretionary_wants_total": FeatureFormatter.format_feature(overall.get("discretionary_wants_total", 0.0), confidence=conf),
            "essential_needs_total": FeatureFormatter.format_feature(overall.get("essential_needs_total", 0.0), confidence=conf),
            "primary_monthly_income": FeatureFormatter.format_feature(salary_info.get("primary_monthly_income", 0.0), confidence=conf, window="30D"),
            "salary_detected_flag": FeatureFormatter.format_feature(salary_info.get("salary_detected", False), confidence=conf),

            "weekend_spend_ratio_30d": FeatureFormatter.format_feature(w30.get("weekend_spend_ratio", 0.0), confidence=conf, window="30D"),
            "night_spend_ratio_30d": FeatureFormatter.format_feature(w30.get("night_spend_ratio", 0.0), confidence=conf, window="30D"),
            "discretionary_wants_spend_30d": FeatureFormatter.format_feature(w30.get("discretionary_wants_spend", 0.0), confidence=conf, window="30D"),
            "essential_needs_spend_30d": FeatureFormatter.format_feature(w30.get("essential_needs_spend", 0.0), confidence=conf, window="30D"),
            "cash_preference_ratio_30d": FeatureFormatter.format_feature(w30.get("cash_preference_ratio", 0.0), confidence=conf, window="30D"),
            "net_savings_30d": FeatureFormatter.format_feature(w30.get("net_savings", 0.0), confidence=conf, window="30D"),

            "weekend_spend_ratio_90d": FeatureFormatter.format_feature(w90.get("weekend_spend_ratio", 0.0), confidence=conf, window="90D"),
            "night_spend_ratio_90d": FeatureFormatter.format_feature(w90.get("night_spend_ratio", 0.0), confidence=conf, window="90D"),
            "discretionary_wants_spend_90d": FeatureFormatter.format_feature(w90.get("discretionary_wants_spend", 0.0), confidence=conf, window="90D"),
            "essential_needs_spend_90d": FeatureFormatter.format_feature(w90.get("essential_needs_spend", 0.0), confidence=conf, window="90D"),
            "cash_preference_ratio_90d": FeatureFormatter.format_feature(w90.get("cash_preference_ratio", 0.0), confidence=conf, window="90D"),
            "net_savings_90d": FeatureFormatter.format_feature(w90.get("net_savings", 0.0), confidence=conf, window="90D"),

            "weekend_spend_ratio_180d": FeatureFormatter.format_feature(w180.get("weekend_spend_ratio", 0.0), confidence=conf, window="180D"),
            "night_spend_ratio_180d": FeatureFormatter.format_feature(w180.get("night_spend_ratio", 0.0), confidence=conf, window="180D"),
            "discretionary_wants_spend_180d": FeatureFormatter.format_feature(w180.get("discretionary_wants_spend", 0.0), confidence=conf, window="180D"),
            "essential_needs_spend_180d": FeatureFormatter.format_feature(w180.get("essential_needs_spend", 0.0), confidence=conf, window="180D"),
            "cash_preference_ratio_180d": FeatureFormatter.format_feature(w180.get("cash_preference_ratio", 0.0), confidence=conf, window="180D"),
            "net_savings_180d": FeatureFormatter.format_feature(w180.get("net_savings", 0.0), confidence=conf, window="180D")
        }

    def _empty_process_response(self) -> dict:
        return {
            "engine": "BehaviourEngine",
            "version": "1.0.0",
            "transaction_annotations": pd.DataFrame(),
            "entities": {
                "monthly_behaviour_profiles": [],
                "behaviour_states": {"primary_state_label": "Unknown", "behaviour_stability_index": 0.0, "behaviour_confidence_score": 0.0},
                "salary_cycle_info": {},
                "spending_trends": {},
                "behaviour_drift": {}
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
            "engine": "BehaviourEngine",
            "version": "1.0.0",
            "behaviour_profile": {
                "primary_state_label": "Unknown",
                "behaviour_stability_index": 0.0,
                "behaviour_confidence_score": 0.0,
                "overall_features": {}
            },
            "salary_cycle_info": {},
            "windowed_metrics": {}
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
    Analyze spending behaviour from classified transactions.

    Matches the interface of income.process(), expense.process(), etc.
    Returns a flat feature dictionary.
    """
    logger.info("Behaviour Engine: processing")

    if transactions.empty:
        logger.warning("Behaviour Engine: no transactions found")
        return {
            "behaviour_state": "Unknown",
            "behaviour_stability_index": 0.0,
            "behaviour_confidence_score": 0.0,
            "salary_exhaustion_speed": 0.0,
            "impulsive_spending_ratio": 0.0,
            "late_night_activity_ratio": 0.0,
            "weekend_spending_ratio": 0.0,
            "gambling_flag": False,
            "cash_advance_ratio": 0.0,
        }

    engine = BehaviourEngine()
    raw = engine.process(transactions)

    # Flatten the FeatureFormatter-wrapped features dict
    raw_features = raw.get("features", {})
    features = {}
    for key, val in raw_features.items():
        features[key] = _unwrap(val)

    # Add top-level behaviour profile fields.
    # process() -> _reconstruct_entities() writes "behaviour_states"; the legacy
    # analyze() wrapper is the only thing that ever produced "behaviour_profile".
    # Reading the wrong key pinned behaviour_state to "Unknown" on every run and
    # clobbered the behaviour_stability_index that _build_feature_dictionary had
    # already computed correctly.
    entities = raw.get("entities", {})
    profile = entities.get("behaviour_states", {})
    features["behaviour_state"] = profile.get("primary_state_label", "Unknown")
    if "behaviour_stability_index" in profile:
        features["behaviour_stability_index"] = profile["behaviour_stability_index"]
    if "behaviour_confidence_score" in profile:
        features["behaviour_confidence_score"] = profile["behaviour_confidence_score"]

    # Add salary cycle info. _reconstruct_entities writes "salary_cycle_info",
    # holding the dict returned by _detect_salary_cycles.
    salary_cycle = entities.get("salary_cycle_info", {})
    features["salary_detected"] = bool(salary_cycle.get("salary_detected", False))
    features["salary_day_range"] = salary_cycle.get("salary_dates", [])
    features["salary_exhaustion_speed"] = salary_cycle.get(
        "salary_exhaustion_speed", features.get("salary_exhaustion_days", 0.0)
    )

    logger.info(
        f"Behaviour Engine: state={features.get('behaviour_state')}, "
        f"stability={features.get('behaviour_stability_index', 0.0)}, "
        f"exhaustion={features.get('salary_exhaustion_speed', 0.0)}"
    )

    return features
