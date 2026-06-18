"""
Entry point for the S1-Episode funding trader.

Wires the live MEXC public data feed -> pure strategy engine -> executor -> exchange backend,
then runs the settlement-cadence loop. Backend is chosen by config `runtime.mode`:
  * "paper" (default): PaperExchange — simulated fills on the live tape. Safe; no key needed.
  * "live":  MexcExchange — real orders. BLOCKED until the go-live gates in PLAN.md §3 pass
             (read-only private API canary + corrected contract signing + paper validation).

Run:  python main.py
"""

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
        raise NotImplementedError(
            "Live trading backend (MexcExchange) is not enabled. Complete the go-live gates "
            "in PLAN.md §3 first: (1) read-only private API canary with corrected contract "
            "signing, (2) tiny real test order + cancel, (3) >=2 settlements in paper mode."
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
    exchange = build_exchange(mode, runtime_cfg, config.get("mexc", {}))
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
