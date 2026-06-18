"""
MEXC contract (futures) request signing.

Authoritative scheme (mexcdevelop.github.io/apidocs/contract_v1_en):
  signString = accessKey + requestTime(ms) + paramString
  signature  = HMAC_SHA256(secretKey, signString)  (hex)
  GET/DELETE : params sorted alphabetically, URL-encoded, joined by '&'
  POST       : the exact JSON body string (no sorting)
Headers: ApiKey, Request-Time (ms), Signature, Content-Type: application/json.

Standalone (not the broken api/base_client._sign_request) so the live trading path has a
single, tested source of truth for auth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional
from urllib.parse import urlencode


def param_string_get(params: Optional[dict]) -> str:
    """Sorted, URL-encoded query string used for GET/DELETE signing AND the request URL."""
    if not params:
        return ""
    items = sorted(params.items(), key=lambda kv: kv[0])
    return urlencode(items)


def body_string(obj: Optional[dict]) -> str:
    """Compact JSON body string used for POST signing AND the request body (must match exactly)."""
    if not obj:
        return ""
    return json.dumps(obj, separators=(", ", ": "))


def sign(access_key: str, secret_key: str, timestamp_ms: str, param_string: str) -> str:
    sign_string = f"{access_key}{timestamp_ms}{param_string}"
    return hmac.new(
        secret_key.encode("utf-8"), sign_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def auth_headers(access_key: str, secret_key: str, timestamp_ms: str, param_string: str) -> dict:
    return {
        "ApiKey": access_key,
        "Request-Time": timestamp_ms,
        "Signature": sign(access_key, secret_key, timestamp_ms, param_string),
        "Content-Type": "application/json",
    }
