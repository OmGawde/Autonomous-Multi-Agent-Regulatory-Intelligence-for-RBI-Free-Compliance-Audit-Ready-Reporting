"""
Tests for Feature Aggregator
"""

import json
import sys
from pathlib import Path
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feature_aggregator import aggregate, save_json, save_csv, _flatten_dict


class TestFlattenDict:
    def test_simple_flatten(self):
        d = {"a": 1, "b": 2}
        assert _flatten_dict(d) == {"a": 1, "b": 2}

    def test_nested_flatten(self):
        d = {"income": {"total": 100, "salary": 80}}
        result = _flatten_dict(d)
        assert result["income.total"] == 100
        assert result["income.salary"] == 80

    def test_deeply_nested(self):
        d = {"a": {"b": {"c": 42}}}
        result = _flatten_dict(d)
        assert result["a.b.c"] == 42

    def test_list_to_json(self):
        d = {"trends": [1.0, 2.0, 3.0]}
        result = _flatten_dict(d)
        assert result["trends"] == "[1.0, 2.0, 3.0]"


class TestAggregate:
    def test_aggregate_basic(self):
        engine_outputs = {
            "income": {"total_income": 100000},
            "expense": {"total_expenses": 60000},
            "balance": {"average_daily_balance": 50000},
            "cash_flow": {"net_cash_flow": 40000},
            "savings": {"average_savings": 40000},
            "investment": {"total_investment": 10000},
        }
        result = aggregate(engine_outputs, "ICICI", {"start": "2025-04-01", "end": "2025-09-30"})

        assert result["bank_name"] == "ICICI"
        assert result["statement_period"]["start"] == "2025-04-01"
        assert result["income"]["total_income"] == 100000
        assert result["expense"]["total_expenses"] == 60000

    def test_aggregate_missing_engine(self):
        engine_outputs = {
            "income": {"total_income": 100000},
        }
        result = aggregate(engine_outputs, "SBI")
        assert result["expense"] == {}
        assert result["balance"] == {}


class TestSaveOutputs:
    def test_save_json(self, tmp_path):
        features = {"bank_name": "ICICI", "income": {"total": 100}}
        path = save_json(features, str(tmp_path / "test.json"))
        assert Path(path).exists()

        with open(path) as f:
            loaded = json.load(f)
        assert loaded["bank_name"] == "ICICI"

    def test_save_csv(self, tmp_path):
        features = {"bank_name": "ICICI", "income": {"total": 100}}
        path = save_csv(features, str(tmp_path / "test.csv"))
        assert Path(path).exists()

        import pandas as pd
        df = pd.read_csv(path)
        assert "income.total" in df.columns

    def test_save_all(self, tmp_path):
        from src.feature_aggregator import save_all
        features = {
            "bank_name": "ICICI",
            "statement_period": {"start": "2025-01-01", "end": "2025-12-31"},
            "income": {"total_income": 100000},
            "expense": {"total_expenses": 50000},
            "balance": {"average_daily_balance": 20000},
            "cash_flow": {"net_cash_flow": 50000},
            "savings": {"average_savings": 10000},
            "investment": {"total_investment": 5000},
        }
        paths = save_all(features, str(tmp_path), "ICICI")
        assert Path(paths["json"]).exists()
        assert Path(paths["csv"]).exists()
        assert "categories" in paths
        for cat in ["income", "expense", "balance", "cash_flow", "savings", "investment"]:
            assert f"{cat}_json" in paths["categories"]
            assert Path(paths["categories"][f"{cat}_json"]).exists()
            assert f"{cat}_csv" in paths["categories"]
            assert Path(paths["categories"][f"{cat}_csv"]).exists()
