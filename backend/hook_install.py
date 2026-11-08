"""Adds (or checks) the ADDGate Stop hook in ~/.claude/settings.json.
Backs up the file first and leaves every other setting alone."""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from config import CLAUDE_HOME, SESSIONS_DIR, STOP_HOOK

HOOK_SCRIPT = STOP_HOOK  # ~/gate/hooks/stop_hook.py: a path that doesn't move
SETTINGS = CLAUDE_HOME / "settings.json"
MARKER = "stop_hook.py"


def _python():
    """The hook only uses Python's standard library, so any python3 runs it. Not the app's own
    interpreter: that lives inside ADDGate.app or a .venv, and either can be rebuilt or deleted."""
    for p in (shutil.which("python3"), "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"):
        if p and Path(p).exists():
            return p
    return "python3"


def command():
    return f'"{_python()}" "{HOOK_SCRIPT}"'


def _ours(cmd):
    return MARKER in cmd and ("ADDGate" in cmd or "/gate/hooks/" in cmd)


def _script_exists(cmd):
    paths = re.findall(r'"([^"]*stop_hook\.py)"', cmd)
    return bool(paths) and Path(paths[-1]).exists()


def _load():
    if not SETTINGS.exists():
        return {}
    with open(SETTINGS, encoding="utf-8") as f:
        return json.load(f)


def _our_commands(settings):
    return [hk.get("command", "") for group in settings.get("hooks", {}).get("Stop", [])
            for hk in group.get("hooks", []) if _ours(hk.get("command", ""))]


def status():
    try:
        settings = _load()
    except (json.JSONDecodeError, OSError) as e:
        return {"installed": False, "error": f"Couldn't read {SETTINGS}: {e}"}
    ours = _our_commands(settings)
    working = any(_script_exists(c) for c in ours)
    last = None
    files = sorted(SESSIONS_DIR.glob("*.jsonl")) if SESSIONS_DIR.exists() else []
    if files:
        lines = files[-1].read_text(encoding="utf-8").strip().splitlines()
        if lines:
            last = json.loads(lines[-1]).get("ts")
    # "stale": an older ADDGate hook points at a script that moved; reinstalling fixes it.
    return {"installed": working, "stale": bool(ours) and not working, "settings_path": str(SETTINGS),
            "command": command(), "last_seen": last}


def install():
    """Adds the hook, or repairs an old one that points at a moved script. Backs up first."""
    settings = _load()
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.backup-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(SETTINGS, backup)
    want = command()
    stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
    for group in stop:  # drop older ADDGate entries; leave every other hook alone
        group["hooks"] = [hk for hk in group.get("hooks", []) if not _ours(hk.get("command", ""))]
    stop[:] = [g for g in stop if g.get("hooks")]
    stop.append({"hooks": [{"type": "command", "command": want}]})
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    return status()


if __name__ == "__main__":
    print(json.dumps(install(), indent=2))
