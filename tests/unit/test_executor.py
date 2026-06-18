"""
P7a — Executor: translate engine Actions into Exchange calls and refine state to real fills.

The engine records a position at the mark price with no stop id; after a market open fills,
the executor recomputes the stop off the *actual* fill and records the resting stop order id.
"""

from datetime import datetime, timezone

import pytest

from strategy.config import StrategyConfig
from strategy.engine import EngineState
from strategy.models import ClosePosition, ExitReason, OpenShort, Position, PositionStatus
from exchange.base import OrderFill
from runtime.executor import Executor

NOW = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


class FakeExchange:
    def __init__(self):
        self.calls = []
        self.open_fill_price = 1.10  # differs from mark (1.0) to prove refinement

    def open_short(self, symbol, volume):
        self.calls.append(("open_short", symbol, volume))
        return OrderFill(order_id="ord-1", avg_price=self.open_fill_price, volume=volume)

    def place_stop(self, symbol, volume, stop_price):
        self.calls.append(("place_stop", symbol, volume, stop_price))
        return "stop-1"

    def close(self, symbol):
        self.calls.append(("close", symbol))
        return OrderFill(order_id="ord-2", avg_price=0.9, volume=0.0)

    def cancel_all(self, symbol):
        self.calls.append(("cancel_all", symbol))


@pytest.fixture
def cfg():
    return StrategyConfig()


def test_open_short_places_stop_off_actual_fill(cfg):
    ex = FakeExchange()
    execr = Executor(ex, cfg)
    # engine-created position with mark-based placeholder values
    state = EngineState(positions={
        "PUMP_USDT": Position("PUMP_USDT", "SHORT", entry_price=1.0, volume=500.0,
                              entry_time=NOW, stop_price=1.175, status=PositionStatus.OPEN)
    })
    actions = [OpenShort("PUMP_USDT", volume=500.0, mark_price=1.0)]

    new_state = execr.execute(actions, state)

    assert ("open_short", "PUMP_USDT", 500.0) in ex.calls
    # stop placed at +17.5% off the real 1.10 fill, not the 1.0 mark
    assert ("place_stop", "PUMP_USDT", 500.0, pytest.approx(1.2925)) in ex.calls
    pos = new_state.positions["PUMP_USDT"]
    assert pos.entry_price == pytest.approx(1.10)
    assert pos.stop_price == pytest.approx(1.2925)
    assert pos.stop_order_id == "stop-1"


def test_close_cancels_resting_stop_then_closes(cfg):
    ex = FakeExchange()
    execr = Executor(ex, cfg)
    actions = [ClosePosition("PUMP_USDT", ExitReason.NORMALIZED)]

    execr.execute(actions, EngineState())

    # cancel must precede close so the stop can't fill during teardown
    assert ex.calls == [("cancel_all", "PUMP_USDT"), ("close", "PUMP_USDT")]
