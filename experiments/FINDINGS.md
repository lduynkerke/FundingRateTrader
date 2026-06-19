# Execution Characterization — Findings (2026-06-18)

## RESOLVED (2026-06-19): the block was the `.com` edge WAF — use the `.co` mirror
MEXC support advised trying the backup API domain. `experiments/domain_probe.py` tested each
contract-API host with a private read + a NON-destructive invalid-symbol `order/submit`:
- `https://contract.mexc.com` — read OK; order/submit **HTML 403 (gateway block)**.
- `https://contract.mexc.co`  — read OK; order/submit returns JSON `code=1001 "Contract does not
  exist"` → **past the gateway, trading path OPEN**.
- `https://api.mexc.co`       — same as the `.co` mirror (past gateway).
So the 403 was an **edge-WAF quirk of the `.com` host on the trading path only**, not a key,
signing, account, or region policy. Fix: `MexcExchange` now defaults to `https://contract.mexc.co`.

### CONFIRMED live (2026-06-19): full round-trip on `.co` succeeded
`order_roundtrip.py FLOW_USDT 60` (open 1-contract isolated short, hold 60s, flatten) on the
`.co` host — clean end-to-end:
- OPEN: submit ack **420 ms**, market fill **~304 ms** later. `dealAvgPrice=0.02876` vs fair
  `0.02876` → **0.0 bps slippage** (filled right at the bid, spread was 1 tick / ~3.5 bps).
- FEE: `takerFee=2.3e-6 USDT` on `0.002876 USDT` notional ⇒ **~8 bps taker per side**, so
  **~16 bps round-trip taker** (corrects the earlier "~0.08% RT" estimate; still comfortably
  under the VERDICT's 0.30% cost assumption, so the edge survives net of fees).
- CLOSE: ack **733 ms**, position **flat in ~308 ms**, account confirmed flat. No residual.
- Order/position shapes match the adapter mapping (positionId, dealAvgPrice, holdVol, state=3).
**Live trading path is fully operational. L4 unblocked.**

### Pre-go-live dress rehearsal (2026-06-19, experiments/execution_dress_rehearsal.py)
Exercised EVERY call the live runtime makes, in order. All pass:
- **Reads:** list_contracts (~600 ms), usdt_perp_symbols (779), get_equity / list_open_symbols /
  get_positions (auth, ~300 ms each), build_snapshot (~600 ms).
- **Funding scan optimized:** run_cycle previously called `funding()` once per symbol →
  **~218 s/cycle serial** (779 calls). `contract/ticker` already carries `fundingRate` (== the
  per-symbol predicted rate) and `fairPrice`, so the new `MexcData.funding_all()` does the whole
  universe in **~150 ms (one call)**. run_cycle now uses it. Big latency + rate-limit risk removed.
- **Writes (first live test of place_stop + cancel_all):** open_short → place_stop (protective
  stop at entry×1.175, far above so it cannot fire) → **stop confirmed resting** (planorder list,
  states=1) → cancel_all → **0 active plan orders remain** → close → **flat**. Full executor path
  works live.
- **Plan-order states (verified):** `1`=untriggered/resting, `2`=cancelled, `3`=triggered. The
  list endpoint returns terminal states too, so count "resting" with `states=1` (a naive unfiltered
  count falsely flags cancelled orders as live — caught and fixed during the rehearsal).
- **Slippage (FLOW_USDT, 1 contract):** open vs fair ~**±3.5 bps** (≈1 tick on a 1-tick spread),
  close ~**+3.4–10 bps**. Taker fee **~8 bps/side**. So realistic **round-trip cost ~0.2%**,
  under the 0.30% VERDICT assumption. Latencies: open ~0.8 s, close ~1.0 s, both well within a
  funding-window cadence.
- **close() now reports the real fill price** (re-fetches the close order) so exit slippage/P&L is
  measurable; previously it returned avg_price=0.

### Go-live wiring
`main.build_exchange("live", ...)` now constructs `MexcExchange` on the `.co` host, but only when
`FRT_CONFIRM_LIVE=1` is set AND `mexc_live` credentials resolve — otherwise it refuses. Set
`runtime.mode: live` in config + `FRT_CONFIRM_LIVE=1` to go live. Account equity is **25 USDT**
(fund before meaningful trading).

Everything below is the original 2026-06-18 diagnosis, kept for the record.

---

## Headline: MEXC blocks futures *order placement* via API on this account
- **Read endpoints work** through the live key + current network: `account/assets` (25 USDT),
  `position/open_positions`, `order/list/open_orders/{sym}`, `planorder/list/orders` all return
  `code:0`. Signing (`accessKey+reqTime+param`, HMAC-SHA256) is correct — verified live.
- **`POST /api/v1/private/order/submit` returns HTTP 403** — an **edge-gateway HTML "Access
  Denied"** page ("You don't have permission to access .../order/submit on this server",
  Akamai-style reference id), NOT a MEXC JSON error. So it is **not** a signature error
  (that returns JSON `code 602/700`) and **not** a per-order rejection — the trading path is
  forbidden at the gateway.
