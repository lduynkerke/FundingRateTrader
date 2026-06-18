"""
P9 — run_cycle: one full decision cycle wiring MexcData -> engine -> executor -> exchange.

Uses the real MexcData (with injected HTTP) and a real PaperExchange, so this exercises the
production cycle path end-to-end without network. Timing/sleep lives in run_forever and is
intentionally not unit-tested.
"""

from datetime import datetime, timezone

import pytest

from strategy.config import StrategyConfig
from strategy.engine import EngineState, StrategyEngine
from exchange.mexc_data import MexcData
from exchange.paper import PaperExchange
from runtime.executor import Executor
from runtime.scheduler import run_cycle

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)

DETAIL = {"data": [
    {"symbol": "PUMP_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
     "volScale": 0, "createTime": 1591242684000, "apiAllowed": True, "state": 0},
    {"symbol": "BORING_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
     "volScale": 0, "createTime": 1591242684000, "apiAllowed": True, "state": 0},
]}
FUNDING = {
    "PUMP_USDT": {"fundingRate": 0.02, "collectCycle": 8, "nextSettleTime": 0, "fairPrice": 1.0},
    "BORING_USDT": {"fundingRate": 0.0001, "collectCycle": 8, "nextSettleTime": 0, "fairPrice": 50.0},
}
KLINE = {"data": {"time": [1, 2], "close": [1.0, 1.0], "amount": [1000.0, 1000.0]}}


def fake_http(url, params=None):
    if "/contract/detail" in url:
        return DETAIL
    if "/funding_rate/" in url:
        sym = url.rsplit("/", 1)[-1]
        return {"data": {"symbol": sym, **FUNDING[sym]}}
    if "/kline/" in url:
        return KLINE
    raise AssertionError(url)


def test_run_cycle_opens_fresh_candidate_and_advances_memory():
    data = MexcData(http_get=fake_http)
    cfg = StrategyConfig()
    ex = PaperExchange(equity=10_000.0, fee_round_trip=0.003)
    engine, execr = StrategyEngine(cfg), Executor(ex, cfg)

    state, actions = run_cycle(NOW, data, engine, execr, ex, EngineState(), cfg)

    # only PUMP qualifies (2% fresh); BORING is below threshold
    assert ex.list_open_symbols() == {"PUMP_USDT"}
    assert "PUMP_USDT" in state.positions
    # episode memory advanced for BOTH observed symbols
    assert state.last_pred_rate == {"PUMP_USDT": 0.02, "BORING_USDT": 0.0001}


def test_run_cycle_exits_when_rate_normalizes():
    data = MexcData(http_get=fake_http)
    cfg = StrategyConfig()
    ex = PaperExchange(equity=10_000.0, fee_round_trip=0.003)
    engine, execr = StrategyEngine(cfg), Executor(ex, cfg)

    state, _ = run_cycle(NOW, data, engine, execr, ex, EngineState(), cfg)
    assert ex.list_open_symbols() == {"PUMP_USDT"}

    # next cycle: PUMP funding has normalized -> close
    FUNDING["PUMP_USDT"] = {"fundingRate": 0.0, "collectCycle": 8, "nextSettleTime": 0, "fairPrice": 0.9}
    try:
        state, _ = run_cycle(NOW, data, engine, execr, ex, state, cfg)
        assert ex.list_open_symbols() == set()
        assert state.positions == {}
    finally:
        FUNDING["PUMP_USDT"] = {"fundingRate": 0.02, "collectCycle": 8, "nextSettleTime": 0, "fairPrice": 1.0}
