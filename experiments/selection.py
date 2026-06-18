"""
Pure symbol-selection helpers for the execution harness.

Used to pick the cheapest API-tradable USDT perps whose single-contract notional fits a small
experiment budget, so a live round-trip costs as little real money as possible.
"""

from __future__ import annotations

from typing import Dict, List


def one_contract_notional(contract_size: float, price: float) -> float:
    return contract_size * price


def spread_bps(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 0.0
    return (ask - bid) / mid * 10_000.0


def rank_affordable(contracts: List[dict], tickers: Dict[str, dict], budget: float) -> List[dict]:
    """Tradable USDT perps with 1-contract notional <= budget, cheapest first."""
    out = []
    for c in contracts:
        if c.get("quoteCoin") != "USDT" or not c.get("apiAllowed") or c.get("state") != 0:
            continue
        tk = tickers.get(c["symbol"])
        if not tk:
            continue
        price = float(tk.get("lastPrice", 0.0))
        notional = one_contract_notional(float(c["contractSize"]), price)
        if notional <= 0 or notional > budget:
            continue
        out.append({
            "symbol": c["symbol"],
            "price": price,
            "contract_size": float(c["contractSize"]),
            "min_vol": float(c["minVol"]),
            "notional_1c": notional,
            "spread_bps": spread_bps(float(tk.get("bid1", 0.0)), float(tk.get("ask1", 0.0))),
            "taker_fee_bps": float(c.get("takerFeeRate", 0.0)) * 10_000.0,
        })
    out.sort(key=lambda r: r["notional_1c"])
    return out