- Diagnosis: this is MEXC's well-known policy — **contract/futures API order placement is gated**
  (approved market-makers/brokers only); ordinary keys are effectively read-only for futures.
  Reads pass the same proxy/IP, so it is path/permission-specific, not a blanket IP block.
- **Retested 2026-06-19 with a second, freshly-created key on the same account/network: identical
  403.** This rules out key-level causes (permissions/whitelist) and signing — the block is at the
  **account/region/gateway level on the trading path** (Akamai WAF "Reference #18..." on
  /order/submit only). Most consistent with a geo/region trading restriction hitting the egress IP
  (this shell is behind a TLS-intercepting proxy) and/or the account not being futures-API approved.
- **Retested from the user's DIRECT network (no proxy): still 403**, and the Akamai edge token
  (`#18.8c8e1002...`) matched the sandbox runs (same geo-routing). This rules out the proxy and
  points to a **region/account-level MEXC policy** refusing futures-API `order/submit` here while
  permitting all reads. Not fixable in code — path forward is MEXC-side or manual-assisted exec.

## What this means
The S1-Episode logic, paper engine, signer, and read adapters are all correct and live-verified,
but **the strategy cannot place orders through MEXC's REST contract API on this account as-is.**
Live trading is blocked at L4 until order placement is unblocked.

## To verify / try (user side, in order)
1. **MEXC key permissions:** confirm the API key has **Futures/Contract Trading** permission
   enabled and **IP whitelisting** set to the machine's egress IP (web UI > API management).
   If "Futures trading" isn't an available scope, the account isn't approved for API futures.
2. **Network/region:** retry `order/submit` from the **normal network without the TLS-intercepting
   proxy** (and from the account's home jurisdiction). MEXC geofences *trading* endpoints; the
   proxy egress IP or region may be the trigger even though reads are allowed.
3. **Apply for API futures access:** MEXC requires application/approval (market-maker/broker
   program) for contract order API. Check current eligibility.
4. **If MEXC stays closed:** options are (a) **manual/assisted execution** — the bot computes the
   exact orders (entry, stop, exit) and emits them for one-click manual placement in the MEXC UI;
   (b) **WebSocket/private order channel** if a different auth path is permitted; (c) port execution
   to an exchange with open futures API (Bybit/Binance/OKX) — but the *signal universe* is
   MEXC-specific microcaps, so the tradable set shrinks to names co-listed there. Re-validate.

## Other live facts captured (useful regardless)
- Fees this tier: taker as low as **2 bps**, round-trip taker ~**0.08%** (VERDICT assumed 0.30%).
- 779 API-flagged USDT perps; 774 have a 1-contract notional under 25 USDT (many sub-cent).
- Auth read latency ~800 ms via the proxy (measure again on the direct network).
- `contract/ticker` (one call, ~917 rows) gives bid1/ask1/fairPrice — good for spread + reference.
