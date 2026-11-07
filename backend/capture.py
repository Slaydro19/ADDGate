"""Reads what you did today: Claude Code transcripts (found via the Stop hook
index, with a fallback scan of ~/.claude/projects) and git commits."""
import json
import subprocess
from datetime import datetime, date, timezone
from pathlib import Path

from config import CLAUDE_HOME, GATE_HOME, SESSIONS_DIR, load_config

MAX_LINE = 140


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _short(text, n=MAX_LINE):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _is_internal(cwd):
    """True for ADDGate's own claude -p runs, which we never want to quiz on."""
    if not cwd:
        return False
    try:
        return Path(cwd).resolve().is_relative_to(GATE_HOME.resolve())
    except (OSError, ValueError):
        return False


def indexed_transcripts(day=None):
    """Transcript paths the Stop hook recorded for a day."""
    day = day or date.today()
    path = SESSIONS_DIR / f"{day.isoformat()}.jsonl"
    found = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tp = rec.get("transcript_path")
            if tp and not _is_internal(rec.get("cwd")):
                found[tp] = rec
    return found


def scanned_transcripts(day=None):
    """Fallback: any transcript touched today, in case the hook isn't installed."""
    day = day or date.today()
    root = CLAUDE_HOME / "projects"
    out = {}
    if not root.exists():
        return out
    for f in root.glob("*/*.jsonl"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime).date() == day:
                out[str(f)] = {"transcript_path": str(f)}
        except OSError:
            continue
    return out


def parse_transcript(path, since=None):
    """Turn a Claude Code .jsonl transcript into a compact event list."""
    events, tool_names = [], {}
    cwd, session_id = None, None
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") not in ("user", "assistant") or entry.get("isSidechain"):
            continue
        cwd = cwd or entry.get("cwd")
        session_id = session_id or entry.get("sessionId")
        ts = _parse_ts(entry.get("timestamp"))
        if since and ts and ts < since:
            continue
        msg = entry.get("message") or {}
        content = msg.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])

        for b in blocks:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text" and b.get("text", "").strip():
                text = b["text"].strip()
                if entry.get("isMeta") or text.startswith("<"):
                    continue  # command wrappers, system reminders
                who = "you" if entry["type"] == "user" else "claude"
                events.append({"ts": ts, "who": who, "text": text})
            elif kind == "tool_use":
                name = b.get("name", "tool")
                tool_names[b.get("id")] = name
                inp = b.get("input") or {}
                if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                    target = inp.get("file_path") or inp.get("notebook_path") or ""
                    events.append({"ts": ts, "who": "edit", "text": f"{name.lower()} {Path(target).name}",
                                   "file": target})
                elif name == "Bash":
                    events.append({"ts": ts, "who": "run", "text": inp.get("command", "")})
            elif kind == "tool_result" and tool_names.get(b.get("tool_use_id")) == "Bash":
                res = b.get("content")
                if isinstance(res, list):
                    res = " ".join(x.get("text", "") for x in res if isinstance(x, dict))
                last = [l for l in str(res or "").strip().splitlines() if l.strip()]
                if last:
                    events.append({"ts": ts, "who": "result", "text": last[-1]})

    if not events or _is_internal(cwd):
        return None
    return {"path": str(path), "session_id": session_id, "cwd": cwd, "events": events}


def sessions_today(since=None):
    found = scanned_transcripts()
    found.update(indexed_transcripts())
    sessions = []
    for tp in found:
        s = parse_transcript(tp, since=since)
        if s:
            sessions.append(s)
    sessions.sort(key=lambda s: s["events"][0]["ts"] or datetime.min.replace(tzinfo=timezone.utc))
    return sessions


def summarize(session):
    """Card data for the Capture screen."""
    ev = session["events"]
    stamps = [e["ts"] for e in ev if e["ts"]]
    start, end = (min(stamps), max(stamps)) if stamps else (None, None)
    files = sorted({e["file"] for e in ev if e.get("file")})
    first_prompt = next((e["text"] for e in ev if e["who"] == "you"), "Untitled session")
    minutes = int((end - start).total_seconds() // 60) if start else 0
    return {
        "id": session["session_id"] or session["path"],
        "title": _short(first_prompt, 70),
        "project": Path(session["cwd"]).name if session["cwd"] else "",
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "minutes": minutes,
        "files": [Path(f).name for f in files],
        "log": [{"t": e["ts"].strftime("%H:%M") if e["ts"] else "", "who": e["who"],
                 "text": _short(e["text"])} for e in ev][-60:],
    }


# How much of each event to send at gate close. Your prompts and Claude's reasoning carry the
# concepts; command output and long code dumps mostly don't, so they're cut hard.
LLM_LIMITS = {"you": 1500, "claude": 600, "run": 160, "result": 120, "edit": 200}


def transcript_for_llm(sessions, max_chars=40000):
    """Compact text version of today's work to hand to Claude at gate close."""
    parts = []
    for s in sessions:
        parts.append(f"\n=== Session in {Path(s['cwd']).name if s['cwd'] else 'unknown folder'} ===")
        last = None
        for e in s["events"]:
            text = " ".join(e["text"].split())  # collapse whitespace and blank lines
            limit = LLM_LIMITS.get(e["who"], 200)
            if len(text) > limit:
                text = text[:limit] + "…"
            line = f"[{e['who']}] {text}"
            if line == last:  # repeated edits of the same file, retried commands
                continue
            parts.append(line)
            last = line
    text = "\n".join(parts)
    if len(text) > max_chars:  # keep the most recent work, starting on a whole line
        tail = text[-max_chars:]
        text = "…(earlier work trimmed)…\n" + tail[tail.find("\n") + 1:]
    return text


def git_commits(since=None):
    since = since or datetime.combine(date.today(), datetime.min.time()).astimezone()
    out = []
    for repo in load_config().get("repos", []):
        repo_path = Path(repo).expanduser()
        if not (repo_path / ".git").exists():
            out.append({"repo": repo_path.name, "error": "not a git repo"})
            continue
        try:
            res = subprocess.run(
                ["git", "-C", str(repo_path), "log", f"--since={since.isoformat()}",
                 "--pretty=format:%h\t%aI\t%s", "--shortstat"],
                capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        current = None
        for line in res.stdout.splitlines():
            if "\t" in line:
                h, when, subject = line.split("\t", 2)
                current = {"repo": repo_path.name, "hash": h, "when": when, "subject": subject, "stat": ""}
                out.append(current)
            elif line.strip() and current:
                current["stat"] = line.strip()
    return out


def commits_for_llm(commits):
    good = [c for c in commits if "hash" in c]
    if not good:
        return ""
    return "\n=== Git commits ===\n" + "\n".join(
        f"{c['repo']} {c['hash']}: {c['subject']} ({c['stat']})" for c in good)
