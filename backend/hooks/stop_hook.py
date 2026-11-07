#!/usr/bin/env python3
"""Claude Code Stop hook. Claude Code runs this every time Claude finishes a reply
and passes JSON on stdin with session_id, transcript_path and cwd. We append that
to ~/gate/sessions/<today>.jsonl so ADDGate knows which transcripts to read.
It must never block or fail Claude Code, so every error is swallowed."""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path


def main():
    if os.environ.get("ADDGATE_INTERNAL"):
        return  # ADDGate's own claude -p calls
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    gate_home = Path(os.environ.get("ADDGATE_HOME", Path.home() / "gate")).expanduser()
    cwd = data.get("cwd") or ""
    try:
        if cwd and Path(cwd).resolve().is_relative_to(gate_home.resolve()):
            return
    except Exception:
        pass
    sessions = gate_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now().astimezone().isoformat(), "session_id": data.get("session_id"),
           "transcript_path": data.get("transcript_path"), "cwd": cwd}
    with open(sessions / f"{date.today().isoformat()}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
