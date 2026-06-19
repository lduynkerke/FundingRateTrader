"""
Entry point for the S1-Episode funding trader.

Wires the live MEXC public data feed -> pure strategy engine -> executor -> exchange backend,
then runs the settlement-cadence loop. Backend is chosen by config `runtime.mode`:
  * "paper" (default): PaperExchange — simulated fills on the live tape. Safe; no key needed.
  * "live":  MexcExchange — real orders. BLOCKED until the go-live gates in PLAN.md §3 pass
             (read-only private API canary + corrected contract signing + paper validation).

Run:  python main.py
"""

import os

from exchange.mexc import MexcExchange
from exchange.mexc_data import MexcData
from exchange.paper import PaperExchange
from runtime.executor import Executor
from runtime.scheduler import run_forever
from runtime.state_store import load_state
from strategy.config import StrategyConfig
from strategy.engine import StrategyEngine
from utils.config_loader import load_config
from utils.logger import setup_logger


def build_exchange(mode: str, runtime_cfg: dict, mexc_cfg: dict):
    if mode == "paper":
        return PaperExchange(equity=float(runtime_cfg.get("paper_start_equity", 10_000.0)))
    if mode == "live":
        if os.getenv("FRT_CONFIRM_LIVE") != "1":
            raise RuntimeError(
                "Refusing to start LIVE trading without explicit confirmation. "
                "Set FRT_CONFIRM_LIVE=1 in the environment to place real orders."
            )
        api_key = (mexc_cfg or {}).get("api_key", "")
        secret_key = (mexc_cfg or {}).get("secret_key", "")
        if not api_key or not secret_key:
            raise RuntimeError(
                "Live mode needs MEXC credentials (mexc_live in config.local.yaml or "
                "MEXC_API_KEY/MEXC_SECRET_KEY env). None resolved."
            )
        return MexcExchange(
            api_key, secret_key,
            default_leverage=int(runtime_cfg.get("leverage", 1)),
        )
    raise ValueError(f"Unknown runtime.mode: {mode!r} (expected 'paper' or 'live')")


def main() -> None:
    config = load_config()
    logger = setup_logger(config.get("logging"))
    logger.info("Starting S1-Episode funding trader")

    cfg = StrategyConfig.from_mapping(config.get("strategy", {}))
    runtime_cfg = config.get("runtime", {})
    mode = runtime_cfg.get("mode", "paper")
    logger.info("Mode=%s | stop=%.0f%% | entry>=%.1f%% | maxconc=%d",
                mode, cfg.stop_pct * 100, cfg.entry_threshold * 100, cfg.max_concurrent)

    data = MexcData()
    # live trading uses the dedicated mexc_live credentials (config.local.yaml), falling back
    # to the generic mexc block / env secrets.
    live_creds = config.get("mexc_live") or config.get("mexc", {})
    exchange = build_exchange(mode, runtime_cfg, live_creds)
    engine = StrategyEngine(cfg)
    executor = Executor(exchange, cfg)
    state = load_state(runtime_cfg.get("state_path", "state/engine_state.json"))

    run_forever(
        data=data, engine=engine, executor=executor, exchange=exchange,
        state=state, cfg=cfg,
        state_path=runtime_cfg.get("state_path", "state/engine_state.json"),
        entry_delay_minutes=int(runtime_cfg.get("entry_delay_minutes", 15)),
    )


if __name__ == "__main__":
    main()
