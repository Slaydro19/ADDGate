"""Adds (or checks) the ADDGate Stop hook in ~/.claude/settings.json.
Backs up the file first and leaves every other setting alone."""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from config import CLAUDE_HOME, SESSIONS_DIR

HOOK_SCRIPT = (Path(__file__).parent / "hooks" / "stop_hook.py").resolve()
SETTINGS = CLAUDE_HOME / "settings.json"
MARKER = "stop_hook.py"


def command():
    return f'"{sys.executable}" "{HOOK_SCRIPT}"'


def _load():
    if not SETTINGS.exists():
        return {}
    with open(SETTINGS, encoding="utf-8") as f:
        return json.load(f)


def status():
    try:
        settings = _load()
    except (json.JSONDecodeError, OSError) as e:
        return {"installed": False, "error": f"Couldn't read {SETTINGS}: {e}"}
    installed = any(MARKER in h.get("command", "") and "ADDGate" in h.get("command", "") or
                    str(HOOK_SCRIPT) in h.get("command", "")
                    for group in settings.get("hooks", {}).get("Stop", [])
                    for h in group.get("hooks", []))
    last = None
    files = sorted(SESSIONS_DIR.glob("*.jsonl")) if SESSIONS_DIR.exists() else []
    if files:
        lines = files[-1].read_text(encoding="utf-8").strip().splitlines()
        if lines:
            last = json.loads(lines[-1]).get("ts")
    return {"installed": installed, "settings_path": str(SETTINGS), "command": command(), "last_seen": last}


def install():
    settings = _load()
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.backup-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(SETTINGS, backup)
    if status()["installed"]:
        return status()
    stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
    stop.append({"hooks": [{"type": "command", "command": command()}]})
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    return status()


if __name__ == "__main__":
    print(json.dumps(install(), indent=2))
