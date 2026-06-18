"""
Executor — performs the side effects for a list of engine Actions.

Splits responsibility cleanly: the engine decides *what* to do (pure), the executor does it
and refines the persisted Position to the actual fill. Protective stops are computed off the
real entry fill, not the pre-trade mark, and a close always cancels the resting stop first so
it cannot fire during teardown.
"""

from __future__ import annotations

from dataclasses import replace
from typing import List

from exchange.base import Exchange
from strategy.config import StrategyConfig
from strategy.engine import EngineState
from strategy.exits import short_stop_price
from strategy.models import Action, ClosePosition, OpenShort


class Executor:
    def __init__(self, exchange: Exchange, cfg: StrategyConfig):
        self.exchange = exchange
        self.cfg = cfg

    def execute(self, actions: List[Action], state: EngineState) -> EngineState:
        positions = dict(state.positions)
        for action in actions:
            if isinstance(action, OpenShort):
                fill = self.exchange.open_short(action.symbol, action.volume)
                stop_price = short_stop_price(fill.avg_price, self.cfg.stop_pct)
                stop_id = self.exchange.place_stop(action.symbol, action.volume, stop_price)
                pos = positions.get(action.symbol)
                if pos is not None:
                    positions[action.symbol] = replace(
                        pos, entry_price=fill.avg_price,
                        stop_price=stop_price, stop_order_id=stop_id,
                    )
            elif isinstance(action, ClosePosition):
                self.exchange.cancel_all(action.symbol)
                self.exchange.close(action.symbol)
                positions.pop(action.symbol, None)
        return EngineState(positions=positions, last_pred_rate=dict(state.last_pred_rate))
