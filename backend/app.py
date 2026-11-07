"""ADDGate local server. Serves the API on /api and the built React app on /.
Binds to 127.0.0.1 only: nothing is reachable from other machines."""
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import capture
import claude_client as cc
import gate
import hook_install
from config import ensure_dirs, load_config, save_config, DEFAULT_CONFIG

STATIC = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=None)
_conn_cache = {"at": 0, "value": None}


@app.errorhandler(cc.ClaudeError)
def claude_error(e):
    code = {"limit": 429, "missing": 503, "auth": 401, "empty": 409}.get(e.kind, 502)
    return jsonify(error=str(e), kind=e.kind), code


@app.errorhandler(KeyError)
def not_found(e):
    return jsonify(error=str(e).strip("'")), 404


@app.get("/api/status")
def status():
    fresh = request.args.get("refresh") == "1"
    if fresh or not _conn_cache["value"] or time.time() - _conn_cache["at"] > 600:
        _conn_cache.update(at=time.time(), value=cc.check_connection())
    return jsonify(_conn_cache["value"])


@app.get("/api/usage")
def usage():
    return jsonify(cc.usage_today())


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
    body = request.get_json(force=True)
    return jsonify(gate.answer_gate(body["question_id"], body.get("answer", "")))


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
    body = request.get_json(force=True)
    return jsonify(gate.answer_review(cid, body.get("answer", "")))


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
    body = request.get_json(force=True)
    cfg = load_config()
    for key in DEFAULT_CONFIG:
        if key in body:
            cfg[key] = body[key]
    cfg["repos"] = [str(Path(r).expanduser()) for r in cfg.get("repos", []) if str(r).strip()]
    save_config(cfg)
    return jsonify(cfg)


@app.post("/api/hook/install")
def hook_install_route():
    return jsonify(hook_install.install())


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
    ensure_dirs()
    port = int(os.environ.get("ADDGATE_PORT", 5055))
    print(f"ADDGate running at http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
