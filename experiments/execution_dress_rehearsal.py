"""
Pre-go-live execution dress rehearsal.

Exercises EVERY MEXC call the live strategy makes, in the exact order the runtime makes them,
so nothing surprises us in production. Three parts:

  A. READ PATH (no orders, always runs) — the per-cycle reads run_cycle/executor perform:
     list_contracts, usdt_perp_symbols, get_equity, list_open_symbols, get_positions,
     build_snapshot, and a timed funding() burst (run_cycle calls funding() once PER symbol,
     so the whole-universe scan cost + any rate-limiting is measured and extrapolated).

  B. WRITE LIFECYCLE (real orders, gated by MEXC_ALLOW_LIVE_ORDERS=1) — the full executor path:
     open_short -> place_stop (at the real S1 stop = entry*(1+stop_pct), far above so it can
     NEVER trigger) -> verify the stop is resting (planorder list) -> reconcile reads
     (get_positions/list_open_symbols/get_order) -> cancel_all (verify stop gone) -> close
     (verify flat). This is the first live test of place_stop and cancel_all.

  C. SLIPPAGE SAMPLE (real orders, gated) — N quick open/close cycles to sample the slippage
     distribution and per-call latency, summarized.

Usage:
  python -m experiments.execution_dress_rehearsal               # READ PATH only (safe)
  MEXC_ALLOW_LIVE_ORDERS=1 python -m experiments.execution_dress_rehearsal [SYMBOL] [N_SAMPLES]
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
from experiments.metrics import slippage_bps, summarize_latencies
from experiments.selection import rank_affordable
from strategy.config import StrategyConfig
from strategy.exits import short_stop_price

REPORT = Path(__file__).with_name("DRESS_REHEARSAL_REPORT.md")
FUNDING_BURST = 40  # symbols to sample for the per-cycle funding-scan timing


def _creds():
    cfg = yaml.safe_load(open(Path(__file__).resolve().parents[1] / "config.local.yaml"))
    return cfg["mexc_live"]


def _timed(fn):
    t0 = time.perf_counter()
    val = fn()
    return val, (time.perf_counter() - t0) * 1000


def pick_symbol(contracts, tickers, equity) -> dict:
    ranked = rank_affordable(list(contracts.values()), tickers, budget=equity)
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


def list_plan_orders(ex, symbol):
    """ACTIVE (untriggered) trigger orders for a symbol.

    Plan-order states (verified live): 1=untriggered/resting, 2=cancelled, 3=triggered/executed.
    The list endpoint returns terminal states too, so we filter to states=1 — only those are
    genuinely "resting" and would still fire.
    """
    return ex._get("/api/v1/private/planorder/list/orders",
                   {"symbol": symbol, "states": "1", "page_num": 1, "page_size": 20}
                   ).get("data", []) or []


# ---------------- A. READ PATH ----------------
def read_path(ex, data, log):
    log.append("## A. Read path (per-cycle reads, no orders)")

    contracts_list, ms = _timed(data.list_contracts)
    contracts = {c["symbol"]: c for c in contracts_list}
    log.append(f"- list_contracts: {len(contracts)} contracts in {ms:.0f} ms")

    symbols, ms = _timed(data.usdt_perp_symbols)
    log.append(f"- usdt_perp_symbols: {len(symbols)} tradable in {ms:.0f} ms")

    equity, ms = _timed(ex.get_equity)
    log.append(f"- get_equity (auth): {equity} USDT in {ms:.0f} ms")
    held, ms = _timed(ex.list_open_symbols)
    log.append(f"- list_open_symbols (auth): {held} in {ms:.0f} ms")
    positions, ms = _timed(ex.get_positions)
    log.append(f"- get_positions (auth): {len(positions)} open in {ms:.0f} ms")

    # funding scan: the runtime now uses ONE bulk ticker call (funding_all) for the whole
    # universe. Compare it against the old per-symbol funding() to show the speedup.
    fa, fa_ms = _timed(data.funding_all)
    log.append(f"- funding_all (bulk, the live path): {len(fa)} symbols in **{fa_ms:.0f} ms/cycle**")
    sample = symbols[:FUNDING_BURST]
    lat, errors = [], 0
    for sym in sample:
        try:
            _, ms = _timed(lambda: data.funding(sym))
            lat.append(ms)
        except Exception as e:  # noqa: BLE001 — want to detect rate-limit/network surprises
            errors += 1
            log.append(f"  !! funding({sym}) failed: {type(e).__name__}: {str(e)[:80]}")
    stats = summarize_latencies(lat)
    old_est_s = (stats["median"] or 0) * len(symbols) / 1000.0
    log.append(f"- (old per-symbol funding() for reference: med={stats['median']:.0f} ms/call "
               f"-> ~{old_est_s:.0f}s serial; replaced by the single bulk call above)")

    # build_snapshot for one candidate (klines + funding + meta)
    chosen = pick_symbol(contracts, data.tickers(), equity)["symbol"]
    snap, ms = _timed(lambda: data.build_snapshot(chosen, contracts[chosen]))
    log.append(f"- build_snapshot({chosen}): pred_rate={snap.pred_rate} "
               f"age={snap.listing_age_days:.0f}d liq={snap.liquidity_quote_vol_5m:.0f} in {ms:.0f} ms")
    log.append("")
    return contracts, equity


# ---------------- B. WRITE LIFECYCLE ----------------
def write_lifecycle(ex, data, contracts, equity, symbol, stop_pct, log):
    log.append("## B. Write lifecycle (full executor path, real orders)")
    tickers = data.tickers()
    if symbol is None:
        symbol = pick_symbol(contracts, tickers, equity)["symbol"]
    tk = tickers[symbol]
    fair = float(tk.get("fairPrice", tk.get("lastPrice")))
    vol = float(contracts[symbol]["minVol"])
    log.append(f"- symbol={symbol} fair={fair} bid={tk.get('bid1')} ask={tk.get('ask1')} "
               f"vol={vol} contractSize={contracts[symbol]['contractSize']}")

    # 1) OPEN SHORT
    (fill, ms) = _timed(lambda: ex.open_short(symbol, vol))
    log.append(f"- open_short: fill={fill.avg_price} vol={fill.volume} in {ms:.0f} ms; "
               f"slippage={slippage_bps(fill.avg_price, fair, 'sell'):.1f} bps")

    # 2) PLACE STOP (real S1 stop, far above -> cannot trigger)
    stop_price = short_stop_price(fill.avg_price, stop_pct)
    (stop_id, ms) = _timed(lambda: ex.place_stop(symbol, vol, stop_price))
    log.append(f"- place_stop @ {stop_price:.6g} ({stop_pct*100:.0f}% above {fill.avg_price}): "
               f"id={stop_id} in {ms:.0f} ms  [FIRST LIVE TEST]")

    # 3) VERIFY the stop is resting
    try:
        plans, ms = _timed(lambda: list_plan_orders(ex, symbol))
        ids = [str(p.get("id") or p.get("orderId")) for p in plans]
        log.append(f"- planorder list: {len(plans)} resting {ids} in {ms:.0f} ms; "
                   f"stop present={str(stop_id) in ids}")
    except MexcError as e:
        log.append(f"- planorder list: ERROR code={e.code} msg={str(e.message)[:100]}")

    # 4) RECONCILE reads (what the scheduler/executor read each cycle)
    held = ex.list_open_symbols()
    detail = ex.get_order(fill.order_id)
    log.append(f"- list_open_symbols held={held}; open order state={detail.get('state')} "
               f"takerFee={detail.get('takerFee')} feeCur={detail.get('feeCurrency')}")

    # 5) CANCEL ALL (cancels the resting stop) -> verify gone  [FIRST LIVE TEST]
    _, ms = _timed(lambda: ex.cancel_all(symbol))
    try:
        plans_after = list_plan_orders(ex, symbol)
        log.append(f"- cancel_all in {ms:.0f} ms; resting plan orders after={len(plans_after)} "
                   f"(expect 0)  [FIRST LIVE TEST]")
    except MexcError as e:
        log.append(f"- cancel_all in {ms:.0f} ms; planorder re-list ERROR {e.code}")

    # 6) CLOSE -> verify flat
    fair_close = float(data.tickers()[symbol].get("fairPrice", fair))
    (cfill, ms) = _timed(lambda: ex.close(symbol))
    log.append(f"- close: fill={cfill.avg_price} vol={cfill.volume} in {ms:.0f} ms; "
               f"slippage={slippage_bps(cfill.avg_price, fair_close, 'buy'):.1f} bps")
    flat, fms = poll_until(lambda: ex.get_positions(symbol),
                           lambda p: all(float(x.get("holdVol", 0)) == 0 for x in p))
    is_flat = all(float(x.get("holdVol", 0)) == 0 for x in flat)
    log.append(f"- FLAT after ~{fms:.0f} ms: {is_flat}")
    if not is_flat:
        log.append("  !! NOT FLAT — manual check: " + json.dumps(flat)[:200])
    log.append("")
    return symbol


# ---------------- C. SLIPPAGE SAMPLE ----------------
def slippage_sample(ex, data, contracts, symbol, n, log):
    log.append(f"## C. Slippage / latency sample ({n} open+close cycles on {symbol})")
    vol = float(contracts[symbol]["minVol"])
    open_slip, close_slip, open_ms, close_ms = [], [], [], []
    for i in range(n):
        fair = float(data.tickers()[symbol].get("fairPrice"))
        f, ms = _timed(lambda: ex.open_short(symbol, vol)); open_ms.append(ms)
        if f.avg_price:
            open_slip.append(slippage_bps(f.avg_price, fair, "sell"))
        poll_until(lambda: ex.get_positions(symbol),
                   lambda p: any(float(x.get("holdVol", 0)) > 0 for x in p))
        fair_c = float(data.tickers()[symbol].get("fairPrice"))
        cf, ms = _timed(lambda: ex.close(symbol)); close_ms.append(ms)
        if cf.avg_price:
            close_slip.append(slippage_bps(cf.avg_price, fair_c, "buy"))
        poll_until(lambda: ex.get_positions(symbol),
                   lambda p: all(float(x.get("holdVol", 0)) == 0 for x in p))
        log.append(f"  cycle {i+1}: open_slip={open_slip[-1] if open_slip else 'NA'} "
                   f"close_slip={close_slip[-1] if close_slip else 'NA'} bps")
    def fmt(xs):
        return ("n/a" if not xs else
                f"min={min(xs):.1f} med={sorted(xs)[len(xs)//2]:.1f} max={max(xs):.1f}")
    log.append(f"- OPEN  slippage bps: {fmt(open_slip)} | latency {summarize_latencies(open_ms)}")
    log.append(f"- CLOSE slippage bps: {fmt(close_slip)} | latency {summarize_latencies(close_ms)}")
    log.append("")


def run(symbol=None, n_samples=2):
    c = _creds()
    ex = MexcExchange(c["api_key"], c["secret_key"], default_leverage=1)
    data = MexcData()
    cfg = StrategyConfig()
    log = [f"# Execution Dress Rehearsal", f"_Generated {datetime.now(timezone.utc).isoformat()}_",
           f"_base={ex._base} stop_pct={cfg.stop_pct}_\n"]

    contracts, equity = read_path(ex, data, log)

    if os.getenv("MEXC_ALLOW_LIVE_ORDERS") == "1":
        chosen = write_lifecycle(ex, data, contracts, equity, symbol, cfg.stop_pct, log)
        if n_samples > 0:
            slippage_sample(ex, data, contracts, chosen, n_samples, log)
    else:
        log.append("## B/C skipped — set MEXC_ALLOW_LIVE_ORDERS=1 to run the real-order parts.\n")

    report = "\n".join(log)
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else None
    ns = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    run(sym, ns)
