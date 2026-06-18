"""
P7c — end-to-end paper loop: engine + executor + PaperExchange over multiple settlements.

No network, no mocks of our own code — the real decision core drives the real simulator.
This is the safety net that the whole wiring behaves before any live key is involved.
"""

from datetime import datetime, timedelta, timezone

import pytest

from strategy.config import StrategyConfig
from strategy.engine import EngineState, MarketSnapshot, StrategyEngine
from strategy.models import Account, SymbolSnapshot
from exchange.paper import PaperExchange
from runtime.executor import Executor

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def build_snapshot(ex, preds):
    symbols = [
        SymbolSnapshot(
            symbol=sym, pred_rate=rate, prev_pred_rate=None,
            listing_age_days=120.0, liquidity_quote_vol_5m=1000.0,
            mark_price=ex.get_price(sym), contract_size=1.0, vol_scale=0, min_volume=1.0,
        )
        for sym, rate in preds.items()
    ]
    return MarketSnapshot(Account(ex.get_equity()), symbols, ex.list_open_symbols())


def run_settlement(engine, execr, ex, state, preds, now):
    res = engine.step(state, build_snapshot(ex, preds), now)
    return execr.execute(res.actions, res.state)


def test_episode_win_via_normalization():
    ex = PaperExchange(equity=10_000.0, prices={"PUMP_USDT": 1.0}, fee_round_trip=0.003)
    engine, execr, state = StrategyEngine(StrategyConfig()), Executor(ex, StrategyConfig()), EngineState()

    # t0: fresh +2% episode -> open short
    state = run_settlement(engine, execr, ex, state, {"PUMP_USDT": 0.02}, T0)
    assert ex.list_open_symbols() == {"PUMP_USDT"}
    assert "PUMP_USDT" in state.positions

    # t1 (+4h): price drifting down, still elevated -> hold
    ex.set_price("PUMP_USDT", 0.95)
    state = run_settlement(engine, execr, ex, state, {"PUMP_USDT": 0.02}, T0 + timedelta(hours=4))
    assert ex.list_open_symbols() == {"PUMP_USDT"}

    # t2 (+8h): funding normalized -> close at 0.90 for a profit
    ex.set_price("PUMP_USDT", 0.90)
    state = run_settlement(engine, execr, ex, state, {"PUMP_USDT": 0.0}, T0 + timedelta(hours=8))
    assert ex.list_open_symbols() == set()
    assert state.positions == {}
    assert ex.get_equity() > 10_000.0  # net winner after costs


def test_episode_stopped_out_then_reconciled():
    ex = PaperExchange(equity=10_000.0, prices={"PUMP_USDT": 1.0}, fee_round_trip=0.0)
    engine, execr, state = StrategyEngine(StrategyConfig()), Executor(ex, StrategyConfig()), EngineState()

    state = run_settlement(engine, execr, ex, state, {"PUMP_USDT": 0.02}, T0)
    assert ex.list_open_symbols() == {"PUMP_USDT"}
    # resting stop sits at +17.5% off the 1.0 fill
    assert state.positions["PUMP_USDT"].stop_price == pytest.approx(1.175)

    # squeeze gaps through the stop between settlements -> exchange auto-closes
    ex.set_price("PUMP_USDT", 1.20)
    assert ex.list_open_symbols() == set()

    # next settlement: engine reconciles the vanished position, no double close, no re-entry
    state = run_settlement(engine, execr, ex, state, {"PUMP_USDT": 0.02}, T0 + timedelta(hours=4))
    assert state.positions == {}
    assert ex.get_equity() == pytest.approx(10_000.0 + (1.0 - 1.175) * 500.0)
