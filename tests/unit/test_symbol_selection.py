"""
L3 — pure symbol-selection helpers for the experiment harness.

Picks the cheapest *tradable* contracts so a tiny live experiment fits a small account:
1-contract notional = contractSize * price must fit the budget, and the contract must allow
API trading.
"""

import pytest

from experiments.selection import one_contract_notional, rank_affordable, spread_bps


def test_one_contract_notional():
    assert one_contract_notional(contract_size=0.0001, price=60000.0) == pytest.approx(6.0)


def test_spread_bps():
    assert spread_bps(bid=0.99, ask=1.01) == pytest.approx(200.0)
    assert spread_bps(bid=0.0, ask=0.0) == 0.0


def test_rank_affordable_filters_and_sorts():
    contracts = [
        {"symbol": "BIG_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
         "apiAllowed": True, "state": 0, "takerFeeRate": 0.0004},
        {"symbol": "CHEAP_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
         "apiAllowed": True, "state": 0, "takerFeeRate": 0.0004},
        {"symbol": "NOAPI_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
         "apiAllowed": False, "state": 0, "takerFeeRate": 0.0004},
        {"symbol": "USDC_PAIR", "quoteCoin": "USDC", "contractSize": 1.0, "minVol": 1,
         "apiAllowed": True, "state": 0, "takerFeeRate": 0.0004},
    ]
    tickers = {
        "BIG_USDT": {"lastPrice": 50.0, "bid1": 49.9, "ask1": 50.1},
        "CHEAP_USDT": {"lastPrice": 2.0, "bid1": 1.99, "ask1": 2.01},
        "NOAPI_USDT": {"lastPrice": 1.0, "bid1": 1.0, "ask1": 1.0},
        "USDC_PAIR": {"lastPrice": 1.0, "bid1": 1.0, "ask1": 1.0},
    }
    ranked = rank_affordable(contracts, tickers, budget=60.0)
    # only USDT, api-allowed, 1-contract notional <= budget; cheapest first
    assert [r["symbol"] for r in ranked] == ["CHEAP_USDT", "BIG_USDT"]
    assert ranked[0]["notional_1c"] == pytest.approx(2.0)
    assert ranked[0]["spread_bps"] == pytest.approx(100.0)  # (2.01-1.99)/2.0


def test_rank_affordable_excludes_over_budget():
    contracts = [{"symbol": "X_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
                  "apiAllowed": True, "state": 0, "takerFeeRate": 0.0004}]
    tickers = {"X_USDT": {"lastPrice": 100.0, "bid1": 99.0, "ask1": 101.0}}
    assert rank_affordable(contracts, tickers, budget=25.0) == []
