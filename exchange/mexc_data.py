"""
MexcData — MEXC public (unauthenticated) market-data adapter.

Maps the real contract/detail, funding_rate, and kline(Min5) responses into the domain
SymbolSnapshot the engine consumes. Public endpoints need no signing, so this works
regardless of whether the account's private contract trading API is enabled — which is
what lets paper mode run against the live tape.

HTTP is injected (`http_get`) for testability; the default transport uses requests with
a truststore-patched TLS context (this shell sits behind a TLS-intercepting proxy).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from strategy.models import SymbolSnapshot

DEFAULT_BASE = "https://contract.mexc.com"


def _default_get(url: str, params: Optional[dict] = None) -> dict:
    import requests
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


class MexcData:
    def __init__(self, base_url: str = DEFAULT_BASE, http_get: Callable = None):
        self._base = base_url
        self._get = http_get or _default_get

    # --- raw endpoints ---
    def list_contracts(self) -> List[dict]:
        return self._get(f"{self._base}/api/v1/contract/detail")["data"]

    def tickers(self) -> Dict[str, dict]:
        """All contract tickers keyed by symbol (lastPrice, fairPrice, bid1, ask1, ...)."""
        data = self._get(f"{self._base}/api/v1/contract/ticker")["data"]
        return {t["symbol"]: t for t in data}

    def funding(self, symbol: str) -> Dict:
        d = self._get(f"{self._base}/api/v1/contract/funding_rate/{symbol}")["data"]
        return {
            "pred_rate": float(d["fundingRate"]),
            "collect_cycle": d["collectCycle"],
            "next_settle_time": d["nextSettleTime"],
            "fair_price": float(d["fairPrice"]),
        }

    def funding_all(self) -> Dict[str, dict]:
        """Predicted funding rate + fair price for the WHOLE universe in one ticker call.

        contract/ticker carries fundingRate (== the per-symbol predicted rate, verified live)
        and fairPrice for every symbol, so the per-cycle universe scan needs a single request
        instead of one funding_rate call per symbol (~779 -> 1).
        """
        return {
            t["symbol"]: {"pred_rate": float(t["fundingRate"]), "fair_price": float(t["fairPrice"])}
            for t in self._get(f"{self._base}/api/v1/contract/ticker")["data"]
        }

    def _klines(self, symbol: str, interval: str, start: int, end: int) -> dict:
        return self._get(
            f"{self._base}/api/v1/contract/kline/{symbol}",
            params={"interval": interval, "start": start, "end": end},
        )["data"]

    # --- derived views ---
    def usdt_perp_symbols(self) -> List[str]:
        return [
            c["symbol"] for c in self.list_contracts()
            if c.get("quoteCoin") == "USDT" and c.get("apiAllowed") and c.get("state") == 0
        ]

    def symbol_meta(self, contract: dict, now: Optional[datetime] = None) -> Dict:
        now = now or datetime.now(timezone.utc)
        created = datetime.fromtimestamp(contract["createTime"] / 1000, timezone.utc)
        return {
            "contract_size": float(contract["contractSize"]),
            "vol_scale": int(contract["volScale"]),
            "min_volume": float(contract["minVol"]),
            "listing_age_days": (now - created).total_seconds() / 86400.0,
        }

    def liquidity_quote_vol_5m(self, symbol: str, lookback_bars: int = 12,
                               now: Optional[datetime] = None) -> float:
        """Median quote-volume per 5m bar over a pre-event window (the 'quiet' proxy)."""
        now = now or datetime.now(timezone.utc)
        end = int(now.timestamp())
        start = end - lookback_bars * 5 * 60
        amounts = self._klines(symbol, "Min5", start, end).get("amount", [])
        if not amounts:
            return 0.0
        return float(statistics.median(amounts))

    def build_snapshot(self, symbol: str, contract: dict,
                       now: Optional[datetime] = None) -> SymbolSnapshot:
        """Assemble a full SymbolSnapshot (funding + meta + liquidity) for a candidate."""
        f = self.funding(symbol)
        meta = self.symbol_meta(contract, now=now)
        return SymbolSnapshot(
            symbol=symbol,
            pred_rate=f["pred_rate"],
            prev_pred_rate=None,  # engine fills from episode memory
            listing_age_days=meta["listing_age_days"],
            liquidity_quote_vol_5m=self.liquidity_quote_vol_5m(symbol, now=now),
            mark_price=f["fair_price"],
            contract_size=meta["contract_size"],
            vol_scale=meta["vol_scale"],
            min_volume=meta["min_volume"],
        )
