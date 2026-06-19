# Deploying the S1-Episode funding trader (Docker on a VM)

This trader shorts fresh ≥1% predicted-funding MEXC microcap perps and exits on
rate-normalization (24h cap) with a 17.5% hard stop. **Test phase config** (in `config.yaml`):
10% equity/trade, **1 position at a time**, fund the account with ~**$100**.

Everything runs in one container; the same image serves the trader and the validation tools.

---

## 0. Prerequisites (on the VM)
- Docker + Docker Compose v2 installed.
- The host clock is NTP-synced (`timedatectl` shows "synchronized: yes"). MEXC signs requests
  with a millisecond timestamp; drift → rejected requests. The container inherits the host clock.
- A MEXC API key **with Futures/Contract trading enabled**.
- **Region matters.** MEXC geofences the *trading* path. Pick a VM region MEXC allows for futures
  (support suggested **Singapore**). The preflight below verifies this from the VM before any real order.

## 1. Get the code and secrets onto the VM
```bash
git clone <your-repo-url> frt && cd frt
cp .env.example .env          # then edit .env:
#   MEXC_API_KEY=...           (your futures key)
#   MEXC_SECRET_KEY=...
#   FRT_CONFIRM_LIVE=0         (keep 0 until you mean it)
#   MEXC_ALLOW_LIVE_ORDERS=0   (only flip for the one-off probes in step 4)
```
`.env` and `config.local.yaml` are gitignored and excluded from the image (`.dockerignore`) —
secrets are injected at runtime as env vars, never baked in. You do **not** need
`config.local.yaml` on the VM if you use `.env`.

## 2. Build
```bash
docker compose build
docker compose run --rm trader test     # optional: run the test suite inside the image
```

## 3. Preflight — read-only go/no-go (run this FIRST)
```bash
docker compose run --rm trader preflight
```
This places **no orders**. Proceed only if:
- the account shows your funded **equity**, and
- `contract.mexc.co` reports **"trading path OPEN"** in the gateway probe.

If `.co` shows a 403 from this VM, the VM's region/IP is blocked — move the VM (see §0) before continuing.

## 4. One gated real round-trip (confirms real fills from this VM)
Temporarily allow real orders for a single tiny probe:
```bash
MEXC_ALLOW_LIVE_ORDERS=1 docker compose run --rm -e MEXC_ALLOW_LIVE_ORDERS=1 trader roundtrip FLOW_USDT
# optional full lifecycle (open -> stop -> cancel -> close): trader rehearsal FLOW_USDT 0
```
It opens ~1 contract (~cents), then flattens, and must end **flat**. Keep `MEXC_ALLOW_LIVE_ORDERS=0`
in `.env` afterward.

## 5. Paper run first (recommended)
Leave `runtime.mode: paper` in `config.yaml` and let it run through at least one hourly settlement:
```bash
docker compose up -d && docker compose logs -f
```
Confirm it scans, (paper-)enters on a qualifying name, and exits as expected.

## 6. Go live (deliberate)
1. Edit `config.yaml`: set `runtime.mode: live`.
2. Edit `.env`: set `FRT_CONFIRM_LIVE=1`.
3. Fund the MEXC account (~$100 for the test phase).
4. Start:
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
The trader refuses live unless `runtime.mode: live` **and** `FRT_CONFIRM_LIVE=1` **and** credentials resolve.

## 7. Operate
- **Logs:** `docker compose logs -f` (also persisted in the `frt-logs` volume; rotated 5×10MB).
- **State:** positions + episode memory persist in the `frt-state` volume, so a restart/redeploy
  resumes cleanly. Inspect: `docker run --rm -v frt_frt-state:/s busybox cat /s/engine_state.json`.
- **Stop:** `docker compose down` (30s grace). Note this does **not** flatten positions — they stay
  open on MEXC, protected by the resting stop, and are picked up again on next start. Flatten manually
  in the MEXC UI if you want to be fully out.
- **Update:** `git pull && docker compose up -d --build`.

## Security
- **Rotate** the API key that was once committed to git history.
- Consider **IP-whitelisting** the key to the VM's egress IP in MEXC API settings.
- Never commit `.env` or `config.local.yaml`. Never put secrets in `config.yaml`.

## Tuning knobs (`config.yaml` → `strategy`)
| key | test value | meaning |
|-----|-----------|---------|
| `equity_fraction` | 0.10 | 10% of equity notional per trade |
| `max_concurrent` | 1 | one position at a time |
| `stop_pct` | 0.175 | 17.5% hard stop (validated 0.10–0.30) |
| `entry_threshold` | 0.01 | short predicted funding ≥ 1% |
| `time_cap_hours` | 24 | force exit after 24h |

Raise `max_concurrent` / `equity_fraction` only after you trust unattended live behavior across
several settlements.
