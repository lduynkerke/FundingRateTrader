# FundingRateTrader — Live S1-Episode Build Plan

**Strategy:** S1-Episode (MEXC extreme-positive-funding short), the *conditional GO*
variant from `tradingProject/Research/mexc_funding/backtest/VERDICT.md`.
**Build style:** red-green TDD. Pure decision core (no I/O) is unit-tested; exchange I/O
is behind an interface with a paper (simulated) implementation that is the **default**.
**Live trading is OFF until paper-mode and a live read-only API canary both pass.**

---
## BUILD STATUS (2026-06-17)
- **DONE (64 tests green, runs live in paper mode):** P0 secrets→env/config.local (gitignored;
  **rotate the old key**), P1 signals, P2 sizing, P3 exits, P4 portfolio, P5 engine.step,
  P6 state store, P7 paper exchange + e2e loop, P8a MEXC public data adapter (shapes verified
  vs live API), P9 scheduler `run_cycle`/`run_forever`, `main.py` (paper default). `python main.py`
  runs a real-data paper trader now.
- **REMAINING:** P8b live trading adapter (`MexcExchange`: corrected contract signing + market /
  stop-market / cancel / assets / positions) — needs live account to verify; then the §3 go-live
  gates. `main.py` mode="live" raises NotImplementedError until then.

---

---

## 0. The strategy, as executable rules

Source of truth: `VERDICT.md` §"Recommended variant" + §Filters + §Stability.

**Universe:** MEXC USDT perpetual contracts.

**Signal:** the *predicted* funding rate (the rate MEXC publishes ~10-15 min before a
settlement; see memory `mexc-funding-filename-rate-is-predicted` — it runs ~4% rich vs
settled, which is fine, the signal *is* the predicted rate). Positive funding ⇒ longs pay
shorts ⇒ perp at premium ⇒ overheated/pumped microcap ⇒ **we SHORT**.

**Entry** — evaluated in the **+5…+30 min** window after a funding settlement, ALL must hold:
1. `pred_rate >= 0.01` (1%). **Lower bound only — do NOT add a 2% upper cap.** The VERDICT
   "pred ≥ 2% FAILS" finding is a warning against *raising the threshold to 2%*, not a reason
   to exclude the biggest prints from a ≥1% strategy. Threshold configurable; default 0.01.
2. **fresh-episode:** the *previous* settlement's predicted rate for this symbol was
   `< threshold` (this settlement is the first of a new high-funding episode).
3. **token age ≥ 90 days** (contract listing age).
4. **liquidity floor:** pre-event quiet quote-volume ≥ $500 per 5m bar (median of the calm
   pre-event 5m bars). Tradability gate, not alpha — KEEP.
5. risk gates: no open position already in this ticker; open positions `< max_concurrent` (5).

Direction = SHORT. Entry order = **MARKET** (lazy entry, +5..30 min ⇒ no execution race).

**Position:** equal-notional ≈ **5% of equity** per trade; isolated margin; low leverage
(default 1x so a 17.5% adverse move ≈ 0.9% of equity). Protective **stop-MARKET** resting at
`entry * (1 + stop_pct)`, `stop_pct` default **0.175** (working range 0.15–0.20; **never ≤10%**,
that destroys the edge). Stop-market, not stop-limit (fill quality matters — VERDICT §Stability).

**Exit** (whichever first):
- **rate normalization:** at any later settlement the predicted rate `|rate| < 0.001` (0.1%)
  OR sign-flips (`rate <= 0`) ⇒ close MARKET.
- **time cap:** 24h since entry ⇒ close MARKET.
- **hard stop:** the resting stop-market fills; runtime detects and reconciles state.

**Portfolio:** max **5** concurrent, **one position per ticker**. If more entry candidates than
free slots in one window, rank by predicted rate desc and take the top slots (rarely binds —
avg concurrency ≈ 1).

**Expected profile (do not treat as a promise):** ~25-30 trades/mo, median ~+3%/trade,
win ~62%, stop rate ~21%, max-DD budget ~2× the IS −9.5% at this sizing. Known risk: short-alt
beta; a strong alt rally (template: Dec 2025, −7% month) is the untested regime — monitor live.

---

## 1. Architecture (layers; the core is pure)

