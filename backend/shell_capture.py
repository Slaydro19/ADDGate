"""Commands you typed yourself, from the zsh hook (hooks/shell_capture.zsh).

Flow: the hook appends raw records to ~/gate/shell/<day>.log (owner-only file). ingest() moves
each file aside, keeps only commands inside your chosen folders, redacts anything that looks like
a secret, stores the result in the database under the OWNER's account, and deletes the raw file.
Other accounts never see these. Output is never captured, only the command line and exit code."""
import os
import re
from datetime import datetime
from pathlib import Path

import db
from config import GATE_HOME, SHELL_HOOK, load_config

SHELL_DIR = GATE_HOME / "shell"
FLAG = SHELL_DIR / ".enabled"
HOOK_FILE = SHELL_HOOK  # ~/gate/hooks/shell_capture.zsh: stable even when the app is rebuilt
ZSHRC = Path.home() / ".zshrc"
MAX_LEN = 500
NOISE = {"ls", "ll", "la", "l", "cd", "clear", "cls", "pwd", "exit", "history", "z", "j", "..", "...", "fg", "bg", "jobs"}
R = "[REDACTED]"

# Order matters: specific patterns first, then generic catch-alls.
REDACTIONS = [
    # known token formats
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), R),
    (re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}"), R),
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{8,}"), R),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), R),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), R),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), R),            # JWT
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), R),
    # headers and URLs
    (re.compile(r"(?i)(authorization:\s*(?:bearer|basic|token)\s+)[^\s'\"]+"), r"\1" + R),
    (re.compile(r"(?i)((?:x-api-key|api-key|x-auth-token|cookie):\s*)[^'\"]+"), r"\1" + R),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):[^@\s/]+@"), r"\1:" + R + "@"),           # user:pass@host
    (re.compile(r"(?i)([?&](?:token|key|api_key|apikey|secret|password|pass|sig|signature|access_token)=)[^&\s'\"]+"), r"\1" + R),
    # flags that take a secret
    (re.compile(r"(?i)(?<!\S)(--?(?:password|passwd|pass|token|api-key|apikey|secret|client-secret|auth|key)(?:=|\s+))(['\"]?)[^\s'\"]+\2"), r"\1" + R),
    (re.compile(r"(\b(?:mysql|mariadb|mysqldump|mongo|mongosh)\b[^|;&]*?\s-p)(\S+)"), r"\1" + R),   # mysql -pSECRET
    (re.compile(r"(\bsshpass\s+-p\s*)(\S+)"), r"\1" + R),
    (re.compile(r"(\s-u\s+[^:\s]+):(\S+)"), r"\1:" + R),                                                # curl -u user:pass
    (re.compile(r"(?i)(\bhtpasswd\b.*\s-b\s+\S+\s+)(\S+)"), r"\1" + R),
    # NAME=value where the name sounds secret (export TOKEN=..., FOO_API_KEY=... cmd)
    (re.compile(r"(?i)(?<![?&\w])([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|PASS|PWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIALS?|AUTH|SESSION|COOKIE)[A-Z0-9_]*=)(?!\[REDACTED\])(['\"]?)[^\s'\"&]*\2"), r"\1" + R),
    # long random-looking strings (40+ chars of hex/base64): probably a key
    (re.compile(r"(?<![/\w.-])[A-Za-z0-9+/_-]{40,}={0,2}(?![/\w.-])"), R),
]


GIT_HASH = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b")


def redact(cmd):
    out = cmd
    # git commit hashes look like keys; protect them in git commands before the catch-all runs
    keep = {}
    if re.match(r"\s*git\b", cmd):
        def stash(m):
            keep[f"\x00{len(keep)}\x00"] = m.group(0)
            return f"\x00{len(keep) - 1}\x00"
        out = GIT_HASH.sub(stash, out)
    for pat, repl in REDACTIONS:
        out = pat.sub(repl, out)
    for k, v in keep.items():
        out = out.replace(k, v)
    return out, out != cmd


