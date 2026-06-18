"""
P6 — JSON persistence of EngineState (open positions + episode memory).

Must survive restarts and degrade safely: a missing or corrupt file yields empty state
rather than crashing a live trader.
"""

from datetime import datetime, timezone

from strategy.engine import EngineState
from strategy.models import Position, PositionStatus
from runtime.state_store import load_state, save_state


def make_state():
    pos = Position(
        symbol="PUMP_USDT", side="SHORT", entry_price=1.23, volume=400.0,
        entry_time=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
        stop_price=1.44525, stop_order_id="abc-123", status=PositionStatus.OPEN,
    )
    return EngineState(positions={"PUMP_USDT": pos},
                       last_pred_rate={"PUMP_USDT": 0.02, "OTHER_USDT": 0.004})


def test_round_trip(tmp_path):
    path = tmp_path / "state.json"
    save_state(make_state(), path)
    loaded = load_state(path)

    assert loaded.last_pred_rate == {"PUMP_USDT": 0.02, "OTHER_USDT": 0.004}
    pos = loaded.positions["PUMP_USDT"]
    assert pos.symbol == "PUMP_USDT"
    assert pos.entry_price == 1.23
    assert pos.volume == 400.0
    assert pos.entry_time == datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    assert pos.stop_price == 1.44525
    assert pos.stop_order_id == "abc-123"
    assert pos.status == PositionStatus.OPEN


def test_missing_file_is_empty_state(tmp_path):
    state = load_state(tmp_path / "nope.json")
    assert state.positions == {}
    assert state.last_pred_rate == {}


def test_corrupt_file_is_empty_state(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    state = load_state(path)
    assert state.positions == {}
    assert state.last_pred_rate == {}


def test_save_is_atomic_no_partial_tmp_left(tmp_path):
    path = tmp_path / "state.json"
    save_state(make_state(), path)
    # no leftover temp files in the directory
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
