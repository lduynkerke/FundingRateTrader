"""
P0 — config loading with a gitignored local override and env-var secrets.

Secrets must never need to live in the tracked config.yaml: a config.local.yaml override
(deep-merged) and MEXC_API_KEY / MEXC_SECRET_KEY env vars (highest precedence) both work.
"""

from utils.config_loader import load_config


def write(p, text):
    p.write_text(text, encoding="utf-8")


def test_loads_base_yaml(tmp_path):
    base = tmp_path / "config.yaml"
    write(base, "mexc:\n  api_key: ''\n  timeout: 10\n")
    cfg = load_config(str(base), local_path=str(tmp_path / "none.yaml"))
    assert cfg["mexc"]["timeout"] == 10


def test_local_override_deep_merges(tmp_path):
    base = tmp_path / "config.yaml"
    local = tmp_path / "config.local.yaml"
    write(base, "mexc:\n  api_key: ''\n  timeout: 10\n")
    write(local, "mexc:\n  api_key: 'from-local'\n")
    cfg = load_config(str(base), local_path=str(local))
    assert cfg["mexc"]["api_key"] == "from-local"
    assert cfg["mexc"]["timeout"] == 10  # base value preserved


def test_env_overrides_everything(tmp_path, monkeypatch):
    base = tmp_path / "config.yaml"
    local = tmp_path / "config.local.yaml"
    write(base, "mexc:\n  api_key: 'base'\n  secret_key: 'base'\n")
    write(local, "mexc:\n  api_key: 'local'\n")
    monkeypatch.setenv("MEXC_API_KEY", "env-key")
    monkeypatch.setenv("MEXC_SECRET_KEY", "env-secret")
    cfg = load_config(str(base), local_path=str(local))
    assert cfg["mexc"]["api_key"] == "env-key"
    assert cfg["mexc"]["secret_key"] == "env-secret"