def owner_id():
    row = db.one("SELECT id FROM users WHERE is_owner = 1 LIMIT 1")
    return row["id"] if row else None


def _owner_config(uid):
    import config
    token = config._current_user.set(uid)
    try:
        return load_config()
    finally:
        config._current_user.reset(token)


def allowed_folders(cfg):
    folders = [str(Path(f).expanduser()) for f in (cfg.get("shell_capture_folders") or []) if str(f).strip()]
    if not folders:
        folders = [str(Path(r).expanduser()) for r in cfg.get("repos", [])]
    return [os.path.realpath(f) for f in folders]


def in_folders(cwd, folders):
    if not folders:
        return False  # nothing chosen yet: capture nothing rather than everything
    real = os.path.realpath(cwd or "/")
    return any(real == f or real.startswith(f.rstrip("/") + "/") for f in folders)


def is_noise(cmd):
    words = cmd.strip().split()
    return not words or (words[0] in NOISE and len(cmd) < 25)


def _ts(value):
    try:
        return datetime.fromtimestamp(float(value)).astimezone().isoformat()
    except (TypeError, ValueError):
        return datetime.now().astimezone().isoformat()


def parse(raw):
    for rec in raw.split("\x1e"):
        parts = rec.split("\x1f")
        if len(parts) < 6:
            continue
        start, end, code, cwd, src, cmd = parts[0], parts[1], parts[2], parts[3], parts[4], "\x1f".join(parts[5:])
        yield {"started_at": _ts(start), "ended_at": _ts(end),
               "exit_code": int(code) if code.lstrip("-").isdigit() else None, "cwd": cwd,
               "source": "terminal" if src == "1" else "shell", "command": cmd}


def set_enabled(on):
    SHELL_DIR.mkdir(parents=True, exist_ok=True)
    SHELL_DIR.chmod(0o700)
    if on:
        FLAG.touch()
    else:
        FLAG.unlink(missing_ok=True)
        for f in SHELL_DIR.glob("*.log*"):  # turning it off throws away anything not yet imported
            f.unlink(missing_ok=True)


