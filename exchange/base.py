"""
The Exchange interface the executor depends on, plus shared value types.

Both PaperExchange (simulation) and MexcExchange (live) implement this Protocol, so the
identical engine + executor drive either with a one-line backend swap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Set, runtime_checkable


@dataclass(frozen=True)
class OrderFill:
    order_id: str
    avg_price: float
    volume: float


@runtime_checkable
class Exchange(Protocol):
    def get_equity(self) -> float: ...

    def list_open_symbols(self) -> Set[str]: ...

    def open_short(self, symbol: str, volume: float) -> OrderFill: ...

    def place_stop(self, symbol: str, volume: float, stop_price: float) -> str: ...

    def close(self, symbol: str) -> OrderFill: ...

    def cancel_all(self, symbol: str) -> None: ...
