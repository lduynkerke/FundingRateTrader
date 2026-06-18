"""
L3 — pure execution metrics used by the characterization harness.

Slippage is signed as a cost (positive = adverse): selling below / buying above the reference.
"""

import pytest

from experiments.metrics import (
    fee_bps,
    fill_ratio,
    slippage_bps,
    summarize_latencies,
)


def test_slippage_sell_below_reference_is_adverse():
    # opened a short (sell) at 0.99 vs fair 1.00 -> sold 1% cheaper -> +100 bps cost
    assert slippage_bps(fill=0.99, reference=1.0, side="sell") == pytest.approx(100.0)


def test_slippage_sell_above_reference_is_favourable():
    assert slippage_bps(fill=1.01, reference=1.0, side="sell") == pytest.approx(-100.0)


def test_slippage_buy_above_reference_is_adverse():
    assert slippage_bps(fill=1.01, reference=1.0, side="buy") == pytest.approx(100.0)


def test_fee_bps():
    assert fee_bps(fee_paid=0.15, notional=100.0) == pytest.approx(15.0)


def test_fill_ratio():
    assert fill_ratio(filled=400.0, requested=500.0) == pytest.approx(0.8)
    assert fill_ratio(filled=0.0, requested=0.0) == 0.0


def test_summarize_latencies():
    s = summarize_latencies([100.0, 200.0, 300.0])
    assert s["min"] == 100.0
    assert s["max"] == 300.0
    assert s["median"] == 200.0
    assert s["n"] == 3


def test_summarize_empty():
    assert summarize_latencies([]) == {"n": 0, "min": None, "median": None, "max": None}
