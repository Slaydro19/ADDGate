"""ADDGate local server. Serves the API on /api and the built React app on /.
Binds to 127.0.0.1 only: nothing is reachable from other machines."""
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session

import capture
import db
import migrate
import claude_client as cc
import gate
import hook_install
import users
from config import DEFAULT_CONFIG, SECRET_FILE, ensure_dirs, load_config, save_config, use_user

STATIC = Path(__file__).parent / "static"
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


# ---------- request guards ----------

@app.before_request
def guard():
    use_user(None)
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


@app.errorhandler(cc.ClaudeError)
def claude_error(e):
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
    user = users.authenticate(b.get("username"), b.get("password"))
    session.clear()
    session.permanent = bool(b.get("remember", True))
    session["uid"] = user["id"]
    return jsonify(user=users.public(user))


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.post("/api/auth/password")
def password():
    b = body()
    users.change_password(session["uid"], b.get("current"), b.get("new"))
    return jsonify(ok=True)


# ---------- Claude connection + usage (shared by the whole machine) ----------

@app.get("/api/status")
def status():
    fresh = request.args.get("refresh") == "1"
    if fresh or not _conn_cache["value"] or time.time() - _conn_cache["at"] > 600:
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
    for s in sessions:
        end = s["end"] or ""
        if st["status"] == "closed":  # quizzed already unless worked on after the close
            s["after_open"] = end > (st.get("closed_at") or "")
        else:
            s["after_open"] = end >= st["opened_at"]
    cfg = load_config()
    return jsonify(gate=st, sessions=sessions, commits=capture.git_commits(),
                   hook=hook_install.status(), repos=cfg.get("repos", []),
                   due=len(gate.due_concepts()))


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
    return jsonify(gate.answer_gate(b["question_id"], b.get("answer", "")))


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
    return jsonify(gate.answer_review(cid, body().get("answer", "")))


@app.get("/api/vault")
def vault():
    items = sorted(gate.vault().values(), key=lambda c: c.get("created", ""), reverse=True)
    for c in items:
        c.pop("pending", None)
    return jsonify(concepts=items)


@app.get("/api/config")
def get_config():
    return jsonify(load_config())


@app.put("/api/config")
def put_config():
    b = body()
    cfg = load_config()
    for key in DEFAULT_CONFIG:
        if key in b:
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
    port = int(os.environ.get("ADDGATE_PORT", 5055))
    print(f"ADDGate running at http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
