"""
Entry-signal evaluation for S1-Episode (pure functions).

Encodes the four entry rules from VERDICT.md. We short *positive* funding only
(perp premium on a pumped microcap), so the rate threshold is a positive lower bound
with no upper cap.
"""

from __future__ import annotations

from typing import List, Optional

from strategy.config import StrategyConfig
from strategy.models import EntrySignal, SymbolSnapshot


def is_fresh_episode(pred_rate: float, prev_pred_rate: Optional[float], threshold: float) -> bool:
    """True when this settlement starts a new high-funding episode.

    Fresh means the current rate is in-episode (>= threshold) while the previous
    settlement was not. An unknown previous rate (first observation) counts as fresh.
    """
    if pred_rate < threshold:
        return False
    if prev_pred_rate is None:
        return True
    return prev_pred_rate < threshold


def passes_entry_filters(snap: SymbolSnapshot, cfg: StrategyConfig) -> bool:
    """All four entry gates: threshold, fresh-episode, age, liquidity."""
    if snap.pred_rate < cfg.entry_threshold:
        return False
    if not is_fresh_episode(snap.pred_rate, snap.prev_pred_rate, cfg.entry_threshold):
        return False
    if snap.listing_age_days < cfg.min_age_days:
        return False
    if snap.liquidity_quote_vol_5m < cfg.min_liq_quote_vol:
        return False
    return True


def evaluate_entries(snaps: List[SymbolSnapshot], cfg: StrategyConfig) -> List[EntrySignal]:
    """Filter a batch of snapshots down to qualifying entry signals."""
    return [
        EntrySignal(symbol=s.symbol, pred_rate=s.pred_rate, mark_price=s.mark_price)
        for s in snaps
        if passes_entry_filters(s, cfg)
    ]
