"""
P2 — position sizing: 5% equity notional -> contract volume with exchange rounding.
"""

import pytest

from strategy.config import StrategyConfig
from strategy.sizing import target_notional, notional_to_volume


@pytest.fixture
def cfg():
    return StrategyConfig()


def test_target_notional_is_equity_fraction(cfg):
    assert target_notional(10_000.0, cfg) == pytest.approx(500.0)


def test_volume_basic_integer_contracts():
    # $500 notional, price $1, contract_size 1 -> 500 contracts; vol_scale 0 -> integer
    vol = notional_to_volume(500.0, price=1.0, contract_size=1.0, vol_scale=0, min_volume=1.0)
    assert vol == 500.0


def test_volume_accounts_for_contract_size():
    # contract_size 10 base units => each contract is worth $10 at price $1
    vol = notional_to_volume(500.0, price=1.0, contract_size=10.0, vol_scale=0, min_volume=1.0)
    assert vol == 50.0


def test_volume_rounds_down_to_scale():
    # 500 / (3 * 1) = 166.66.. ; vol_scale 0 floors to 166 (never overshoot notional)
    vol = notional_to_volume(500.0, price=3.0, contract_size=1.0, vol_scale=0, min_volume=1.0)
    assert vol == 166.0


def test_volume_respects_fractional_scale():
    # price 30000, contract_size 0.0001 (BTC-like) -> 500/(30000*0.0001)=166.66.. contracts
    vol = notional_to_volume(500.0, price=30000.0, contract_size=0.0001, vol_scale=2, min_volume=0.01)
    assert vol == pytest.approx(166.66)


def test_rejects_when_below_min_volume():
    # rounds down to below exchange minimum -> 0 (cannot trade this name at this size)
    vol = notional_to_volume(5.0, price=1.0, contract_size=10.0, vol_scale=0, min_volume=1.0)
    assert vol == 0.0


def test_rejects_on_nonpositive_price():
    assert notional_to_volume(500.0, price=0.0, contract_size=1.0, vol_scale=0, min_volume=1.0) == 0.0
