"""
MexcExchange — live MEXC contract (futures) trading client implementing the Exchange protocol.

All auth goes through exchange.mexc_signing. The POST body sent over the wire is the *exact*
signed string (sent as raw data, not re-serialized) so the signature always matches the bytes.
Every response is checked for code == 0 and raises MexcError otherwise.

Order codes (MEXC docs): side 1=open long, 2=close short, 3=open short, 4=close long;
type 5=market; openType 1=isolated. Protective stop = planorder (trigger order) that closes
the short (side 2) at market when price rises to the trigger (triggerType 1 = price >=).

HTTP transport + clock are injected for testing; the default transport uses requests with a
truststore-patched TLS context (TLS-intercepting proxy in this environment).

Base host: the `contract.mexc.com` edge WAF-blocks POST /order/submit with an HTML 403
("Access Denied") even though every read succeeds. The `contract.mexc.co` mirror is NOT behind
that WAF and accepts order/submit (verified live 2026-06-19 via experiments/domain_probe.py),
so the default base_url points at the `.co` host. MEXC support confirmed `.co` as the backup.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Set

from exchange.base import OrderFill
from exchange.mexc_signing import auth_headers, body_string, param_string_get


class MexcError(RuntimeError):
    def __init__(self, code, message, payload=None):
        super().__init__(f"MEXC error code={code}: {message}")
        self.code = code
        self.message = message
        self.payload = payload


def _default_transport(method: str, url: str, headers: dict, body: Optional[str]) -> dict:
    import requests
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    if method == "GET":
        resp = requests.get(url, headers=headers, timeout=15)
    else:
        # send the exact signed string as the raw body
        resp = requests.post(url, headers=headers, data=(body or ""), timeout=15)
    try:
        return resp.json()
    except ValueError:
        # non-JSON error body (e.g. an HTML 403) -> surface as a MEXC-style error payload
        return {"success": False, "code": resp.status_code,
                "message": (resp.text or resp.reason)[:300]}


class MexcExchange:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = "https://contract.mexc.co",
        transport: Callable = None,
        clock: Callable[[], str] = None,
        default_leverage: int = 1,
        open_type: int = 1,  # 1 = isolated
    ):
        self._key = api_key
        self._secret = secret_key
        self._base = base_url.rstrip("/")
        self._transport = transport or _default_transport
        self._clock = clock or (lambda: str(int(time.time() * 1000)))
        self._leverage = default_leverage
        self._open_type = open_type

    # --- signed transport ---
    def _check(self, resp: dict) -> dict:
        if resp.get("code", 0) != 0:
            raise MexcError(resp.get("code"), resp.get("message", resp.get("msg", "")), resp)
        return resp

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        ps = param_string_get(params)
        headers = auth_headers(self._key, self._secret, self._clock(), ps)
        url = f"{self._base}{path}"
        if ps:
            url = f"{url}?{ps}"
        return self._check(self._transport("GET", url, headers, None))

    def _post(self, path: str, body: dict) -> dict:
        bs = body_string(body)
        headers = auth_headers(self._key, self._secret, self._clock(), bs)
        return self._check(self._transport("POST", f"{self._base}{path}", headers, bs))

    # --- account / positions ---
    def get_equity(self) -> float:
        data = self._get("/api/v1/private/account/assets").get("data", [])
        for asset in data:
            if asset.get("currency") == "USDT":
                return float(asset.get("equity", 0.0))
        return 0.0

    def get_positions(self, symbol: Optional[str] = None) -> List[dict]:
        params = {"symbol": symbol} if symbol else None
        return self._get("/api/v1/private/position/open_positions", params).get("data", []) or []

    def list_open_symbols(self) -> Set[str]:
        return {p["symbol"] for p in self.get_positions() if float(p.get("holdVol", 0)) > 0}

    def _get_order(self, order_id) -> dict:
        return self._get(f"/api/v1/private/order/get/{order_id}").get("data", {})

    def get_order(self, order_id) -> dict:
        """Public accessor for a single order's detail (fills, fees, state)."""
        return self._get_order(order_id)

    # --- trading ---
    def open_short(self, symbol: str, volume: float) -> OrderFill:
        resp = self._post("/api/v1/private/order/submit", {
            "symbol": symbol, "vol": volume, "side": 3, "type": 5,
            "openType": self._open_type, "leverage": self._leverage,
        })
        order_id = resp["data"]["orderId"] if isinstance(resp["data"], dict) else resp["data"]
        detail = self._get_order(order_id)
        return OrderFill(
            order_id=str(order_id),
            avg_price=float(detail.get("dealAvgPrice", 0.0) or 0.0),
            volume=float(detail.get("dealVol", volume) or volume),
        )

    def place_stop(self, symbol: str, volume: float, stop_price: float) -> str:
        resp = self._post("/api/v1/private/planorder/place", {
            "symbol": symbol, "vol": volume, "side": 2, "openType": self._open_type,
            "leverage": self._leverage, "triggerPrice": stop_price, "triggerType": 1,
            "executeCycle": 2, "orderType": 5, "trend": 2,
        })
        data = resp["data"]
        return str(data["orderId"] if isinstance(data, dict) else data)

    def close(self, symbol: str) -> OrderFill:
        positions = self.get_positions(symbol)
        pos = next((p for p in positions if float(p.get("holdVol", 0)) > 0), None)
        if pos is None:
            return OrderFill(order_id="", avg_price=0.0, volume=0.0)
        body = {
            "symbol": symbol, "vol": float(pos["holdVol"]), "side": 2, "type": 5,
            "openType": self._open_type, "positionId": pos["positionId"],
        }
        resp = self._post("/api/v1/private/order/submit", body)
        data = resp["data"]
        order_id = data["orderId"] if isinstance(data, dict) else data
        return OrderFill(order_id=str(order_id), avg_price=0.0, volume=float(pos["holdVol"]))

    def cancel_all(self, symbol: str) -> None:
        for path in ("/api/v1/private/order/cancel_all", "/api/v1/private/planorder/cancel_all"):
            try:
                self._post(path, {"symbol": symbol})
            except MexcError:
                pass  # nothing to cancel of that kind is not an error for our purposes

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        return self._post("/api/v1/private/position/change_leverage", {
            "symbol": symbol, "leverage": leverage, "openType": self._open_type,
        })
