"""
Exit logic for an open S1-Episode short (pure functions).

Two engine-driven exits: rate-normalization (the episode is over) and a 24h time cap
(backstop). The hard adverse-excursion stop rests on the exchange as a stop-market order;
the engine reconciles a stop fill separately. Normalization wins ties over the time cap.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from strategy.config import StrategyConfig
from strategy.models import ExitReason, Position


def short_stop_price(entry_price: float, stop_pct: float) -> float:
    """Stop-market trigger for a short: a stop_pct adverse (upward) move from entry."""
    return entry_price * (1.0 + stop_pct)


def _is_normalized(latest_pred_rate: float, cfg: StrategyConfig) -> bool:
    # Episode over when funding decays below the floor or flips non-positive.
    return abs(latest_pred_rate) < cfg.normalize_threshold or latest_pred_rate <= 0.0


def should_exit(
    position: Position,
    latest_pred_rate: Optional[float],
    now: datetime,
    cfg: StrategyConfig,
) -> Optional[ExitReason]:
    """Return the exit reason if this position should be closed now, else None."""
    if latest_pred_rate is not None and _is_normalized(latest_pred_rate, cfg):
        return ExitReason.NORMALIZED

    held_hours = (now - position.entry_time).total_seconds() / 3600.0
    if held_hours >= cfg.time_cap_hours:
        return ExitReason.TIME_CAP

    return None
