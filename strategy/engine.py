"""
StrategyEngine — the pure decision core for S1-Episode.

`step` is a referentially-transparent function of (persisted state, market snapshot, clock).
It returns the actions to perform and the next state; it performs no I/O and never assumes
real fill prices (the executor refines entry/stop to actual fills). Keeping it pure makes the
entire trading logic exhaustively unit-testable with no network and no money at risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Dict, List, Optional, Set

from strategy.config import StrategyConfig
from strategy.exits import short_stop_price, should_exit
from strategy.models import (
    Account,
    Action,
    ClosePosition,
    OpenShort,
    Position,
    PositionStatus,
    SymbolSnapshot,
)
from strategy.portfolio import select_entries
from strategy.signals import evaluate_entries
from strategy.sizing import notional_to_volume, target_notional


@dataclass
class EngineState:
    """Everything that must survive a process restart."""
    positions: Dict[str, Position] = field(default_factory=dict)
    last_pred_rate: Dict[str, float] = field(default_factory=dict)  # episode memory


@dataclass(frozen=True)
class MarketSnapshot:
    """Market view at one settlement decision point."""
    account: Account
    symbols: List[SymbolSnapshot]
    exchange_open_symbols: Set[str]  # symbols the exchange currently reports we hold


@dataclass(frozen=True)
class StepResult:
    actions: List[Action]
    state: EngineState


class StrategyEngine:
    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def step(self, state: EngineState, snapshot: MarketSnapshot, now: datetime) -> StepResult:
        cfg = self.cfg
        current_rate = {s.symbol: s.pred_rate for s in snapshot.symbols}
        actions: List[Action] = []
        positions: Dict[str, Position] = dict(state.positions)

        # --- 1. reconcile existing positions ---
        for symbol, pos in list(positions.items()):
            if symbol not in snapshot.exchange_open_symbols:
                # closed out of band (stop-market filled or manual close) -> just forget it
                positions.pop(symbol)
                continue
            reason = should_exit(pos, current_rate.get(symbol), now, cfg)
            if reason is not None:
                actions.append(ClosePosition(symbol=symbol, reason=reason))
                positions.pop(symbol)

        # --- 2. evaluate new entries ---
        # fill prev_pred_rate from our own persisted episode memory
        enriched = [replace(s, prev_pred_rate=state.last_pred_rate.get(s.symbol))
                    for s in snapshot.symbols]
        signals = evaluate_entries(enriched, cfg)
        chosen = select_entries(
            signals,
            open_symbols=set(positions.keys()),
            open_count=len(positions),
            cfg=cfg,
        )

        meta = {s.symbol: s for s in snapshot.symbols}
        notional = target_notional(snapshot.account.equity, cfg)
        for sig in chosen:
            m = meta[sig.symbol]
            volume = notional_to_volume(
                notional, m.mark_price, m.contract_size, m.vol_scale, m.min_volume
            )
            if volume <= 0:
                continue
            actions.append(OpenShort(symbol=sig.symbol, volume=volume, mark_price=m.mark_price))
            positions[sig.symbol] = Position(
                symbol=sig.symbol,
                side="SHORT",
                entry_price=m.mark_price,
                volume=volume,
                entry_time=now,
                stop_price=short_stop_price(m.mark_price, cfg.stop_pct),
                stop_order_id=None,
                status=PositionStatus.OPEN,
            )

        # --- 3. advance episode memory for every observed symbol ---
        new_memory = dict(state.last_pred_rate)
        new_memory.update(current_rate)

        return StepResult(
            actions=actions,
            state=EngineState(positions=positions, last_pred_rate=new_memory),
        )
