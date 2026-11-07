"""Defenses that matter most once ADDGate has a terminal: who is talking to the server, from where."""
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

import db

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

# ---------- Host / Origin ----------

def hostname(value):
    """'localhost:5055' -> 'localhost'; '[::1]:5055' -> '[::1]'."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1]
    return value.rsplit(":", 1)[0] if ":" in value else value


def host_ok(host_header):
    """Blocks DNS rebinding: an attacker's domain that resolves to 127.0.0.1 arrives with its
    own name in the Host header, so only requests addressed to localhost get through."""
    return hostname(host_header) in LOCAL_HOSTS


def origin_ok(origin, allowed_ports):
    """For the terminal WebSocket: the page opening it must be ADDGate itself."""
    if not origin:
        return False
    parts = urlsplit(origin)
    return (parts.scheme == "http" and (parts.hostname or "") in {"localhost", "127.0.0.1", "::1"}
            and parts.port in allowed_ports)


def security_headers(resp, ws_ports):
    ws = " ".join(f"ws://localhost:{p} ws://127.0.0.1:{p}" for p in sorted(ws_ports))
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "                                    # no inline or injected scripts
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "  # React inline styles, fonts
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        f"connect-src 'self' {ws}; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"                                 # nobody can frame ADDGate
    )
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    return resp


# ---------- login throttling ----------

MAX_FAILURES, WINDOW, LOCKOUT = 5, 300, 300
_failures = {}
_lock = threading.Lock()


def login_blocked(username):
    """Seconds left on a lockout, or 0."""
    key = (username or "").strip().lower()
    with _lock:
        rec = _failures.get(key)
        if rec and rec.get("locked_until", 0) > time.time():
            return int(rec["locked_until"] - time.time()) + 1
    return 0


def login_failed(username):
    key = (username or "").strip().lower()
    now = time.time()
    with _lock:
        rec = _failures.setdefault(key, {"times": []})
        rec["times"] = [t for t in rec["times"] if now - t < WINDOW] + [now]
        if len(rec["times"]) >= MAX_FAILURES:
            rec["locked_until"] = now + LOCKOUT
            rec["times"] = []
            return True
    return False


def login_succeeded(username):
    with _lock:
        _failures.pop((username or "").strip().lower(), None)


# ---------- audit log ----------

def audit(user_id, event, detail=""):
    with db.write() as c:
        c.execute("INSERT INTO audit (user_id, at, event, detail) VALUES (?, ?, ?, ?)",
                  (user_id, datetime.now().astimezone().isoformat(), event, str(detail)[:300]))


def recent_audit(limit=30):
    return db.all_rows("SELECT a.at, a.event, a.detail, u.username FROM audit a "
                       "LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT ?", (limit,))
