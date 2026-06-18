"""
Scheduler — drives one decision cycle (run_cycle) and the live timing loop (run_forever).

run_cycle is the production path: scan funding for the whole universe (so episode memory
advances for every symbol and exits are evaluated on held names), build full snapshots only
for the qualifying high-funding candidates, then step the engine and execute. It is pure of
timing so it can be tested with injected data + a paper exchange.

run_forever wraps it in the +entry_delay-after-settlement cadence; that part is thin
orchestration and is exercised in paper mode rather than unit tests.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from exchange.mexc_data import MexcData
from runtime.executor import Executor
from runtime.state_store import save_state
from strategy.config import StrategyConfig
from strategy.engine import EngineState, MarketSnapshot, StrategyEngine
from strategy.models import Account, Action, SymbolSnapshot
from utils.logger import get_logger


def run_cycle(
    now: datetime,
    data: MexcData,
    engine: StrategyEngine,
    executor: Executor,
    exchange,
    state: EngineState,
    cfg: StrategyConfig,
) -> Tuple[EngineState, List[Action]]:
    """Execute one settlement decision cycle; return (new_state, actions taken)."""
    contracts = {c["symbol"]: c for c in data.list_contracts()}
    symbols = [s for s in data.usdt_perp_symbols()]

    funding_map = {sym: data.funding(sym) for sym in symbols}
    held = exchange.list_open_symbols()

    # feed the paper simulator the latest fair prices (and credit funding to held shorts)
    if hasattr(exchange, "set_price"):
        for sym in symbols:
            exchange.set_price(sym, funding_map[sym]["fair_price"])
        for sym in held:
            if sym in funding_map:
                exchange.apply_funding(sym, funding_map[sym]["pred_rate"])

    snapshots: List[SymbolSnapshot] = []
    for sym in symbols:
        f = funding_map[sym]
        if f["pred_rate"] >= cfg.entry_threshold and sym in contracts:
            snapshots.append(data.build_snapshot(sym, contracts[sym], now=now))
        else:
            # lightweight: enough to advance memory and evaluate exits; fails threshold anyway
            snapshots.append(SymbolSnapshot(
                symbol=sym, pred_rate=f["pred_rate"], prev_pred_rate=None,
                listing_age_days=0.0, liquidity_quote_vol_5m=0.0,
                mark_price=f["fair_price"], contract_size=1.0, vol_scale=0, min_volume=1.0,
            ))

    snapshot = MarketSnapshot(
        account=Account(equity=exchange.get_equity()),
        symbols=snapshots,
        exchange_open_symbols=exchange.list_open_symbols(),
    )
    result = engine.step(state, snapshot, now)
    new_state = executor.execute(result.actions, result.state)
    return new_state, result.actions


def run_forever(
    data: MexcData,
    engine: StrategyEngine,
    executor: Executor,
    exchange,
    state: EngineState,
    cfg: StrategyConfig,
    state_path: str,
    entry_delay_minutes: int,
    poll_seconds: int = 60,
):
    """Wake near each settlement+delay, run a cycle, persist. Crash-safe via saved state."""
    logger = get_logger()
    logger.info("Scheduler running; entry delay = %d min after settlement", entry_delay_minutes)
    last_cycle_key: Optional[str] = None

    while True:
        now = datetime.now(timezone.utc)
        # settlements land on whole hours; act once per hour in the post-settlement window
        in_window = entry_delay_minutes <= now.minute < entry_delay_minutes + 5
        cycle_key = now.strftime("%Y-%m-%dT%H")
        if in_window and cycle_key != last_cycle_key:
            try:
                state, actions = run_cycle(now, data, engine, executor, exchange, state, cfg)
                save_state(state, state_path)
                if actions:
                    logger.info("Cycle %s actions: %s", cycle_key, actions)
                last_cycle_key = cycle_key
            except Exception:
                logger.exception("run_cycle failed; will retry next poll")
        time.sleep(poll_seconds)
