"""Configuration loading and shared paths."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
FRONTEND_DIR = ROOT / "frontend"
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_PATH = ROOT / "config.example.json"

DEFAULTS = {
    "tmdb_api_key": "",
    "posters_enabled": True,
    "tmdb_direct_route": True,
    "dataset": "ml-latest-small",
    "host": "127.0.0.1",
    "port": 8000,
    "svd": {"n_factors": 64, "n_epochs": 40, "lr": 0.007, "reg": 0.05, "seed": 42},
    "knn": {"k_neighbors": 40, "shrinkage": 25},
    "hybrid": {"alpha": 0.55, "cold_start_threshold": 8},
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict:
    """Defaults, then config.example.json, then config.json, then the environment.

    config.json is gitignored because it holds a personal TMDB key, so a fresh
    clone falls back to the example file for everything except the key - which
    can come from the TMDB_API_KEY environment variable instead.
    """
    cfg = dict(DEFAULTS)
    for path in (EXAMPLE_PATH, CONFIG_PATH):
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            loaded.pop("_comment", None)
            cfg = _merge(cfg, loaded)

    env_key = os.environ.get("TMDB_API_KEY", "").strip()
    if env_key:
        cfg["tmdb_api_key"] = env_key
    if not cfg.get("tmdb_api_key"):
        # no key anywhere: run without posters rather than failing to start
        cfg["posters_enabled"] = False

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return cfg


CONFIG = load_config()
