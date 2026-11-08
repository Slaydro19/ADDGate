"""ADDGate local server. Serves the API on /api and the built React app on /.
Binds to 127.0.0.1 only: nothing is reachable from other machines."""
import os
import secrets
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_sock import Sock

import capture
import db
import migrate
import claude_client as cc
import gate
import hook_install
import security
import shell_capture
import stats as stats_mod
import terminal
import users
from config import (BUNDLE_DIR, DEFAULT_CONFIG, PROTECTED_CONFIG, SECRET_FILE, ensure_dirs, load_config,
                    save_config, use_user)

STATIC = BUNDLE_DIR / "static"  # the built UI: next to this file, or inside ADDGate.app
PORT = int(os.environ.get("ADDGATE_PORT", 5055))
DEV = bool(os.environ.get("ADDGATE_DEV") or os.environ.get("FLASK_DEBUG"))
ALLOWED_PORTS = {PORT} | ({5173} if DEV else set())  # 5173 = Vite dev server in dev mode only
PUBLIC_API = {"/api/status", "/api/auth/me", "/api/auth/login", "/api/auth/signup", "/api/auth/logout"}


def secret_key():
    ensure_dirs()
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text().strip()


ensure_dirs()
db.init()
migrate.run()  # one-time import of older JSON files; does nothing once they're imported

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=secret_key(),
    SESSION_COOKIE_NAME="addgate_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
_conn_cache = {"at": 0, "value": None}
sock = Sock(app)


# ---------- request guards ----------

@app.before_request
def guard():
    use_user(None)
    if not security.host_ok(request.host):  # DNS rebinding: only requests addressed to localhost
        return "Forbidden: ADDGate only answers to localhost.", 403
    if request.path == "/ws/terminal":  # checked BEFORE the WebSocket handshake is accepted
        return _terminal_gate()
    if not request.path.startswith("/api/"):
        return None
    # Blocks cross-site form posts: browsers can't send JSON cross-origin without a CORS preflight.
    if request.method in ("POST", "PUT", "DELETE") and not request.is_json:
        return jsonify(error="Requests must be JSON.", kind="bad_request"), 415
    uid = session.get("uid")
    user = users.get(uid) if uid else None
    if user:
        use_user(user["id"])
    elif request.path not in PUBLIC_API:
        session.clear()
        return jsonify(error="Please sign in.", kind="login"), 401
    return None


@app.after_request
def headers(resp):
    return security.security_headers(resp, ALLOWED_PORTS)


@app.errorhandler(terminal.TerminalError)
def terminal_error(e):
    return jsonify(error=str(e), kind="terminal"), 409


@app.errorhandler(cc.ClaudeError)
def claude_error(e):
    if e.kind in ("auth", "missing"):  # a real call just proved the connection is gone
        _conn_cache.update(at=time.time(), value={"connected": False, "kind": e.kind, "message": str(e)})
    code = {"limit": 429, "missing": 503, "auth": 401, "empty": 409}.get(e.kind, 502)
    return jsonify(error=str(e), kind=e.kind), code


@app.errorhandler(users.AuthError)
def auth_error(e):
    return jsonify(error=str(e), kind="auth_form"), 400


@app.errorhandler(KeyError)
def not_found(e):
    return jsonify(error=str(e).strip("'")), 404


def body():
    return request.get_json(silent=True) or {}


# ---------- accounts ----------

@app.get("/api/auth/me")
def me():
    uid = session.get("uid")
    user = users.get(uid) if uid else None
    return jsonify(user=users.public(user) if user else None, has_users=users.has_users())


@app.post("/api/auth/signup")
def signup():
    b = body()
    user, first = users.create(b.get("username"), b.get("password"), b.get("display_name"))
    if first:
        migrate.adopt_legacy(user["id"])
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    return jsonify(user=users.public(user))


@app.post("/api/auth/login")
def login():
    b = body()
    wait = security.login_blocked(b.get("username"))
    if wait:
        return jsonify(error=f"Too many wrong passwords. Try again in {wait // 60 + 1} min.", kind="auth_form"), 429
    try:
        user = users.authenticate(b.get("username"), b.get("password"))
    except users.AuthError:
        if security.login_failed(b.get("username")):
            security.audit(None, "login_locked", (b.get("username") or "")[:40])
        raise
    security.login_succeeded(b.get("username"))
    session.clear()
    session.permanent = bool(b.get("remember", True))
    session["uid"] = user["id"]
    return jsonify(user=users.public(user))


@app.post("/api/auth/logout")
def logout():
    if session.get("uid"):
        terminal.close_all(session["uid"], "signed out")
    session.clear()
    return jsonify(ok=True)


@app.post("/api/auth/password")
def password():
    b = body()
    users.change_password(session["uid"], b.get("current"), b.get("new"))
    return jsonify(ok=True)


