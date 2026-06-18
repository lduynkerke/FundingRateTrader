"""
JSON persistence for EngineState.

Atomic writes (temp file + os.replace) so a crash mid-write never corrupts the live
state; loads degrade to empty state on missing/corrupt files so the trader can restart
cleanly rather than die holding stale beliefs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Union

from strategy.engine import EngineState
from strategy.models import Position, PositionStatus


def _position_to_dict(p: Position) -> dict:
    return {
        "symbol": p.symbol,
        "side": p.side,
        "entry_price": p.entry_price,
        "volume": p.volume,
        "entry_time": p.entry_time.isoformat(),
        "stop_price": p.stop_price,
        "stop_order_id": p.stop_order_id,
        "status": p.status.value,
    }


def _position_from_dict(d: dict) -> Position:
    return Position(
        symbol=d["symbol"],
        side=d["side"],
        entry_price=d["entry_price"],
        volume=d["volume"],
        entry_time=datetime.fromisoformat(d["entry_time"]),
        stop_price=d["stop_price"],
        stop_order_id=d.get("stop_order_id"),
        status=PositionStatus(d.get("status", "OPEN")),
    )


def save_state(state: EngineState, path: Union[str, Path]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "positions": {s: _position_to_dict(p) for s, p in state.positions.items()},
        "last_pred_rate": state.last_pred_rate,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


def load_state(path: Union[str, Path]) -> EngineState:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        positions = {s: _position_from_dict(d) for s, d in payload["positions"].items()}
        return EngineState(positions=positions, last_pred_rate=payload["last_pred_rate"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return EngineState()
