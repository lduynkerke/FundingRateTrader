"""
P7b — PaperExchange: deterministic simulated fills, resting stop triggers, equity accounting.
"""

import pytest

from exchange.paper import PaperExchange


def test_open_short_records_position_and_charges_fee():
    ex = PaperExchange(equity=10_000.0, prices={"PUMP_USDT": 1.0}, fee_round_trip=0.003)
    fill = ex.open_short("PUMP_USDT", 500.0)
    assert fill.avg_price == 1.0
    assert ex.list_open_symbols() == {"PUMP_USDT"}
    # half of 0.30% round-trip charged on entry: 1.0*500*0.0015 = 0.75
    assert ex.get_equity() == pytest.approx(9_999.25)


def test_close_realizes_short_pnl():
    ex = PaperExchange(equity=10_000.0, prices={"PUMP_USDT": 1.0}, fee_round_trip=0.003)
    ex.open_short("PUMP_USDT", 500.0)
    ex.set_price("PUMP_USDT", 0.90)
    ex.close("PUMP_USDT")
    # gross short pnl (1.0-0.9)*500 = 50 ; minus entry fee .75 and exit fee .9*500*.0015=.675
    assert ex.get_equity() == pytest.approx(10_000.0 + 50 - 0.75 - 0.675)
    assert ex.list_open_symbols() == set()


def test_resting_stop_triggers_on_adverse_move():
    ex = PaperExchange(equity=10_000.0, prices={"PUMP_USDT": 1.0}, fee_round_trip=0.0)
    ex.open_short("PUMP_USDT", 500.0)
    ex.place_stop("PUMP_USDT", 500.0, stop_price=1.175)
    ex.set_price("PUMP_USDT", 1.20)  # gaps through the stop
    # filled at the stop price (stop-market), position gone
    assert ex.list_open_symbols() == set()
    assert ex.get_equity() == pytest.approx(10_000.0 + (1.0 - 1.175) * 500.0)


def test_funding_credit_for_short():
    ex = PaperExchange(equity=10_000.0, prices={"PUMP_USDT": 1.0}, fee_round_trip=0.0)
    ex.open_short("PUMP_USDT", 500.0)
    ex.apply_funding("PUMP_USDT", rate=0.02)  # short receives positive funding
    assert ex.get_equity() == pytest.approx(10_000.0 + 0.02 * 1.0 * 500.0)
