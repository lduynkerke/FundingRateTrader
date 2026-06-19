"""
Live market-order round-trip experiment (GATED, tiny size).

Measures real execution: submit/fill latency, slippage vs fair price, realized fees, and the
exact response shapes (so the adapter's fill mapping can be hardened). Opens a 1-contract
isolated short on a cheap, well-priced, tight-spread symbol, then immediately flattens and
verifies the account is flat.

SAFETY: places a REAL order. Runs only when MEXC_ALLOW_LIVE_ORDERS=1. Without it, dry-runs
(prints the plan and exits). Picks the cheapest symbol with price in [0.01, 100] and spread
< 15 bps unless a symbol is passed as argv[1].

Usage:
  python -m experiments.order_roundtrip                 # dry run (plan only)
  MEXC_ALLOW_LIVE_ORDERS=1 python -m experiments.order_roundtrip [SYMBOL]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from exchange.mexc import MexcError, MexcExchange
from exchange.mexc_data import MexcData
from experiments.metrics import slippage_bps
from experiments.selection import rank_affordable

LOG = Path(__file__).with_name("ORDER_ROUNDTRIP_LOG.md")


def _creds():
    cfg = yaml.safe_load(open(Path(__file__).resolve().parents[1] / "config.local.yaml"))
    return cfg["mexc_live"]


def pick_symbol(contracts, tickers, equity) -> dict:
    ranked = rank_affordable(contracts, tickers, budget=equity)
    good = [r for r in ranked if 0.01 <= r["price"] <= 100 and r["spread_bps"] < 15]
    return (good or ranked)[0]


def poll_until(fn, ok, timeout_s=10.0, interval_s=0.3):
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_s:
        val = fn()
        if ok(val):
            return val, (time.perf_counter() - start) * 1000
        time.sleep(interval_s)
    return fn(), (time.perf_counter() - start) * 1000


def run(symbol=None, hold_seconds: float = 0.0):
    c = _creds()
    ex = MexcExchange(c["api_key"], c["secret_key"], default_leverage=1)
    data = MexcData()
    equity = ex.get_equity()
    contracts = {x["symbol"]: x for x in data.list_contracts()}
    tickers = data.tickers()

    if symbol is None:
        chosen = pick_symbol(list(contracts.values()), tickers, equity)
        symbol = chosen["symbol"]
    tk = tickers[symbol]
    fair = float(tk.get("fairPrice", tk.get("lastPrice")))
    log = [f"# Order round-trip - {symbol}",
           f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
           f"- equity={equity} fair={fair} bid={tk.get('bid1')} ask={tk.get('ask1')} "
           f"contractSize={contracts[symbol]['contractSize']} minVol={contracts[symbol]['minVol']}\n"]

    if os.getenv("MEXC_ALLOW_LIVE_ORDERS") != "1":
        log.append("DRY RUN — set MEXC_ALLOW_LIVE_ORDERS=1 to place a real 1-contract order.")
        print("\n".join(log))
        return

    vol = float(contracts[symbol]["minVol"])
    try:
        # --- OPEN ---
        t0 = time.perf_counter()
        open_resp = ex._post("/api/v1/private/order/submit",
                             {"symbol": symbol, "vol": vol, "side": 3, "type": 5,
                              "openType": 1, "leverage": 1})
        ack_ms = (time.perf_counter() - t0) * 1000
        order_id = open_resp["data"]["orderId"] if isinstance(open_resp["data"], dict) else open_resp["data"]
        log.append(f"- OPEN ack {ack_ms:.0f} ms; submit raw: {json.dumps(open_resp)[:300]}")

        pos, fill_ms = poll_until(lambda: ex.get_positions(symbol),
                                  lambda p: any(float(x.get("holdVol", 0)) > 0 for x in p))
        order_detail = ex.get_order(order_id)
        log.append(f"- FILL after ~{fill_ms:.0f} ms; order raw: {json.dumps(order_detail)[:400]}")
        log.append(f"- positions raw: {json.dumps(pos)[:400]}")

        deal = float(order_detail.get("dealAvgPrice", 0) or 0)
        if deal:
            log.append(f"- OPEN slippage vs fair: {slippage_bps(deal, fair, 'sell'):.1f} bps "
                       f"(fill {deal} vs fair {fair})")

        # --- HOLD (let the position sit, e.g. 60s after fill) ---
        if hold_seconds > 0:
            log.append(f"- HOLD {hold_seconds:.0f}s after fill before flattening...")
            time.sleep(hold_seconds)

        # --- CLOSE (flatten) ---
        t1 = time.perf_counter()
        close_resp = ex.close(symbol)
        close_ms = (time.perf_counter() - t1) * 1000
        log.append(f"- CLOSE ack {close_ms:.0f} ms; fill: {close_resp}")

        flat, flat_ms = poll_until(lambda: ex.get_positions(symbol),
                                   lambda p: all(float(x.get("holdVol", 0)) == 0 for x in p))
        is_flat = all(float(x.get("holdVol", 0)) == 0 for x in flat)
        log.append(f"- FLAT after ~{flat_ms:.0f} ms: {is_flat}")
        if not is_flat:
            log.append("  !! NOT FLAT — manual check required: " + json.dumps(flat)[:300])
    except MexcError as e:
        log.append(f"- MEXC ERROR: code={e.code} msg={e.message} payload={json.dumps(e.payload)[:300]}")

    report = "\n".join(log)
    LOG.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote {LOG}")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else None
    hold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    run(sym, hold_seconds=hold)