@app.post("/api/auth/confirm")
def confirm_password():
    """'sudo mode': re-enter your password to unlock sensitive actions for 15 minutes."""
    uid = session["uid"]
    key = f"confirm:{uid}"
    wait = security.login_blocked(key)
    if wait:
        return jsonify(error=f"Too many wrong passwords. Try again in {wait // 60 + 1} min.", kind="auth_form"), 429
    if not users.check_password(uid, body().get("password")):
        if security.login_failed(key):
            security.audit(uid, "confirm_locked")
        return jsonify(error="That's not your password.", kind="auth_form"), 400
    security.login_succeeded(key)
    session["reauth_at"] = time.time()
    return jsonify(ok=True, unlocked_for=terminal.REAUTH_TTL)


def _unlocked():
    return time.time() - float(session.get("reauth_at") or 0) < terminal.REAUTH_TTL


def _owner():
    user = users.get(session.get("uid"))
    return user if user and user.get("is_owner") else None


# ---------- terminal (owner only) ----------

@app.get("/api/terminal/status")
def terminal_status():
    owner = _owner()
    left = max(0, int(terminal.REAUTH_TTL - (time.time() - float(session.get("reauth_at") or 0))))
    return jsonify(allowed=bool(owner), enabled=bool(owner) and bool(load_config().get("terminal_enabled")),
                   unlocked=_unlocked(), unlocked_seconds=left if _unlocked() else 0,
                   sessions=terminal.count(session["uid"]), max_sessions=terminal.MAX_SESSIONS)


@app.post("/api/terminal/enable")
def terminal_enable():
    owner = _owner()
    if not owner:
        return jsonify(error="Only the owner of this Mac's ADDGate can use the terminal.", kind="forbidden"), 403
    b = body()
    if not users.check_password(owner["id"], b.get("password")):
        return jsonify(error="That's not your password.", kind="auth_form"), 400
    cfg = load_config()
    cfg["terminal_enabled"] = bool(b.get("enabled"))
    save_config(cfg)
    if not cfg["terminal_enabled"]:
        terminal.close_all(owner["id"], "terminal turned off")
    else:
        session["reauth_at"] = time.time()
    security.audit(owner["id"], "terminal_enabled" if cfg["terminal_enabled"] else "terminal_disabled")
    return jsonify(enabled=cfg["terminal_enabled"])


@app.post("/api/terminal/ticket")
def terminal_ticket():
    owner = _owner()
    if not owner or not load_config().get("terminal_enabled"):
        return jsonify(error="The terminal is off.", kind="forbidden"), 403
    if not _unlocked():
        return jsonify(error="Confirm your password to open a terminal.", kind="reauth"), 403
    return jsonify(ticket=terminal.issue_ticket(owner["id"]))


def _terminal_gate():
    """Every lock, checked before the WebSocket upgrade. Any failure is a plain 403."""
    uid = session.get("uid")
    owner = _owner()
    reasons = []
    if not security.origin_ok(request.headers.get("Origin"), ALLOWED_PORTS):
        reasons.append("bad origin")
    if not owner or owner["id"] != uid:
        reasons.append("not owner")
    else:
        use_user(uid)
        if not load_config().get("terminal_enabled"):
            reasons.append("terminal off")
        if not _unlocked():
            reasons.append("not unlocked")
    if not terminal.redeem_ticket(request.args.get("ticket"), uid):  # always spent, even on failure
        reasons.append("bad ticket")
    if reasons:
        security.audit(uid, "terminal_refused", ", ".join(reasons) + f" (origin {request.headers.get('Origin')})")
        return "Forbidden", 403
    g.terminal_uid = uid
    return None


@sock.route("/ws/terminal")
def terminal_socket(ws):
    uid = getattr(g, "terminal_uid", None)
    if not uid:  # unreachable: _terminal_gate runs first; kept as a second lock
        ws.close(reason=1008, message="Not allowed")
        return
    terminal.run(ws, uid, security.audit)


@app.get("/api/audit")
def audit_log():
    if not _owner():
        return jsonify(error="Owner only.", kind="forbidden"), 403
    return jsonify(events=security.recent_audit())


# ---------- Claude connection + usage (shared by the whole machine) ----------

@app.get("/api/status")
def status():
    # A check is a real Claude call, so it only runs on startup, when you press Refresh, or while
    # disconnected. Otherwise the last result stands until a real call fails with an auth error.
    fresh = request.args.get("refresh") == "1"
    if fresh or not _conn_cache["value"]:
        _conn_cache.update(at=time.time(), value=cc.check_connection())
    return jsonify(_conn_cache["value"])


@app.get("/api/usage")
def usage():
    return jsonify(cc.usage_today())


# ---------- capture + gate ----------

@app.get("/api/capture")
def capture_view():
    st = gate.state()
    sessions = [capture.summarize(s) for s in capture.sessions_today()]
    shell = None
    if _owner():  # your own commands are only ever shown to the owner
        shell_capture.ingest()
        start_of_day = datetime.combine(date.today(), datetime.min.time()).astimezone().isoformat()
        typed = shell_capture.commands_since(session["uid"], start_of_day)
        sessions += [shell_capture.summarize_block(b) for b in shell_capture.blocks(typed)]
        sessions.sort(key=lambda s: s["start"] or "")
        cfg_ = load_config()
        shell = {"enabled": bool(cfg_.get("shell_capture_enabled")), "today": len(typed),
                 "folders": shell_capture.allowed_folders(cfg_)}
    for s in sessions:
        end = s["end"] or ""
        if st["status"] == "closed":  # quizzed already unless worked on after the close
            s["after_open"] = end > (st.get("closed_at") or "")
        else:
            s["after_open"] = end >= st["opened_at"]
    cfg = load_config()
    return jsonify(gate=st, sessions=sessions, commits=capture.git_commits(),
                   hook=hook_install.status(), repos=cfg.get("repos", []), shell=shell,
                   due=len(gate.due_concepts()))


