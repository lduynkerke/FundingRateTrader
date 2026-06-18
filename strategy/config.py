"""
Strategy parameters for S1-Episode, defaulting to the VERDICT.md "conditional GO" spec.

Every number here is a knob the backtest pinned down; defaults are the recommended values.
Keep this a plain dataclass so the pure logic never reaches for config files or env.
"""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class StrategyConfig:
    # --- entry ---
    entry_threshold: float = 0.01      # predicted funding >= 1% (lower bound only)
    min_age_days: float = 90.0         # contract listing age floor
    min_liq_quote_vol: float = 500.0   # quiet pre-event quote-vol per 5m bar ($)

    # --- exit ---
    normalize_threshold: float = 0.001  # |pred rate| < 0.1% => episode over
    time_cap_hours: float = 24.0        # hard cap on hold time
    stop_pct: float = 0.175             # adverse-excursion hard stop (15-20% range)

    # --- sizing / portfolio ---
    equity_fraction: float = 0.05       # notional per trade as fraction of equity
    max_concurrent: int = 5             # max simultaneous positions
    leverage: int = 1                   # isolated-margin leverage

    def __post_init__(self):
        if not (0.10 <= self.stop_pct <= 0.30):
            # 5% stops destroy the edge; >30% is untested. Guard against fat-finger configs.
            raise ValueError(
                f"stop_pct={self.stop_pct} outside validated 0.10-0.30 range"
            )
        if self.entry_threshold <= 0:
            raise ValueError("entry_threshold must be positive (we short positive funding)")

    @classmethod
    def from_mapping(cls, data: dict) -> "StrategyConfig":
        """Build from a config dict, ignoring unknown keys (e.g. runtime settings)."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})
