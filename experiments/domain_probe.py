"""
Backup-domain gateway probe (NON-DESTRUCTIVE).

MEXC support advised: try the backup API domain `api.mexc.co`, then retry; if it still fails,
try a different egress IP (ideally Singapore). This script tests each candidate contract-API
host for two things, WITHOUT placing any real order:

  1. private READ  — GET /api/v1/private/account/assets (confirms the host serves the signed
     contract API and our auth is accepted there).
  2. trading-path  — POST /api/v1/private/order/submit with a DELIBERATELY INVALID symbol.
     * HTML "Access Denied" / HTTP 403  -> gateway still blocks the trading path on this host.
     * JSON `code != 0` (e.g. contract-not-exist) -> we got PAST the gateway; the block is lifted
       and a real order would be accepted. (The bad symbol guarantees nothing is ever filled.)

Usage:  python -m experiments.domain_probe
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from exchange.mexc import MexcError, MexcExchange
from utils.config_loader import load_live_creds

# Candidate contract-API hosts to try, in MEXC-support's suggested order.
CANDIDATES = [
    "https://contract.mexc.com",  # current (known 403 on order/submit)
    "https://contract.mexc.co",   # backup TLD mirror for the contract API
    "https://api.mexc.co",        # the literal domain MEXC support named
]

BAD_SYMBOL = "ZZ_NONEXISTENT_USDT"  # guarantees the order can never fill
LOG = Path(__file__).with_name("DOMAIN_PROBE_LOG.md")


def _creds() -> dict:
    return load_live_creds()


def _classify_order_path(ex: MexcExchange) -> str:
    """Send an invalid order; return a human verdict on the trading path."""
    try:
        resp = ex._post("/api/v1/private/order/submit", {
            "symbol": BAD_SYMBOL, "vol": 1, "side": 3, "type": 5,
            "openType": 1, "leverage": 1,
        })
        return f"PAST GATEWAY (unexpected success): {json.dumps(resp)[:200]}"
    except MexcError as e:
        msg = str(e.message or "")
        if e.code == 403 or "Access Denied" in msg or "<html" in msg.lower():
            return f"GATEWAY BLOCK (403) — trading path still forbidden. {msg[:160]}"
        return f"PAST GATEWAY — JSON rejection code={e.code} msg={msg[:160]} (trading path OPEN)"
    except Exception as e:  # network/DNS/TLS error reaching this host
        return f"UNREACHABLE: {type(e).__name__}: {str(e)[:160]}"


def run() -> None:
    c = _creds()
    out = [f"# Backup-domain gateway probe",
           f"_Generated {datetime.now(timezone.utc).isoformat()}_\n",
           "Tests each host for a private read + a non-destructive invalid-symbol order/submit.\n"]

    for base in CANDIDATES:
        out.append(f"## {base}")
        ex = MexcExchange(c["api_key"], c["secret_key"], base_url=base, default_leverage=1)
        # 1) private read
        t0 = time.perf_counter()
        try:
            eq = ex.get_equity()
            read_ms = (time.perf_counter() - t0) * 1000
            out.append(f"- READ account/assets: OK equity={eq} USDT ({read_ms:.0f} ms)")
        except MexcError as e:
            out.append(f"- READ account/assets: MexcError code={e.code} msg={str(e.message)[:160]}")
        except Exception as e:
            out.append(f"- READ account/assets: UNREACHABLE {type(e).__name__}: {str(e)[:160]}")
            out.append("")
            continue  # if the host won't even serve a read, skip the order probe
        # 2) trading-path classification
        out.append(f"- ORDER PATH: {_classify_order_path(ex)}")
        out.append("")

    report = "\n".join(out)
    LOG.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote {LOG}")


if __name__ == "__main__":
    run()
