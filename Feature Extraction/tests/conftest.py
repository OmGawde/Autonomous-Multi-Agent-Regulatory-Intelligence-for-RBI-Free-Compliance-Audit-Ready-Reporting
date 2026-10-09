"""Shared test configuration.

Keeps the unit suite independent of the 5.8 GB FinanceParam weights.

`classifier.py` (Tier 4.5) and `business_profiler.py` reach for
`ParamAdapter.get_instance()`, which loads the real model when the weights are
present on disk. That would make the suite's behaviour depend on whether a
developer has run `tools/fetch_finance_param`, add ~25s and ~6GB of VRAM to a
run, and make model-path tests non-deterministic. Forcing the heuristic engine
keeps these tests unit tests.

Integration against the real weights belongs in a separate, explicitly opted-in
run -- unset this variable to do that.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _force_param_mock_mode():
    """Run the whole suite against the heuristic engine, not the 3B model."""
    previous = os.environ.get("BHARATGEN_MOCK_MODE")
    os.environ["BHARATGEN_MOCK_MODE"] = "1"

    # The adapter is a singleton; drop any instance built before this fixture so
    # it is rebuilt in mock mode.
    try:
        from src.model.param_adapter import ParamAdapter
        ParamAdapter._instance = None
    except ImportError:
        pass

    yield

    if previous is None:
        os.environ.pop("BHARATGEN_MOCK_MODE", None)
    else:
        os.environ["BHARATGEN_MOCK_MODE"] = previous
