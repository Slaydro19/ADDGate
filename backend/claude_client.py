"""Calls Claude through the Claude Code CLI (`claude -p`), so it bills to your
Claude subscription. No API keys or tokens are handled here."""
import json
import os
import re
import shutil
import subprocess
from datetime import date

from config import RUNNER_DIR, USAGE_FILE, load_config, read_json, write_json


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
    tokens = sum(int(usage.get(k) or 0) for k in (
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens"))
    data = read_json(USAGE_FILE, {})
    today = date.today().isoformat()
    day = data.get(today, {"tokens": 0, "calls": 0, "cost_usd": 0.0})
    day["tokens"] += tokens
    day["calls"] += 1
    day["cost_usd"] = round(day["cost_usd"] + float(payload.get("total_cost_usd") or 0), 4)
    data[today] = day
    write_json(USAGE_FILE, data)


def note_limit_hit(message):
    data = read_json(USAGE_FILE, {})
    today = date.today().isoformat()
    day = data.get(today, {"tokens": 0, "calls": 0, "cost_usd": 0.0})
    day["limit_message"] = message[:300]
    data[today] = day
    write_json(USAGE_FILE, data)


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
    cfg = load_config()
    day = read_json(USAGE_FILE, {}).get(date.today().isoformat(),
                                        {"tokens": 0, "calls": 0, "cost_usd": 0.0})
    budget = int(cfg.get("daily_token_budget") or 0)
    pct = round(100 * day["tokens"] / budget, 1) if budget else 0
    level = "red" if day.get("limit_message") else "amber" if pct >= 80 else "ok"
    return {**day, "budget": budget, "percent": pct, "level": level}
