"""
P8a — MexcData: public market-data adapter mapping real MEXC responses to domain types.

Payloads below are trimmed copies of the live shapes probed from contract.mexc.com
(funding_rate, contract/detail, kline Min5). HTTP is injected so these tests never hit
the network.
"""

from datetime import datetime, timezone

import pytest

from exchange.mexc_data import MexcData

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)

DETAIL = {"success": True, "code": 0, "data": [
    {"symbol": "BTC_USDT", "quoteCoin": "USDT", "contractSize": 0.0001, "minVol": 1,
     "volScale": 0, "priceScale": 1, "createTime": 1591242684000, "apiAllowed": True, "state": 0},
    {"symbol": "PUMP_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
     "volScale": 0, "priceScale": 4, "createTime": 1591242684000, "apiAllowed": True, "state": 0},
    {"symbol": "NOAPI_USDT", "quoteCoin": "USDT", "contractSize": 1.0, "minVol": 1,
     "volScale": 0, "priceScale": 4, "createTime": 1591242684000, "apiAllowed": False, "state": 0},
    {"symbol": "BTC_USDC", "quoteCoin": "USDC", "contractSize": 1.0, "minVol": 1,
     "volScale": 0, "priceScale": 4, "createTime": 1591242684000, "apiAllowed": True, "state": 0},
]}

FUNDING = {"success": True, "code": 0, "data": {
    "symbol": "PUMP_USDT", "fundingRate": 0.02, "maxFundingRate": 0.0018,
    "minFundingRate": -0.0018, "collectCycle": 8, "nextSettleTime": 1781740800000,
    "timestamp": 1781732059971, "idxPrice": 1.0, "fairPrice": 1.05}}

KLINE = {"success": True, "code": 0, "data": {
    "time": [1, 2, 3, 4],
    "close": [1.0, 1.01, 1.0, 1.02],
    "amount": [600.0, 400.0, 1000.0, 800.0],  # quote-vol per 5m bar
}}


def fake_http(url, params=None):
    if "/contract/detail" in url:
        return DETAIL
    if "/funding_rate/" in url:
        return FUNDING
    if "/kline/" in url:
        return KLINE
    raise AssertionError(f"unexpected url {url}")


@pytest.fixture
def data():
    return MexcData(http_get=fake_http)


def test_usdt_perp_symbols_filters_quote_api_and_state(data):
    syms = data.usdt_perp_symbols()
    # only USDT-quoted, api-allowed, enabled contracts
    assert syms == ["BTC_USDT", "PUMP_USDT"]


def test_contract_meta_includes_listing_age(data):
    contracts = {c["symbol"]: c for c in data.list_contracts()}
    meta = data.symbol_meta(contracts["BTC_USDT"], now=NOW)
    assert meta["contract_size"] == 0.0001
    assert meta["vol_scale"] == 0
    assert meta["min_volume"] == 1
    # createTime 2020-06 -> well over 90 days by 2026
    assert meta["listing_age_days"] > 2000


def test_funding_maps_predicted_rate_and_fair_price(data):
    f = data.funding("PUMP_USDT")
    assert f["pred_rate"] == 0.02
    assert f["collect_cycle"] == 8
    assert f["fair_price"] == 1.05
    assert f["next_settle_time"] == 1781740800000


def test_liquidity_is_median_quote_vol(data):
    # median of [600, 400, 1000, 800] = 700
    assert data.liquidity_quote_vol_5m("PUMP_USDT") == pytest.approx(700.0)


def test_build_full_snapshot(data):
    contracts = {c["symbol"]: c for c in data.list_contracts()}
    snap = data.build_snapshot("PUMP_USDT", contracts["PUMP_USDT"], now=NOW)
    assert snap.symbol == "PUMP_USDT"
    assert snap.pred_rate == 0.02
    assert snap.mark_price == 1.05           # fair price
    assert snap.liquidity_quote_vol_5m == pytest.approx(700.0)
    assert snap.contract_size == 1.0
    assert snap.listing_age_days > 2000
