"""
P5 — StrategyEngine.step: the pure decision function.

step(state, snapshot, now) -> StepResult(actions, new_state). No I/O. It:
  * reconciles open positions (out-of-band stop fills, normalization/time-cap exits)
  * opens new shorts for fresh qualifying episodes within slot/sizing limits
  * advances per-symbol episode memory (last predicted rate) for every observed symbol
"""

from datetime import datetime, timedelta, timezone

import pytest

from strategy.config import StrategyConfig
from strategy.engine import StrategyEngine, EngineState, MarketSnapshot
from strategy.models import (
    Account,
    ClosePosition,
    ExitReason,
    OpenShort,
    Position,
    SymbolSnapshot,
)

NOW = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    return StrategyEngine(StrategyConfig())


def snap(symbol, pred_rate, **kw):
    base = dict(
        symbol=symbol,
        pred_rate=pred_rate,
        prev_pred_rate=None,          # engine overrides from its own memory
        listing_age_days=120.0,
        liquidity_quote_vol_5m=1000.0,
        mark_price=1.0,
        contract_size=1.0,
        vol_scale=0,
        min_volume=1.0,
    )
    base.update(kw)
    return SymbolSnapshot(**base)


def market(symbols, equity=10_000.0, open_syms=None):
    return MarketSnapshot(
        account=Account(equity=equity),
        symbols=symbols,
        exchange_open_symbols=set() if open_syms is None else set(open_syms),
    )


def open_position(symbol, entry_time=NOW):
    return Position(
        symbol=symbol, side="SHORT", entry_price=1.0, volume=500.0,
        entry_time=entry_time, stop_price=1.175, stop_order_id="stop-1",
    )


# --- entries ----------------------------------------------------------------

def test_fresh_episode_opens_short(engine):
    res = engine.step(EngineState(), market([snap("PUMP_USDT", 0.02)]), NOW)
    opens = [a for a in res.actions if isinstance(a, OpenShort)]
    assert len(opens) == 1
    # 5% of 10k = $500 notional, price 1, contract_size 1 -> 500 contracts
    assert opens[0].symbol == "PUMP_USDT"
    assert opens[0].volume == 500.0
    # state now tracks the position with a +17.5% stop off the mark
    assert "PUMP_USDT" in res.state.positions
    assert res.state.positions["PUMP_USDT"].stop_price == pytest.approx(1.175)


def test_episode_memory_blocks_non_fresh_entry(engine):
    state = EngineState(last_pred_rate={"PUMP_USDT": 0.02})  # already in-episode
    res = engine.step(state, market([snap("PUMP_USDT", 0.02)]), NOW)
    assert [a for a in res.actions if isinstance(a, OpenShort)] == []


def test_memory_advances_for_all_observed_symbols(engine):
    res = engine.step(EngineState(), market([snap("A_USDT", 0.004), snap("B_USDT", 0.02)]), NOW)
    assert res.state.last_pred_rate == {"A_USDT": 0.004, "B_USDT": 0.02}


def test_no_entry_when_slots_full(engine):
    state = EngineState(positions={
        f"H{i}_USDT": open_position(f"H{i}_USDT") for i in range(5)
    })
    res = engine.step(state, market([snap("PUMP_USDT", 0.02)],
                                    open_syms=[f"H{i}_USDT" for i in range(5)]), NOW)
    assert [a for a in res.actions if isinstance(a, OpenShort)] == []


def test_no_entry_when_volume_rounds_to_zero(engine):
    # tiny equity -> $5 notional, $10/contract, int contracts -> 0 -> skip
    res = engine.step(EngineState(), market([snap("PUMP_USDT", 0.02, contract_size=10.0)],
                                            equity=100.0), NOW)
    assert [a for a in res.actions if isinstance(a, OpenShort)] == []
    assert "PUMP_USDT" not in res.state.positions


# --- exits / reconciliation -------------------------------------------------

def test_close_on_normalization(engine):
    state = EngineState(positions={"PUMP_USDT": open_position("PUMP_USDT")},
                        last_pred_rate={"PUMP_USDT": 0.02})
    res = engine.step(state, market([snap("PUMP_USDT", 0.0005)], open_syms=["PUMP_USDT"]), NOW)
    closes = [a for a in res.actions if isinstance(a, ClosePosition)]
    assert len(closes) == 1 and closes[0].reason == ExitReason.NORMALIZED
    assert "PUMP_USDT" not in res.state.positions


def test_close_on_time_cap(engine):
    entry = NOW - timedelta(hours=25)
    state = EngineState(positions={"PUMP_USDT": open_position("PUMP_USDT", entry_time=entry)},
                        last_pred_rate={"PUMP_USDT": 0.02})
    res = engine.step(state, market([snap("PUMP_USDT", 0.02)], open_syms=["PUMP_USDT"]), NOW)
    closes = [a for a in res.actions if isinstance(a, ClosePosition)]
    assert len(closes) == 1 and closes[0].reason == ExitReason.TIME_CAP


def test_reconciles_out_of_band_stop_fill(engine):
    # exchange no longer reports the position (stop filled) -> drop, no close action
    state = EngineState(positions={"PUMP_USDT": open_position("PUMP_USDT")},
                        last_pred_rate={"PUMP_USDT": 0.02})
    res = engine.step(state, market([snap("PUMP_USDT", 0.02)], open_syms=[]), NOW)
    assert [a for a in res.actions if isinstance(a, ClosePosition)] == []
    assert "PUMP_USDT" not in res.state.positions


def test_held_position_not_reentered_even_if_still_fresh_looking(engine):
    # symbol we already hold should never generate a second OpenShort
    state = EngineState(positions={"PUMP_USDT": open_position("PUMP_USDT")},
                        last_pred_rate={"PUMP_USDT": 0.0})  # memory looks "fresh"
    res = engine.step(state, market([snap("PUMP_USDT", 0.02)], open_syms=["PUMP_USDT"]), NOW)
    assert [a for a in res.actions if isinstance(a, OpenShort)] == []
