"""
L1 — MEXC contract request signing.

signString = accessKey + requestTime(ms) + paramString ; HMAC-SHA256 hex.
GET params are sorted alphabetically and URL-encoded; POST signs the exact JSON body string.
Vectors below were computed independently so the exact signed bytes can't drift unnoticed.
"""

from exchange.mexc_signing import auth_headers, body_string, param_string_get, sign

ACCESS = "testkey"
SECRET = "testsecret"
TS = "1700000000000"


def test_get_param_string_is_sorted_and_encoded():
    assert param_string_get({"symbol": "BTC_USDT", "page_num": 1}) == "page_num=1&symbol=BTC_USDT"


def test_get_param_string_url_encodes_special_chars():
    # commas etc. must be encoded when signing
    assert param_string_get({"orderIds": "1,2"}) == "orderIds=1%2C2"


def test_empty_params_is_empty_string():
    assert param_string_get({}) == ""
    assert param_string_get(None) == ""


def test_body_string_is_compact_json_preserving_order():
    assert body_string({"symbol": "BTC_USDT", "vol": 1}) == '{"symbol": "BTC_USDT", "vol": 1}'


def test_sign_get_vector():
    sig = sign(ACCESS, SECRET, TS, "page_num=1&symbol=BTC_USDT")
    assert sig == "bc02d78f94742bb7fb74ad6530e0a0284b00a73b6abe7a748145b3a40c7aecc0"


def test_sign_post_vector():
    sig = sign(ACCESS, SECRET, TS, '{"symbol": "BTC_USDT", "vol": 1}')
    assert sig == "0a62ff16fe4b17f48b76115519c80361a5eb1dcd9ca6e51d26f4156f23ea9266"


def test_auth_headers_contains_required_fields():
    headers = auth_headers(ACCESS, SECRET, TS, "page_num=1&symbol=BTC_USDT")
    assert headers["ApiKey"] == ACCESS
    assert headers["Request-Time"] == TS
    assert headers["Content-Type"] == "application/json"
    assert headers["Signature"] == "bc02d78f94742bb7fb74ad6530e0a0284b00a73b6abe7a748145b3a40c7aecc0"
