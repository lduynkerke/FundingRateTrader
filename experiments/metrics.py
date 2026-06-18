"""
Pure metrics for execution experiments (no I/O).

Slippage is expressed in basis points as a *cost*: positive means the fill was adverse
(sold below / bought above the reference price), negative means price improvement.
"""

from __future__ import annotations

import statistics
from typing import List, Optional


def slippage_bps(fill: float, reference: float, side: str) -> float:
    """Signed slippage cost in bps relative to a reference (mark/fair) price."""
    if reference <= 0:
        return 0.0
    if side == "sell":          # opening a short: want a high sell price
        cost = (reference - fill) / reference
    else:                        # "buy": closing a short / opening a long
        cost = (fill - reference) / reference
    return cost * 10_000.0


def fee_bps(fee_paid: float, notional: float) -> float:
    if notional <= 0:
        return 0.0
    return fee_paid / notional * 10_000.0


def fill_ratio(filled: float, requested: float) -> float:
    if requested <= 0:
        return 0.0
    return filled / requested


def summarize_latencies(samples_ms: List[float]) -> dict:
    if not samples_ms:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {
        "n": len(samples_ms),
        "min": min(samples_ms),
        "median": statistics.median(samples_ms),
        "max": max(samples_ms),
    }
