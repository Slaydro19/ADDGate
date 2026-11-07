"""Paths and user config for ADDGate. Everything lives under ~/gate."""
import json
import os
from pathlib import Path

GATE_HOME = Path(os.environ.get("ADDGATE_HOME", Path.home() / "gate")).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()

SESSIONS_DIR = GATE_HOME / "sessions"   # Stop hook index: one .jsonl per day
DAYS_DIR = GATE_HOME / "days"           # gate close output per day
RUNNER_DIR = GATE_HOME / ".runner"      # cwd for ADDGate's own claude -p calls
CONFIG_FILE = GATE_HOME / "config.json"
STATE_FILE = GATE_HOME / "state.json"   # gate open/closed
VAULT_FILE = GATE_HOME / "vault.json"   # every concept + review schedule
USAGE_FILE = GATE_HOME / "usage.json"

DEFAULT_CONFIG = {
    "repos": [],                 # absolute paths of git repos to watch
    "model": "",                 # blank = Claude Code's default model
    "daily_token_budget": 200000,
    "questions_per_close": 5,
    "hint_delay_seconds": 60,
    "review_intervals_days": [1, 3, 7, 14, 30],
}


def ensure_dirs():
    for d in (GATE_HOME, SESSIONS_DIR, DAYS_DIR, RUNNER_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        write_json(CONFIG_FILE, DEFAULT_CONFIG)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(read_json(CONFIG_FILE, {}))
    return cfg


def save_config(cfg):
    write_json(CONFIG_FILE, cfg)
