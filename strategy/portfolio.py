"""
Portfolio gating (pure): concurrency cap, one-position-per-ticker, candidate ranking.

Concurrency rarely binds (avg ~1 open position) but the cap is a hard risk control, and
ranking by predicted rate gives a deterministic tie-break when a single window produces
more candidates than free slots.
"""

from __future__ import annotations

from typing import List, Set

from strategy.config import StrategyConfig
from strategy.models import EntrySignal


def open_slots(open_count: int, cfg: StrategyConfig) -> int:
    """Free position slots given the current number of open positions."""
    return max(0, cfg.max_concurrent - open_count)


def select_entries(
    signals: List[EntrySignal],
    open_symbols: Set[str],
    open_count: int,
    cfg: StrategyConfig,
) -> List[EntrySignal]:
    """Pick which entry signals to actually open this window.

    Drops tickers already held, ranks the rest by predicted rate (desc), and truncates
    to the number of free slots.
    """
    candidates = [s for s in signals if s.symbol not in open_symbols]
    candidates.sort(key=lambda s: s.pred_rate, reverse=True)
    return candidates[: open_slots(open_count, cfg)]
