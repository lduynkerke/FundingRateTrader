"""
Read-only live characterization of the MEXC account + contract universe.

Safe: performs NO order placement. Produces facts the strategy/runtime need — account equity
and position mode, fee tier, and the cheapest API-tradable symbols (for later tiny order
experiments) — and writes them to experiments/EXECUTION_REPORT.md.

Usage:  python -m experiments.characterize
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from exchange.mexc import MexcError, MexcExchange
from exchange.mexc_data import MexcData
from experiments.selection import rank_affordable

REPORT = Path(__file__).with_name("EXECUTION_REPORT.md")


def _creds():
    cfg = yaml.safe_load(open(Path(__file__).resolve().parents[1] / "config.local.yaml"))
    return cfg["mexc_live"]


def run() -> str:
    c = _creds()
    ex = MexcExchange(c["api_key"], c["secret_key"])
    data = MexcData()
    lines = [f"# MEXC Execution Characterization (read-only)\n",
             f"_Generated {datetime.now(timezone.utc).isoformat()}_\n"]

    # --- account ---
    t0 = time.perf_counter()
    equity = ex.get_equity()
    auth_ms = (time.perf_counter() - t0) * 1000
    positions = ex.get_positions()
    lines += [
        "## Account",
        f"- USDT equity: **{equity}**",
        f"- Open positions: {len(positions)}",
        f"- Auth read latency: {auth_ms:.0f} ms",
        "",
    ]

    # --- universe + fees + affordability ---
    contracts = data.list_contracts()
    tickers = data.tickers()
    usdt = [c for c in contracts if c.get("quoteCoin") == "USDT"]
    api_ok = [c for c in usdt if c.get("apiAllowed") and c.get("state") == 0]
    taker = sorted({c.get("takerFeeRate") for c in api_ok if c.get("takerFeeRate") is not None})
    maker = sorted({c.get("makerFeeRate") for c in api_ok if c.get("makerFeeRate") is not None})
    rt = 2 * max(taker) * 100 if taker else 0.0
    lines += [
        "## Universe",
        f"- USDT perps: {len(usdt)}; API-tradable & enabled: {len(api_ok)}",
        f"- Taker fee rates seen: {taker}  | Maker: {maker}",
        f"- Round-trip taker cost ~ {rt:.3f}% (VERDICT assumed 0.30%)",
        "",
    ]

    ranked = rank_affordable(contracts, tickers, budget=equity)
    lines += [f"## Cheapest API-tradable symbols (1-contract notional &lt;= {equity} USDT)",
              "| symbol | price | 1c notional $ | spread bps | taker bps |",
              "|---|---|---|---|---|"]
    for r in ranked[:15]:
        lines.append(f"| {r['symbol']} | {r['price']:g} | {r['notional_1c']:.3f} | "
                     f"{r['spread_bps']:.0f} | {r['taker_fee_bps']:.0f} |")
    if not ranked:
        lines.append("| (none fit the budget) | | | | |")
    lines += ["", f"_{len(ranked)} symbols fit a single contract within {equity} USDT._", ""]

    report = "\n".join(lines)
    REPORT.write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    try:
        print(run())
        print(f"\nWrote {REPORT}")
    except MexcError as e:
        print(f"MEXC error: {e}")
