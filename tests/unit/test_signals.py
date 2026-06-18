"""
P1 — pure entry-signal logic for S1-Episode.

These tests pin the four entry rules from VERDICT.md:
  1. predicted rate >= threshold (1%), lower bound only (no 2% upper cap)
  2. fresh-episode: previous settlement's predicted rate was < threshold
  3. listing age >= 90 days
  4. liquidity floor: quiet pre-event quote-vol >= $500 / 5m bar
No I/O — everything operates on plain domain objects.
"""

import pytest

from strategy.config import StrategyConfig
from strategy.models import SymbolSnapshot
from strategy.signals import is_fresh_episode, passes_entry_filters, evaluate_entries


@pytest.fixture
def cfg():
    return StrategyConfig()  # defaults: thr=0.01, age=90, liq=500


def make_snapshot(**kw):
    base = dict(
        symbol="PUMP_USDT",
        pred_rate=0.02,
        prev_pred_rate=0.0,      # below threshold -> fresh
        listing_age_days=120.0,
        liquidity_quote_vol_5m=1000.0,
        mark_price=1.0,
    )
    base.update(kw)
    return SymbolSnapshot(**base)


# --- is_fresh_episode -------------------------------------------------------

def test_fresh_when_prev_below_threshold(cfg):
    assert is_fresh_episode(0.02, 0.0, cfg.entry_threshold) is True

def test_not_fresh_when_prev_already_in_episode(cfg):
    # rate stayed high across settlements -> not a NEW episode
    assert is_fresh_episode(0.02, 0.015, cfg.entry_threshold) is False

def test_fresh_when_no_prior_observation(cfg):
    # first time we ever see this symbol high -> treat as fresh
    assert is_fresh_episode(0.02, None, cfg.entry_threshold) is True

def test_not_fresh_when_current_below_threshold(cfg):
    assert is_fresh_episode(0.005, None, cfg.entry_threshold) is False


# --- passes_entry_filters ---------------------------------------------------

def test_passes_when_all_conditions_met(cfg):
    assert passes_entry_filters(make_snapshot(), cfg) is True

def test_rejects_rate_below_threshold(cfg):
    assert passes_entry_filters(make_snapshot(pred_rate=0.005), cfg) is False

def test_keeps_very_high_rate_no_upper_cap(cfg):
    # pred >= 2% is NOT excluded by a >=1% strategy (VERDICT nuance)
    assert passes_entry_filters(make_snapshot(pred_rate=0.05), cfg) is True

def test_rejects_negative_funding(cfg):
    # negative funding => we don't short; only positive (perp premium) qualifies
    assert passes_entry_filters(make_snapshot(pred_rate=-0.02), cfg) is False

def test_rejects_when_not_fresh(cfg):
    assert passes_entry_filters(make_snapshot(prev_pred_rate=0.015), cfg) is False

def test_rejects_young_token(cfg):
    assert passes_entry_filters(make_snapshot(listing_age_days=30.0), cfg) is False

def test_accepts_token_exactly_at_age_floor(cfg):
    assert passes_entry_filters(make_snapshot(listing_age_days=90.0), cfg) is True

def test_rejects_illiquid(cfg):
    assert passes_entry_filters(make_snapshot(liquidity_quote_vol_5m=100.0), cfg) is False

def test_accepts_liquidity_exactly_at_floor(cfg):
    assert passes_entry_filters(make_snapshot(liquidity_quote_vol_5m=500.0), cfg) is True


# --- evaluate_entries -------------------------------------------------------

def test_evaluate_returns_only_qualifying_symbols(cfg):
    snaps = [
        make_snapshot(symbol="GOOD_USDT"),
        make_snapshot(symbol="LOWRATE_USDT", pred_rate=0.004),
        make_snapshot(symbol="YOUNG_USDT", listing_age_days=10.0),
        make_snapshot(symbol="STALE_USDT", prev_pred_rate=0.02),
    ]
    signals = evaluate_entries(snaps, cfg)
    assert [s.symbol for s in signals] == ["GOOD_USDT"]
    assert signals[0].pred_rate == 0.02
    assert signals[0].mark_price == 1.0
