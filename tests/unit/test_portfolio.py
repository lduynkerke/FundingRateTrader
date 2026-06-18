"""
P4 — portfolio gating: concurrency cap (5), one-position-per-ticker, rank by pred rate.
"""

import pytest

from strategy.config import StrategyConfig
from strategy.models import EntrySignal
from strategy.portfolio import open_slots, select_entries


@pytest.fixture
def cfg():
    return StrategyConfig()


def sig(symbol, rate):
    return EntrySignal(symbol=symbol, pred_rate=rate, mark_price=1.0)


def test_open_slots(cfg):
    assert open_slots(0, cfg) == 5
    assert open_slots(3, cfg) == 2
    assert open_slots(5, cfg) == 0
    assert open_slots(7, cfg) == 0  # never negative


def test_select_drops_already_open_tickers(cfg):
    signals = [sig("A_USDT", 0.02), sig("B_USDT", 0.03)]
    chosen = select_entries(signals, open_symbols={"A_USDT"}, open_count=1, cfg=cfg)
    assert [s.symbol for s in chosen] == ["B_USDT"]


def test_select_ranks_by_pred_rate_desc(cfg):
    signals = [sig("A_USDT", 0.02), sig("B_USDT", 0.05), sig("C_USDT", 0.03)]
    chosen = select_entries(signals, open_symbols=set(), open_count=0, cfg=cfg)
    assert [s.symbol for s in chosen] == ["B_USDT", "C_USDT", "A_USDT"]


def test_select_respects_open_slots(cfg):
    signals = [sig("A_USDT", 0.02), sig("B_USDT", 0.05), sig("C_USDT", 0.03)]
    # 4 already open -> only 1 slot left -> take highest-rate candidate
    chosen = select_entries(signals, open_symbols=set(), open_count=4, cfg=cfg)
    assert [s.symbol for s in chosen] == ["B_USDT"]


def test_select_returns_empty_when_full(cfg):
    signals = [sig("A_USDT", 0.02)]
    assert select_entries(signals, open_symbols=set(), open_count=5, cfg=cfg) == []
