"""Calls Claude through the Claude Code CLI (`claude -p`), so it bills to your
Claude subscription. No API keys or tokens are handled here."""
import json
import os
import re
import shutil
import subprocess
from datetime import date

import db
from config import RUNNER_DIR, load_config


class ClaudeError(Exception):
    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind  # "missing" | "auth" | "limit" | "timeout" | "error"


LIMIT_PATTERNS = re.compile(r"usage limit|rate limit|limit reached|resets? at", re.I)
AUTH_PATTERNS = re.compile(r"log ?in|logged in|auth|credential|api key", re.I)


def claude_path():
    return os.environ.get("ADDGATE_CLAUDE_BIN") or shutil.which("claude")


def _record_usage(payload):
    usage = payload.get("usage") or {}
    # Cache reads (Claude Code's built-in instructions, re-read on every call) are cheap and
    # count far less toward plan limits, so they're left out of the work-token count.
    work = sum(int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens"))
    total = work + int(usage.get("cache_read_input_tokens") or 0)
    cost = float(payload.get("total_cost_usd") or 0)
    with db.write() as c:  # one statement, so parallel calls add up instead of overwriting
        c.execute("INSERT INTO usage (day, tokens, work_tokens, calls, cost_usd) VALUES (?, ?, ?, 1, ?) "
                  "ON CONFLICT(day) DO UPDATE SET tokens = tokens + excluded.tokens, "
                  "work_tokens = work_tokens + excluded.work_tokens, "
                  "calls = calls + 1, cost_usd = cost_usd + excluded.cost_usd",
                  (date.today().isoformat(), total, work, cost))


def note_limit_hit(message):
    with db.write() as c:
        c.execute("INSERT INTO usage (day, limit_message) VALUES (?, ?) "
                  "ON CONFLICT(day) DO UPDATE SET limit_message = excluded.limit_message",
                  (date.today().isoformat(), message[:300]))


def ask(instructions, data_text="", timeout=240):
    """Run one headless Claude call. Instructions go as the prompt argument,
    bulky data (transcripts) goes through stdin. Returns the text result."""
    exe = claude_path()
    if not exe:
        raise ClaudeError("Claude Code isn't installed or isn't on your PATH.", "missing")

    cfg = load_config()
    cmd = [exe, "-p", instructions, "--output-format", "json"]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]

    env = dict(os.environ, ADDGATE_INTERNAL="1")  # our Stop hook skips these runs
    RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cmd, input=data_text, capture_output=True, text=True,
                              timeout=timeout, cwd=str(RUNNER_DIR), env=env)
    except subprocess.TimeoutExpired:
        raise ClaudeError("Claude took too long to answer. Try again.", "timeout")

    raw = (proc.stdout or "").strip()
    payload = None
    if raw:
        try:
            payload = json.loads(raw.splitlines()[-1] if not raw.startswith("{") else raw)
        except json.JSONDecodeError:
            payload = None

    if payload is None or proc.returncode != 0 or payload.get("is_error"):
        msg = (payload or {}).get("result") or proc.stderr.strip() or raw or "Unknown error from Claude Code."
        if LIMIT_PATTERNS.search(msg):
            note_limit_hit(msg)
            raise ClaudeError(msg, "limit")
        if AUTH_PATTERNS.search(msg):
            raise ClaudeError(msg, "auth")
        raise ClaudeError(msg)

    _record_usage(payload)
    return payload.get("result", "")


def extract_json(text):
    """Claude sometimes wraps JSON in prose or code fences. Pull out the
    outermost object or array and parse it."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("No JSON in Claude's reply")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def ask_json(instructions, data_text="", retries=1):
    last = None
    for _ in range(retries + 1):
        reply = ask(instructions, data_text)
        try:
            return extract_json(reply)
        except (ValueError, json.JSONDecodeError) as e:
            last = e
            instructions = instructions + "\n\nYour last reply was not valid JSON. Reply with JSON only."
    raise ClaudeError(f"Claude didn't return valid JSON: {last}")


def check_connection():
    exe = claude_path()
    if not exe:
        return {"connected": False, "kind": "missing",
                "message": "Claude Code isn't installed or isn't on your PATH."}
    try:
        ask("Reply with exactly: ok", timeout=60)
        return {"connected": True, "binary": exe}
    except ClaudeError as e:
        return {"connected": False, "kind": e.kind, "message": str(e)}


def usage_today():
    """ADDGate's own Claude calls today. This is NOT your plan's remaining quota (there's no
    supported way to read that); Claude's Settings > Usage page is the source of truth."""
    cfg = load_config()
    row = db.one("SELECT work_tokens, calls, limit_message FROM usage WHERE day = ?",
                 (date.today().isoformat(),)) or {}
    tokens, calls = int(row.get("work_tokens") or 0), int(row.get("calls") or 0)
    limit = int(cfg.get("daily_token_limit") or 0)  # optional warning the user sets; 0 = off
    pct = round(100 * tokens / limit, 1) if limit else None
    level = "red" if row.get("limit_message") else "amber" if pct is not None and pct >= 80 else "ok"
    out = {"tokens": tokens, "calls": calls, "limit": limit, "percent": pct, "level": level}
    if row.get("limit_message"):
        out["limit_message"] = row["limit_message"]
    return out
