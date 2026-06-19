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


def load_live_creds(local_path: str = None) -> dict:
    """Resolve live MEXC credentials for tools/experiments.

    Precedence: MEXC_API_KEY/MEXC_SECRET_KEY env vars (how the Docker container injects
    secrets) first, then the `mexc_live` (or `mexc`) block of config.local.yaml. Raises if
    neither yields a key pair, so a misconfigured deploy fails loudly instead of unsigned.
    """
    api, sec = os.getenv("MEXC_API_KEY"), os.getenv("MEXC_SECRET_KEY")
    if api and sec:
        return {"api_key": api, "secret_key": sec}

    if local_path is None:
        local_path = str(Path(__file__).resolve().parents[1] / "config.local.yaml")
    if Path(local_path).exists():
        data = yaml.safe_load(open(local_path)) or {}
        block = data.get("mexc_live") or data.get("mexc") or {}
        if block.get("api_key") and block.get("secret_key"):
            return {"api_key": block["api_key"], "secret_key": block["secret_key"]}

    raise RuntimeError(
        "No MEXC live credentials found: set MEXC_API_KEY/MEXC_SECRET_KEY env vars or add a "
        "mexc_live block to config.local.yaml."
    )
