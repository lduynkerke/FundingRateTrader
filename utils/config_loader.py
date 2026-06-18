"""
Configuration loading for FundingRateTrader.

Precedence (low -> high): config.yaml  <  config.local.yaml (gitignored)  <  env vars.
Secrets (MEXC_API_KEY / MEXC_SECRET_KEY) should come from the environment or the gitignored
local file, never from the tracked config.yaml.
"""

import os
from pathlib import Path

import yaml


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str = "config.yaml", local_path: str = None) -> dict:
    """Load YAML config, overlaying config.local.yaml and then env-var secrets.

    :param path: Path to the tracked base config.
    :param local_path: Path to the gitignored override (defaults to config.local.yaml
                       beside the base config).
    :return: Merged configuration dict.
    """
    with open(path, "r") as f:
        config = yaml.safe_load(f) or {}

    if local_path is None:
        local_path = str(Path(path).with_name("config.local.yaml"))
    if Path(local_path).exists():
        with open(local_path, "r") as f:
            _deep_merge(config, yaml.safe_load(f) or {})

    mexc = config.setdefault("mexc", {})
    if os.getenv("MEXC_API_KEY"):
        mexc["api_key"] = os.getenv("MEXC_API_KEY")
    if os.getenv("MEXC_SECRET_KEY"):
        mexc["secret_key"] = os.getenv("MEXC_SECRET_KEY")

    return config
