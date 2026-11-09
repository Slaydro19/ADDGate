"""Paths and per-user settings for ADDGate.

~/gate/ (owner-only)
  addgate.db   SQLite: accounts, settings, gate state, concepts, attempts, quizzes, usage
  secret.key   signs sign-in cookies
  sessions/    Stop hook index, one .jsonl per day (shared; the hook stays a tiny standalone script)
  .runner/     working folder for ADDGate's own claude -p calls

The signed-in account is set per request with use_user()."""
import contextvars
import json
import os
import shutil
import sys
from pathlib import Path

APP_VERSION = "2.9"
GATE_HOME = Path(os.environ.get("ADDGATE_HOME", Path.home() / "gate")).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()

# Where the app's own files live: the backend folder, or inside ADDGate.app when packaged.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# Hook scripts are copied to ~/gate/hooks so Claude Code and zsh point at a path that never
# moves, even if the app folder is renamed or ADDGate.app is rebuilt.
HOOKS_DIR = GATE_HOME / "hooks"
STOP_HOOK = HOOKS_DIR / "stop_hook.py"
SHELL_HOOK = HOOKS_DIR / "shell_capture.zsh"

SESSIONS_DIR = GATE_HOME / "sessions"
RUNNER_DIR = GATE_HOME / ".runner"
SECRET_FILE = GATE_HOME / "secret.key"

DEFAULT_CONFIG = {
    "repos": [],                 # absolute paths of git repos to watch
    "model": "",                 # blank = Claude Code's default model
    "daily_token_limit": 0,      # optional warning threshold for ADDGate's own usage; 0 = off
    "questions_per_close": 5,
    "hint_delay_seconds": 60,
    "review_intervals_days": [1, 3, 7, 14, 30],
    "terminal_enabled": False,   # owner only; can only be changed through /api/terminal/enable
    "shell_capture_enabled": False,  # owner only: record commands you type (never their output)
    "shell_capture_folders": [],     # only capture inside these folders; empty = your git repos
    "account_token_cap": 0,          # set by an admin only: ADDGate's own Claude tokens per day for this account; 0 = no cap
}
PROTECTED_CONFIG = {"terminal_enabled", "shell_capture_enabled", "shell_capture_folders", "account_token_cap"}  # own routes; never writable through the general settings save

_current_user = contextvars.ContextVar("addgate_user", default=None)


def use_user(user_id):
    _current_user.set(user_id)


def current_user_or_none():
    return _current_user.get()


def current_user():
    uid = _current_user.get()
    if not uid:
        raise RuntimeError("No signed-in user for this request")
    return uid


def ensure_dirs():
    for d in (GATE_HOME, SESSIONS_DIR, RUNNER_DIR, HOOKS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    GATE_HOME.chmod(0o700)  # database, cookie key and transcripts index are yours alone
    install_hook_files()


def install_hook_files():
    """Keep ~/gate/hooks in sync with the copies shipped with this version of ADDGate."""
    for name, mode in (("stop_hook.py", 0o700), ("shell_capture.zsh", 0o600)):
        src, dest = BUNDLE_DIR / "hooks" / name, HOOKS_DIR / name
        if src.exists() and (not dest.exists() or dest.read_bytes() != src.read_bytes()):
            shutil.copyfile(src, dest)
            dest.chmod(mode)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_config():
    import db
    cfg = dict(DEFAULT_CONFIG)
    uid = _current_user.get()
    if uid:
        row = db.one("SELECT data FROM user_config WHERE user_id = ?", (uid,))
        if row:
            cfg.update(db.loads(row["data"], {}))
    return cfg


def save_config(cfg):
    import db
    clean = {k: cfg[k] for k in DEFAULT_CONFIG if k in cfg}
    with db.write() as c:
        c.execute("INSERT INTO user_config (user_id, data) VALUES (?, ?) "
                  "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
                  (current_user(), db.dumps(clean)))
