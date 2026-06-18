# Live Execution Build + API Characterization Plan

Builds the real `MexcExchange` (private contract trading) behind the existing `Exchange`
protocol, plus an **execution-characterization harness** that empirically measures the live
API (latency, slippage, fill quality, limits, account mode) before we trust it with the
strategy. Red-green-refactor TDD; live order calls are gated behind explicit opt-in + tiny size.

Paper mode (already shipped) keeps running independently — this work only adds the `live` path.

## Verified MEXC contract facts (official docs, 2026-06-18)
- **Signing:** `signString = accessKey + requestTime(ms) + paramString`,
  `signature = HMAC_SHA256(secretKey, signString)` hex.
  - GET/DELETE: params **sorted alphabetically**, `k=v` joined by `&`, URL-encoded.
  - POST: the **exact JSON body string** (no sorting).
  - Headers: `ApiKey`, `Request-Time`(ms), `Signature`, `Content-Type: application/json`,
    optional `Recv-Window`.
  - The repo's `api/base_client._sign_request` is WRONG (signs `ts+METHOD+endpoint+params`) —
    do not reuse it; new clean signer instead.
- **Order codes:** side 1=open long, 2=close short, 3=open short, 4=close long.
  type 1=limit,2=post-only,3=IOC,4=FOK,5=market. openType 1=isolated,2=cross.
  positionMode 1=hedge,2=one-way.
- **Endpoints:** assets `GET /private/account/assets`; positions `GET /private/position/open_positions`;
  submit `POST /private/order/submit`; cancel `POST /private/order/cancel` (JSON array of orderIds,
  ≤50); cancel-all `POST /private/order/cancel_all` (optional symbol); open orders
  `GET /private/order/list/open_orders/{symbol}`; change leverage `POST /private/position/change_leverage`;
  **trigger/stop** `POST /private/planorder/place` (fields: symbol, vol, leverage, side, openType,
  triggerPrice, triggerType[1=≥,2=≤], executeCycle[1=24h,2=7d], orderType[5=market],
  trend[1=last,2=fair,3=index], reduceOnly); plan cancel `POST /private/planorder/cancel` / `cancel_all`.
- Response shape: `{success, code, data}`; success when `code == 0`.

**S1 mappings:** open short = submit side=3,type=5,openType=1,leverage. Protective stop = planorder
side=2 (close short), triggerType=1 (price ≥ trigger), orderType=5 (market), trend=2 (fair),
executeCycle=2 (7d > our 24h cap), vol=position vol. Close = submit side=2,type=5 (+positionId in
hedge mode, or reduceOnly in one-way — the harness determines which the account uses).

## TDD phases
- **L1 — signer** (`exchange/mexc_signing.py`): `param_string_get(params)`, `body_string(obj)`,
  `sign(access, secret, ts_ms, param_string)`, `auth_headers(...)`. Pinned against precomputed
  HMAC vectors so the exact signed bytes can't silently drift.
- **L2 — MexcExchange** (`exchange/mexc.py`): implements the `Exchange` protocol (get_equity,
  list_open_symbols, open_short, place_stop, close, cancel_all) + set_leverage/get_positions.
  Injected HTTP transport + clock; tests assert URL, signed headers, GET param string, POST body,
  and response→domain mapping. No network in tests. Raises on `code != 0`.
- **L3 — characterization harness** (`experiments/`):
  - pure metrics (`metrics.py`): slippage vs reference price, latency stats (submit→ack→fill),
    fee bps, fill-ratio — TDD'd.
  - `probes.py` experiment definitions + a runner that writes `EXECUTION_REPORT.md` + raw JSON.
  - **read-only** probes (safe, no opt-in): auth canary, balance, positions, open orders, account
    position-mode, per-symbol capabilities (apiAllowed, minVol, contractSize, maker/taker fee,
    maxLeverage), funding/settle timing.
  - **live-order** probes (require `--live-orders` flag + `MEXC_ALLOW_LIVE_ORDERS=1`, tiny vol):
    1. market open+close round-trip → submit/ack/fill latency, slippage vs fair price, realized fee;
    2. limit place→cancel latency, partial-fill behaviour;
    3. planorder (stop-market) place→trigger→fill quality + latency at a near trigger;
    4. position lifecycle incl. how closing works (positionId vs reduceOnly) → resolves account mode;
    5. rate-limit probing (burst until 429/510) to set safe concurrency/backoff.
  Goal artifact: `experiments/EXECUTION_REPORT.md` — opportunities & limitations feeding sizing,
  stop-fill assumptions (VERDICT says next-bar fills halve the edge — measure the real number),
  and the runtime's order/backoff policy.
- **L4 — wire live** into `main.py`/`build_exchange` once L3 read-only canary + tiny-order probes
  pass; flip `runtime.mode: live` only after the PLAN.md §3 gates.

## Safety rails
- Live orders never run without BOTH `--live-orders` and `MEXC_ALLOW_LIVE_ORDERS=1`.
- Experiments use the exchange minimum volume and immediately flatten; every order tagged with an
  `externalOid` prefix for audit.
- Key loaded only from env / config.local.yaml. Rotate the previously-committed key first.