def ingest():
    """Import raw hook files. Safe to call often; does nothing when there's nothing new."""
    if not SHELL_DIR.exists():
        return 0
    uid = owner_id()
    files = sorted(SHELL_DIR.glob("*.log"))
    if not files:
        return 0
    cfg = _owner_config(uid) if uid else {}
    enabled, folders = bool(cfg.get("shell_capture_enabled")), allowed_folders(cfg)
    added = 0
    for f in files:
        work = f.with_suffix(".log.ingesting")
        try:
            f.rename(work)  # the hook keeps appending to a fresh file meanwhile
        except OSError:
            continue
        rows = []
        if uid and enabled:
            for c in parse(work.read_text(encoding="utf-8", errors="replace")):
                if is_noise(c["command"]) or not in_folders(c["cwd"], folders):
                    continue
                cmd, was = redact(c["command"])
                if len(cmd) > MAX_LEN:
                    cmd = cmd[:MAX_LEN] + "…"
                rows.append((uid, c["started_at"], c["ended_at"], c["exit_code"], c["cwd"], c["source"], cmd, int(was)))
        if rows:
            with db.write() as conn:
                conn.executemany("INSERT INTO shell_commands (user_id, started_at, ended_at, exit_code, cwd, source, "
                                 "command, redacted) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            added += len(rows)
        work.unlink(missing_ok=True)  # raw text (with any secrets) is gone either way
    return added


def commands_since(uid, since_iso, limit=400):
    return db.all_rows("SELECT * FROM shell_commands WHERE user_id = ? AND started_at >= ? ORDER BY started_at, id "
                       "LIMIT ?", (uid, since_iso, limit))


def blocks(commands, gap_minutes=15):
    """Group commands into work blocks: same folder, no long gaps. Shown like sessions on Capture."""
    out, cur = [], None
    for c in commands:
        t = datetime.fromisoformat(c["started_at"])
        if cur and c["cwd"] == cur["cwd"] and (t - cur["_last"]).total_seconds() < gap_minutes * 60:
            cur["commands"].append(c)
            cur["_last"] = t
        else:
            cur = {"cwd": c["cwd"], "commands": [c], "_first": t, "_last": t}
            out.append(cur)
    for b in out:
        b["start"], b["end"] = b.pop("_first").isoformat(), b.pop("_last").isoformat()
    return out


def zshrc_status():
    try:
        text = ZSHRC.read_text(encoding="utf-8")
    except OSError:
        text = ""
    line = f'source "{HOOK_FILE}"'
    old = [l for l in text.splitlines() if "shell_capture.zsh" in l and l.strip().startswith("source")]
    # "stale": an older line points at a copy inside the app folder; adding again replaces it
    return {"installed": line in text, "stale": bool(old) and line not in text, "line": line, "path": str(ZSHRC)}


def install_zshrc():
    st = zshrc_status()
    if st["installed"]:
        return st
    if st["stale"]:
        uninstall_zshrc()
    if ZSHRC.exists():
        backup = ZSHRC.with_name(f".zshrc.addgate-backup-{datetime.now():%Y%m%d-%H%M%S}")
        backup.write_bytes(ZSHRC.read_bytes())
    with open(ZSHRC, "a", encoding="utf-8") as f:
        f.write(f"\n# ADDGate shell capture (does nothing unless turned on in ADDGate; start a command with a space to skip)\n"
                f"{st['line']}\n")
    return zshrc_status()


def uninstall_zshrc():
    if not ZSHRC.exists():
        return zshrc_status()
    lines = ZSHRC.read_text(encoding="utf-8").splitlines(keepends=True)
    keep = [l for l in lines if not ("shell_capture.zsh" in l and l.strip().startswith("source"))
            and not l.startswith("# ADDGate shell capture")]
    ZSHRC.write_text("".join(keep), encoding="utf-8")
    return zshrc_status()


def clear(uid):
    with db.write() as conn:
        conn.execute("DELETE FROM shell_commands WHERE user_id = ?", (uid,))


def summarize_block(b):
    """Card data for the Capture screen, same shape as a Claude session card."""
    cmds = b["commands"]
    first = next((c["command"] for c in cmds), "")
    start, end = datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])
    failed = sum(1 for c in cmds if c["exit_code"] not in (0, None))
    return {
        "id": f"shell-{b['start']}", "kind": "shell",
        "title": f"You ran {len(cmds)} command{'s' if len(cmds) != 1 else ''}: {first[:50]}{'…' if len(first) > 50 else ''}",
        "project": Path(b["cwd"]).name or b["cwd"], "start": b["start"], "end": b["end"],
        "minutes": int((end - start).total_seconds() // 60), "files": [], "commands": len(cmds), "failed": failed,
        "log": [{"t": datetime.fromisoformat(c["started_at"]).strftime("%H:%M"), "who": "typed",
                 "text": c["command"] + (f"   ✗ exit {c['exit_code']}" if c["exit_code"] not in (0, None) else ""),
                 "exit": c["exit_code"]} for c in cmds][-60:],
    }


def for_llm(commands, max_chars=8000):
    """Your own commands for the gate-close prompt, tagged so Claude knows YOU typed them."""
    if not commands:
        return ""
    lines, cwd = ["\n=== Commands the person typed THEMSELVES (not Claude) ==="], None
    for c in commands:
        if c["cwd"] != cwd:
            cwd = c["cwd"]
            lines.append(f"(in {Path(cwd).name or cwd})")
        code = c["exit_code"]
        lines.append(f"[you ran] {c['command'][:200]}" + (f"  (exit {code})" if code not in (0, None) else ""))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else lines[0] + "\n…(earlier commands trimmed)…\n" + text[-max_chars:]
