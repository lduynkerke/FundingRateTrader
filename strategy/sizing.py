"""
Position sizing: turn a 5%-of-equity notional target into a valid contract volume.

Volume is floored to the exchange's allowed decimal places so we never overshoot the
notional/equity budget, and rejected (-> 0.0) if it lands below the minimum order size.
"""

from __future__ import annotations

import math

from strategy.config import StrategyConfig


def target_notional(equity: float, cfg: StrategyConfig) -> float:
    """Notional (quote currency) to deploy on one trade."""
    return equity * cfg.equity_fraction


def notional_to_volume(
    notional: float,
    price: float,
    contract_size: float,
    vol_scale: int,
    min_volume: float,
) -> float:
    """Convert a quote-currency notional to a tradable contract volume.

    Returns 0.0 when the inputs are unusable or the rounded volume is below the
    exchange minimum (i.e. this symbol can't be traded at this size).
    """
    if price <= 0 or contract_size <= 0 or notional <= 0:
        return 0.0

    raw = notional / (price * contract_size)
    factor = 10 ** vol_scale
    volume = math.floor(raw * factor) / factor

    if volume < min_volume:
        return 0.0
    return volume
