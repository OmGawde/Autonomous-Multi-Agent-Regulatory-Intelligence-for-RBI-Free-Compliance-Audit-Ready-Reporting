"""Unit tests for BharatGen Param-Finance Adapter (param_adapter.py).

Verifies:
1. Device resolution & Mock fallback instantiation.
2. SHA-256 narration cache keys.
3. Pillar 1: Batch long-tail exception classification (e.g. Kapil Textiles, Shree Ganesh Kirana).
4. Pillar 2: SME business profiling and commingling risk flags.
5. Pillar 3: CAM executive narrative memorandum synthesis.
"""

from __future__ import annotations

import pytest
from src.model.param_adapter import MockParamFinanceModel, ParamAdapter, ParamModelLoader


@pytest.fixture
def adapter():
    """Instantiate ParamAdapter with sovereign mock loader for deterministic unit testing."""
    loader = ParamModelLoader(mock_mode=True)
    return ParamAdapter(loader=loader)


def test_device_auto_routing():
    """Device router resolves valid strings and falls back gracefully to CPU."""
    assert ParamModelLoader._resolve_device("cpu") == "cpu"
    assert ParamModelLoader._resolve_device("auto") in ["cuda", "mps", "cpu"]


def test_sha256_narration_cache_key():
    """Cache keys are normalized and collision-resistant."""
    k1 = ParamAdapter._hash_key("UPI/123/Swiggy", "DEBIT")
    k2 = ParamAdapter._hash_key("   upi/123/swiggy  ", "debit")
    k3 = ParamAdapter._hash_key("UPI/123/Swiggy", "CREDIT")

    assert k1 == k2
    assert k1 != k3


def test_pillar1_batch_exception_handling(adapter):
    """Pillar 1 resolves ambiguous Indian narrations in a single batched call."""
    unresolved_batch = [
        {
            "index": 1,
            "narration": "NEFT-AXIP001-KAPIL TEXTILES-CHQ 4410",
            "debit": 0.0,
            "credit": 45000.0,
        },
        {
            "index": 2,
            "narration": "UPI/SHREE GANESH KIRANA/DHANDHA PAYMENT",
            "debit": 12500.0,
            "credit": 0.0,
        },
        {
            "index": 3,
            "narration": "ACH D- BAJAJ FINSERV-492819-LOAN EMI",
            "debit": 14500.0,
            "credit": 0.0,
        },
    ]

    results = adapter.classify_unresolved_batch(unresolved_batch)
    assert len(results) == 3

    # Row 1: Kapil Textiles
    r1 = next(r for r in results if r["index"] == 1)
    assert r1["category"] == "Income"
    assert "Textiles" in r1["counterparty"] or "Textiles" in r1["subcategory"]
    assert r1["classification_method"] == "param_finance"

    # Row 2: Shree Ganesh Kirana
    r2 = next(r for r in results if r["index"] == 2)
    assert r2["category"] == "Expense"
    assert "Kirana" in r2["counterparty"] or "Inventory" in r2["subcategory"]
    assert r2["classification_method"] == "param_finance"

    # Row 3: Bajaj Finserv EMI
    r3 = next(r for r in results if r["index"] == 3)
    assert r3["category"] == "Loan EMI"
    assert "Bajaj" in r3["counterparty"]
    assert r3["banking_rail"] == "NACH"


def test_pillar2_sme_business_profiling(adapter):
    """Pillar 2 extracts trade sector, commingling risk, and informal loan indicators."""
    textile_counterparties = [
        {"name": "Kapil Textiles Surat", "volume": 450000.0},
        {"name": "Vardhman Fabrics Ltd", "volume": 320000.0},
        {"name": "Apex Roadways Logistics", "volume": 90000.0},
        {"name": "Shree Ganesh Committee BC", "volume": 50000.0},
    ]

    profile = adapter.profile_sme_counterparties(textile_counterparties)
    assert "Textile" in profile["inferred_business_sector"]
    assert profile["commingling_risk"] in ["LOW", "MEDIUM", "HIGH"]
    assert profile["informal_borrowing_flag"] is True
    assert any("BC" in s or "Committee" in s for s in profile["informal_borrowing_signals"])


def test_pillar3_cam_executive_narrative(adapter):
    """Pillar 3 synthesizes an institutional 3-paragraph Credit Appraisal Memo."""
    features = {
        "borrower_name": "Sharma Auto Components",
        "true_turnover": 8450000.0,
        "circular_volume": 1200000.0,
        "foir": 0.385,
        "inward_bounces": 1,
        "volatility_band": "Low",
        "adb": 185000.0,
    }

    memo = adapter.generate_cam_executive_narrative(features)
    assert isinstance(memo, str)
    paragraphs = [p.strip() for p in memo.split("\n\n") if p.strip()]
    assert len(paragraphs) == 3

    # Paragraph 1 checks turnover and circular deduction
    assert "Sharma Auto Components" in paragraphs[0]
    assert "84.50" in paragraphs[0]
    assert "circular" in paragraphs[0].lower()

    # Paragraph 2 checks FOIR and ADB
    assert "38.5%" in paragraphs[1]
    assert "1.85" in paragraphs[1]

    # Paragraph 3 checks bounce caution covenant
    assert "single inward cheque" in paragraphs[2].lower() or "covenant" in paragraphs[2].lower()
