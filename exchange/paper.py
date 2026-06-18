"""
PaperExchange — in-memory simulator implementing the Exchange protocol.

Default backend for dry-runs. Fills market orders at the current price, fires resting
stop-market orders when the price gaps through them, and tracks equity with round-trip
fees and (optionally) funding credits. Deterministic: prices are driven explicitly via
set_price, so a test or paper loop fully controls the tape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set

from exchange.base import OrderFill


@dataclass
class _PaperPosition:
    volume: float
    entry_price: float
    contract_size: float


@dataclass
class _PaperStop:
    volume: float
    stop_price: float
    order_id: str


class PaperExchange:
    def __init__(
        self,
        equity: float,
        prices: Optional[Dict[str, float]] = None,
        fee_round_trip: float = 0.003,
        contract_sizes: Optional[Dict[str, float]] = None,
    ):
        self._equity = equity
        self._prices: Dict[str, float] = dict(prices or {})
        self._fee_half = fee_round_trip / 2.0
        self._contract_sizes = dict(contract_sizes or {})
        self._positions: Dict[str, _PaperPosition] = {}
        self._stops: Dict[str, _PaperStop] = {}
        self._order_seq = 0

    # --- helpers ---
    def _next_id(self, prefix: str) -> str:
        self._order_seq += 1
        return f"{prefix}-{self._order_seq}"

    def _cs(self, symbol: str) -> float:
        return self._contract_sizes.get(symbol, 1.0)

    def _fill_close(self, symbol: str, exit_price: float) -> OrderFill:
        pos = self._positions.pop(symbol)
        self._stops.pop(symbol, None)
        cs = pos.contract_size
        pnl = (pos.entry_price - exit_price) * pos.volume * cs  # short
        fee = exit_price * pos.volume * cs * self._fee_half
        self._equity += pnl - fee
        return OrderFill(order_id=self._next_id("close"), avg_price=exit_price, volume=pos.volume)

    # --- Exchange protocol ---
    def get_equity(self) -> float:
        return self._equity

    def list_open_symbols(self) -> Set[str]:
        return set(self._positions.keys())

    def get_price(self, symbol: str) -> float:
        return self._prices[symbol]

    def open_short(self, symbol: str, volume: float) -> OrderFill:
        price = self._prices[symbol]
        cs = self._cs(symbol)
        self._positions[symbol] = _PaperPosition(volume=volume, entry_price=price, contract_size=cs)
        self._equity -= price * volume * cs * self._fee_half
        return OrderFill(order_id=self._next_id("open"), avg_price=price, volume=volume)

    def place_stop(self, symbol: str, volume: float, stop_price: float) -> str:
        oid = self._next_id("stop")
        self._stops[symbol] = _PaperStop(volume=volume, stop_price=stop_price, order_id=oid)
        return oid

    def close(self, symbol: str) -> OrderFill:
        return self._fill_close(symbol, self._prices[symbol])

    def cancel_all(self, symbol: str) -> None:
        self._stops.pop(symbol, None)

    # --- simulation controls ---
    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price
        stop = self._stops.get(symbol)
        if stop is not None and symbol in self._positions and price >= stop.stop_price:
            # stop-market gaps through -> fill at the stop trigger price
            self._fill_close(symbol, stop.stop_price)

    def apply_funding(self, symbol: str, rate: float) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            return
        # short receives funding when rate is positive
        self._equity += rate * pos.entry_price * pos.volume * pos.contract_size