# ---------- shell capture (owner only) ----------

def _owner_or_403():
    owner = _owner()
    if not owner:
        return None, (jsonify(error="Only this Mac's owner can use shell capture.", kind="forbidden"), 403)
    return owner, None


@app.get("/api/shell/status")
def shell_status():
    owner, err = _owner_or_403()
    if err:
        return err
    cfg = load_config()
    count = db.one("SELECT COUNT(*) AS n, MIN(started_at) AS first FROM shell_commands WHERE user_id = ?", (owner["id"],))
    return jsonify(enabled=bool(cfg.get("shell_capture_enabled")), folders=cfg.get("shell_capture_folders", []),
                   effective_folders=shell_capture.allowed_folders(cfg), stored=count["n"], since=count["first"],
                   zshrc=shell_capture.zshrc_status())


@app.post("/api/shell/settings")
def shell_settings():
    owner, err = _owner_or_403()
    if err:
        return err
    b = body()
    cfg = load_config()
    if "folders" in b:
        cfg["shell_capture_folders"] = [str(Path(f).expanduser()) for f in b["folders"] if str(f).strip()][:50]
    if "enabled" in b:
        cfg["shell_capture_enabled"] = bool(b["enabled"])
        shell_capture.set_enabled(cfg["shell_capture_enabled"])
        security.audit(owner["id"], "shell_capture_on" if cfg["shell_capture_enabled"] else "shell_capture_off")
    save_config(cfg)
    return shell_status()


@app.post("/api/shell/zshrc")
def shell_zshrc():
    owner, err = _owner_or_403()
    if err:
        return err
    st = shell_capture.install_zshrc() if body().get("install") else shell_capture.uninstall_zshrc()
    security.audit(owner["id"], "zshrc_hook_added" if st["installed"] else "zshrc_hook_removed")
    return jsonify(st)


@app.post("/api/shell/clear")
def shell_clear():
    owner, err = _owner_or_403()
    if err:
        return err
    shell_capture.clear(owner["id"])
    security.audit(owner["id"], "shell_history_cleared")
    return shell_status()


@app.post("/api/gate/open")
def gate_open():
    return jsonify(gate.open_gate())


@app.post("/api/gate/close")
def gate_close():
    return jsonify(gate.close_gate())


@app.get("/api/gate/today")
def gate_today():
    return jsonify(day=gate.public_day(gate.today()), gate=gate.state(),
                   hint_delay=load_config()["hint_delay_seconds"])


@app.post("/api/gate/answer")
def gate_answer():
    b = body()
    return jsonify(gate.answer_gate(b["question_id"], b))


@app.get("/api/review")
def review_list():
    due = sorted(gate.due_concepts(), key=lambda c: (c.get("status") != "relearn", c["next_due"]))
    return jsonify(due=[{k: v for k, v in c.items() if k not in ("history", "pending")} for c in due],
                   hint_delay=load_config()["hint_delay_seconds"])


@app.post("/api/review/<cid>/question")
def review_question(cid):
    return jsonify(gate.review_question(cid))


@app.post("/api/review/<cid>/answer")
def review_answer(cid):
    return jsonify(gate.answer_review(cid, body()))


@app.get("/api/vault")
def vault():
    items = sorted(gate.vault().values(), key=lambda c: c.get("created", ""), reverse=True)
    for c in items:
        c.pop("pending", None)
    return jsonify(concepts=items)


@app.get("/api/stats")
def stats():
    return jsonify(stats_mod.stats())


@app.get("/api/config")
def get_config():
    return jsonify(load_config())


@app.put("/api/config")
def put_config():
    b = body()
    cfg = load_config()
    for key in DEFAULT_CONFIG:
        if key in b and key not in PROTECTED_CONFIG:  # the terminal switch has its own guarded route
            cfg[key] = b[key]
    cfg["repos"] = [str(Path(r).expanduser()) for r in cfg.get("repos", []) if str(r).strip()]
    save_config(cfg)
    return jsonify(cfg)


@app.post("/api/hook/install")
def hook_install_route():
    return jsonify(hook_install.install())


# ---------- front end ----------

@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path):
    if path.startswith("api/"):
        return jsonify(error="not found"), 404
    if path and (STATIC / path).is_file():
        return send_from_directory(STATIC, path)
    if (STATIC / "index.html").exists():
        return send_from_directory(STATIC, "index.html")
    return "Front end not built yet. Run: cd frontend && npm install && npm run build", 200


if __name__ == "__main__":
    print(f"ADDGate running at http://localhost:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