```
strategy/        PURE domain, zero I/O — the TDD heartland
  models.py      dataclasses: FundingObs, SymbolSnapshot, Position, Account,
                 EntrySignal, Action (OpenShort/PlaceStop/ClosePosition/CancelOrder)
  signals.py     is_fresh_episode(), passes_entry_filters(), evaluate_entries()
  sizing.py      target_notional(equity), notional_to_volume(notional, price, contract meta)
  exits.py       should_exit(position, latest_obs, now) -> reason|None ; stop_price()
  portfolio.py   open_slots(), dedupe_by_ticker(), rank_candidates()
  engine.py      StrategyEngine.step(state, snapshot, now) -> list[Action]  (pure)
exchange/        I/O adapters behind one Protocol
  base.py        Exchange protocol: get_equity, list_positions, open_market_short,
                 place_stop_market, close_position_market, cancel_order, get_symbol_meta,
                 get_recent_5m_klines, get_funding, list_perp_symbols
  mexc.py        MexcExchange — wraps api/contract_client + api/futures_client into domain types
  paper.py       PaperExchange — in-memory simulated fills + equity (DEFAULT runtime backend)
runtime/
  state_store.py JSON-persisted: open positions + per-symbol last predicted rate (episode memory)
  executor.py    turns Action list into Exchange calls; idempotent; logs every order
  scheduler.py   wakes around each settlement, builds snapshot, runs engine.step, executes
api/             EXISTING — keep; fix contract signing (Phase 8)
utils/           EXISTING — config_loader (add env-secret support), logger
config.yaml      add `strategy:` + `runtime:` sections; secrets move to env
main.py          rewire to runtime.scheduler; mode=paper default
tests/
  unit/          pure-domain tests (fast, no network) — bulk of the suite
  integration/   exchange adapter vs mocked HTTP; live canaries gated by RUN_LIVE=1
```

**Why this shape:** every trading *decision* is a pure function of (persisted state, market
snapshot, clock) → list of Actions. That is fully unit-testable with no network and no money.
The Exchange Protocol lets the identical engine drive PaperExchange (safe dry-run) or
MexcExchange (live) with a one-line switch.

The legacy `pipeline/funding_rate_trader.py` (pre-funding 30s strategy) is **superseded** and
left untouched for reference; the new system does not import it. `pipeline/funding_rate_logger.py`
data-collection stays usable.

---

## 2. TDD sequence (each step: write failing test → implement → green → refactor)

- **P0 — scaffolding & safety.** test layout, `tests/unit`, conftest path; move MEXC secrets
  to env (`MEXC_API_KEY`/`MEXC_SECRET_KEY`) with config fallback; gitignore `config.local.yaml`,
  `state/`, `logs/`. **Flag: committed key must be rotated.**
- **P1 — models + signals.** fresh-episode detection; each entry filter; `evaluate_entries`
  combining threshold + fresh + age + liquidity. Liquidity = median quiet 5m quote-vol ≥ $500.
- **P2 — sizing.** target_notional = 5% equity; notional→contract volume with contractSize +
  vol-scale rounding + min-volume floor; reject if below min.
- **P3 — exits.** rate-normalization (|r|<0.1% or flip), 24h time cap, stop price calc;
  precedence (stop > normalization > cap when simultaneous).
- **P4 — portfolio.** open-slots vs max 5; one-per-ticker dedupe; rank by pred rate.
- **P5 — engine.step (integration of pure parts).** scenarios: fresh episode ⇒ [OpenShort,
  PlaceStop]; normalization ⇒ [ClosePosition]; time cap ⇒ [ClosePosition]; stop already filled
  on exchange ⇒ reconcile/no double-close; slot-full ⇒ no open; per-symbol memory updates.
- **P6 — state store.** JSON round-trip of positions + episode memory; corrupt/missing file ⇒
  empty state; atomic write.
- **P7 — paper exchange.** simulated market fills at provided price, stop trigger on adverse
  excursion, equity accounting incl. funding legs and 0.30% round-trip cost; drives a full
  engine loop end-to-end in a test (synthetic settlements).
- **P8 — MEXC adapter (mocked HTTP).** map `/contract/detail` → symbol meta + listing age;
  `/contract/funding_rate/{sym}` → predicted rate + collectCycle + nextSettleTime;
  `/contract/kline` → 5m klines; **fix contract signing** to `HMAC_SHA256(secret,
  accessKey+reqTime+paramString)` and verify against MEXC docs; private wrappers for assets,
  positions, submit order (market), trigger/plan order (stop-market), cancel. HTTP fully mocked.
- **P9 — runtime wiring + paper dry-run.** scheduler builds snapshots around settlements, runs
  engine, executes via PaperExchange; `main.py` mode switch; a scripted multi-settlement paper
  run asserts sane behaviour end-to-end.

## 3. Go-live gates (NOT code — operational, must pass in order)
1. **Read-only private canary:** `get account assets` returns 200 with the corrected signing.
   *If MEXC contract private API is not enabled for this account, live execution is blocked
   regardless of code* — this is the #1 unknown; verify first.
2. Place + cancel a far-from-market tiny test order (real, 1 contract) to confirm submit + the
   trigger/plan (stop-market) endpoint work and the field mapping is right.
3. Run **paper mode** through ≥2 real settlements; confirm signal/sizing/exit logic matches
   intent on live data.
4. Only then flip to live at minimum size; scale only after ~2 months of live fills confirm
   the cost/stop-fill assumptions (VERDICT mandate).

## 4. Open items to verify against live MEXC (tracked, not assumed)
- Contract signing scheme (P8 canary).
- Whether private contract order API is enabled for this key (gate 1).
- Exact stop-market endpoint + fields (`planorder`/trigger vs SL on submit).
- Listing-age field in `/contract/detail` (`createTime`?), else derive from earliest kline.
- 5m kline availability/retention for the liquidity calc at event time.
- Funding settlement schedule per symbol via `collectCycle` (1h/4h/8h mix) — do not assume 8h.
