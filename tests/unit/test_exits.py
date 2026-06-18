"""
P3 — exit logic: rate-normalization, 24h time cap, and the short stop price.

The hard stop itself rests on the exchange (stop-market); should_exit covers the two
engine-driven exits. Precedence when several fire at once: normalization (mechanism) over
the time cap (backstop).
"""

from datetime import datetime, timedelta, timezone

import pytest

from strategy.config import StrategyConfig
from strategy.exits import short_stop_price, should_exit
from strategy.models import ExitReason, Position, PositionStatus


@pytest.fixture
def cfg():
    return StrategyConfig()


def make_position(entry_time):
    return Position(
        symbol="PUMP_USDT",
        side="SHORT",
        entry_price=1.0,
        volume=100.0,
        entry_time=entry_time,
        stop_price=1.175,
    )


def test_short_stop_price(cfg):
    assert short_stop_price(1.0, cfg.stop_pct) == pytest.approx(1.175)
    assert short_stop_price(200.0, 0.15) == pytest.approx(230.0)


def test_no_exit_while_episode_persists(cfg):
    now = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
    pos = make_position(now - timedelta(hours=8))
    assert should_exit(pos, latest_pred_rate=0.015, now=now, cfg=cfg) is None


def test_no_exit_when_no_new_observation_yet(cfg):
    now = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
    pos = make_position(now - timedelta(hours=2))
    assert should_exit(pos, latest_pred_rate=None, now=now, cfg=cfg) is None


def test_exit_on_rate_normalized(cfg):
    now = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
    pos = make_position(now - timedelta(hours=8))
    assert should_exit(pos, latest_pred_rate=0.0005, now=now, cfg=cfg) == ExitReason.NORMALIZED


def test_exit_on_sign_flip(cfg):
    now = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
    pos = make_position(now - timedelta(hours=8))
    assert should_exit(pos, latest_pred_rate=-0.02, now=now, cfg=cfg) == ExitReason.NORMALIZED


def test_exit_on_time_cap(cfg):
    now = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
    pos = make_position(now - timedelta(hours=24))
    # rate still elevated but 24h elapsed -> backstop
    assert should_exit(pos, latest_pred_rate=0.02, now=now, cfg=cfg) == ExitReason.TIME_CAP


def test_normalization_takes_precedence_over_time_cap(cfg):
    now = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
    pos = make_position(now - timedelta(hours=25))
    assert should_exit(pos, latest_pred_rate=0.0, now=now, cfg=cfg) == ExitReason.NORMALIZED
