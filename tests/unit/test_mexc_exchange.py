"""
L2 — MexcExchange (private contract trading) implementing the Exchange protocol.

HTTP is injected via a FakeTransport that records every call, so we assert the exact request
construction (method, signed headers, GET query / POST body) and the response->domain mapping
without any network. Order codes per MEXC docs: open short=3, close short=2, market type=5.
"""

from types import SimpleNamespace

import pytest

from exchange.base import OrderFill
from exchange.mexc import MexcError, MexcExchange
from exchange.mexc_signing import sign

KEY, SECRET, TS = "testkey", "testsecret", "1700000000000"


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.routes = {}  # url-substring -> response dict, or list (popped in order)

    def __call__(self, method, url, headers, body):
        self.calls.append(SimpleNamespace(method=method, url=url, headers=headers, body=body))
        for key, resp in self.routes.items():
            if key in url:
                return resp.pop(0) if isinstance(resp, list) else resp
        raise AssertionError(f"no canned response for {url}")

    def call_to(self, substr):
        return next(c for c in self.calls if substr in c.url)


def make(transport):
    return MexcExchange(KEY, SECRET, base_url="https://x", transport=transport,
                        clock=lambda: TS, default_leverage=1)


def test_default_base_url_is_gateway_unblocked_co_mirror():
    # The .com host is WAF-blocked on order/submit (HTML 403); the .co mirror is not
    # (verified live 2026-06-19, experiments/domain_probe.py). Default to the working host.
    ex = MexcExchange(KEY, SECRET)
    assert ex._base == "https://contract.mexc.co"


def test_raises_on_nonzero_code():
    t = FakeTransport()
    t.routes["/account/assets"] = {"success": False, "code": 602, "message": "sign error"}
    with pytest.raises(MexcError) as e:
        make(t).get_equity()
    assert e.value.code == 602


def test_get_equity_signs_and_maps_usdt():
    t = FakeTransport()
    t.routes["/account/assets"] = {"success": True, "code": 0, "data": [
        {"currency": "BTC", "equity": 0.0},
        {"currency": "USDT", "equity": 1234.56, "availableBalance": 1000.0},
    ]}
    assert make(t).get_equity() == pytest.approx(1234.56)
    call = t.call_to("/account/assets")
    assert call.method == "GET"
    assert call.headers["ApiKey"] == KEY
    # GET with no params -> signature over empty param string
    assert call.headers["Signature"] == sign(KEY, SECRET, TS, "")


def test_list_open_symbols_filters_zero_holdings():
    t = FakeTransport()
    t.routes["/position/open_positions"] = {"success": True, "code": 0, "data": [
        {"symbol": "PUMP_USDT", "holdVol": 500.0, "positionId": 99},
        {"symbol": "DEAD_USDT", "holdVol": 0.0, "positionId": 7},
    ]}
    assert make(t).list_open_symbols() == {"PUMP_USDT"}


def test_open_short_submits_market_then_returns_fill():
    t = FakeTransport()
    t.routes["/order/submit"] = {"success": True, "code": 0, "data": {"orderId": 12345}}
    t.routes["/order/get/"] = {"success": True, "code": 0,
                               "data": {"dealAvgPrice": 1.05, "dealVol": 500.0, "state": 3}}
    fill = make(t).open_short("PUMP_USDT", 500.0)
    assert fill == OrderFill(order_id="12345", avg_price=1.05, volume=500.0)

    submit = t.call_to("/order/submit")
    assert submit.method == "POST"
    # body carries the S1 short-market params and is what was signed
    assert '"side": 3' in submit.body and '"type": 5' in submit.body
    assert '"openType": 1' in submit.body and '"vol": 500.0' in submit.body
    assert submit.headers["Signature"] == sign(KEY, SECRET, TS, submit.body)


def test_place_stop_builds_trigger_close_short():
    t = FakeTransport()
    t.routes["/planorder/place"] = {"success": True, "code": 0, "data": {"orderId": 777}}
    oid = make(t).place_stop("PUMP_USDT", 500.0, stop_price=1.175)
    assert oid == "777"
    body = t.call_to("/planorder/place").body
    assert '"side": 2' in body          # close short
    assert '"triggerType": 1' in body   # trigger when price >= stop
    assert '"orderType": 5' in body     # market on trigger
    assert '"triggerPrice": 1.175' in body


def test_close_uses_position_id_and_holdvol():
    t = FakeTransport()
    t.routes["/position/open_positions"] = {"success": True, "code": 0, "data": [
        {"symbol": "PUMP_USDT", "holdVol": 500.0, "positionId": 99},
    ]}
    t.routes["/order/submit"] = {"success": True, "code": 0, "data": {"orderId": 5}}
    make(t).close("PUMP_USDT")
    body = t.call_to("/order/submit").body
    assert '"side": 2' in body          # close short
    assert '"type": 5' in body          # market
    assert '"positionId": 99' in body
    assert '"vol": 500.0' in body


def test_cancel_all_cancels_orders_and_plan_orders():
    t = FakeTransport()
    t.routes["/order/cancel_all"] = {"success": True, "code": 0, "data": None}
    t.routes["/planorder/cancel_all"] = {"success": True, "code": 0, "data": None}
    make(t).cancel_all("PUMP_USDT")
    assert any("/order/cancel_all" in c.url for c in t.calls)
    assert any("/planorder/cancel_all" in c.url for c in t.calls)
