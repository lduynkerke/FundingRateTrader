"""
build_exchange backend selection: paper by default, live only behind an explicit confirm.

Live trading must never start by accident, so build_exchange requires the FRT_CONFIRM_LIVE=1
environment flag AND resolvable credentials before it will construct a MexcExchange.
"""

import pytest

from exchange.mexc import MexcExchange
from exchange.paper import PaperExchange
from main import build_exchange

LIVE_CREDS = {"api_key": "k", "secret_key": "s"}


def test_paper_mode_builds_paper_exchange():
    ex = build_exchange("paper", {"paper_start_equity": 500.0}, {})
    assert isinstance(ex, PaperExchange)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        build_exchange("bogus", {}, {})


def test_live_mode_requires_confirm_flag(monkeypatch):
    monkeypatch.delenv("FRT_CONFIRM_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="FRT_CONFIRM_LIVE"):
        build_exchange("live", {}, LIVE_CREDS)


def test_live_mode_requires_credentials(monkeypatch):
    monkeypatch.setenv("FRT_CONFIRM_LIVE", "1")
    with pytest.raises(RuntimeError, match="credential"):
        build_exchange("live", {}, {"api_key": "", "secret_key": ""})


def test_live_mode_builds_mexc_exchange_when_confirmed(monkeypatch):
    monkeypatch.setenv("FRT_CONFIRM_LIVE", "1")
    ex = build_exchange("live", {}, LIVE_CREDS)
    assert isinstance(ex, MexcExchange)
    assert ex._base == "https://contract.mexc.co"  # the gateway-unblocked mirror
