"""
Domain data types shared across the pure strategy core.

All times are timezone-aware UTC datetimes. Rates are fractions (0.02 == 2%).
These objects carry no behaviour beyond construction — logic lives in the function modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Union


@dataclass(frozen=True)
class SymbolSnapshot:
    """Everything the engine needs to know about one symbol at one decision point."""
    symbol: str
    pred_rate: float                     # predicted funding rate at the just-passed settlement
    prev_pred_rate: Optional[float]      # predicted rate at the previous settlement (None if unknown)
    listing_age_days: float
    liquidity_quote_vol_5m: float        # median quiet pre-event quote-volume per 5m bar ($)
    mark_price: float
    # contract metadata used for sizing (optional at signal stage)
    contract_size: float = 1.0           # base units per contract
    vol_scale: int = 0                   # decimal places allowed on contract volume
    min_volume: float = 1.0              # exchange minimum order volume (contracts)


@dataclass(frozen=True)
class EntrySignal:
    symbol: str
    pred_rate: float
    mark_price: float


@dataclass(frozen=True)
class Account:
    equity: float                        # total equity in quote currency (USDT)


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Position:
    symbol: str
    side: str                            # "SHORT"
    entry_price: float
    volume: float                        # contracts
    entry_time: datetime
    stop_price: float
    stop_order_id: Optional[str] = None
    status: PositionStatus = PositionStatus.OPEN


class ExitReason(str, Enum):
    NORMALIZED = "rate_normalized"
    TIME_CAP = "time_cap"
    STOP = "stop"


# --- Actions: what engine.step emits for the executor to perform ---

@dataclass(frozen=True)
class OpenShort:
    symbol: str
    volume: float
    mark_price: float                    # reference price at decision time (for paper/logging)


@dataclass(frozen=True)
class PlaceStop:
    symbol: str
    stop_price: float
    volume: float


@dataclass(frozen=True)
class ClosePosition:
    symbol: str
    reason: ExitReason


@dataclass(frozen=True)
class CancelOrder:
    symbol: str
    order_id: str


Action = Union[OpenShort, PlaceStop, ClosePosition, CancelOrder]
