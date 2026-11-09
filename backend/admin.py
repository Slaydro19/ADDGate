"""Admin console API (/api/admin/...). Admin accounts only.

Privacy line: an admin sees who has an account and how much it is used (counts, dates, token totals),
never anyone's answers, vault, transcripts or typed commands. Nothing here reads that content.

Destructive actions (delete, restore, reset password, change a role) need the admin to re-enter their
own password within the last 15 minutes, and every action is written to the audit log."""
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, request, session

import appsettings
import backup
import claude_client as cc
import db
import hook_install
import security
import terminal
import users
from config import APP_VERSION, DEFAULT_CONFIG, GATE_HOME

bp = Blueprint("admin", __name__, url_prefix="/api/admin")
STARTED = time.time()


def body():
    return request.get_json(silent=True) or {}


def _admin():
    user = users.get(session.get("uid"))
    return user if user and user.get("is_admin") and not user.get("disabled") else None


@bp.before_request
def admins_only():
    if not _admin():
        return jsonify(error="Admins only.", kind="forbidden"), 403
    return None


def _need_reauth():
    if time.time() - float(session.get("reauth_at") or 0) >= terminal.REAUTH_TTL:
        return jsonify(error="Confirm your password to continue.", kind="reauth"), 403
    return None


def _log(event, target=None, detail=""):
    # the signed-in account, even if this very action just ended its admin role
    text = (f"{target['username']}" if target else "") + (f" · {detail}" if detail else "")
    security.audit(session.get("uid"), event, text.strip(" ·"))


def _target(uid):
    user = users.get(uid)
    if not user:
        raise KeyError("No such account.")
    return user


def _is_last_admin(user):
    """True when this account is an enabled admin and no other enabled admin exists."""
    return bool(user.get("is_admin")) and not user.get("disabled") and not users.active_admins(excluding=user["id"])


def _user_row(r):
    cfg = db.loads(r.pop("cfg"), {}) or {}
    r["account_token_cap"] = int(cfg.get("account_token_cap") or 0)
    r["locked"] = security.login_blocked(r["username"]) > 0
    for k in ("is_admin", "is_owner", "disabled", "must_change_password"):
        r[k] = bool(r[k])
    r["tokens_today"] = int(r["tokens_today"] or 0)
    return r


def _users():
    today = date.today().isoformat()
    week = (date.today() - timedelta(days=6)).isoformat()
    rows = db.all_rows(
        "SELECT u.id, u.username, u.display_name, u.created, u.last_login, u.last_seen, u.is_admin, u.is_owner, "
        "u.disabled, u.must_change_password, "
        "(SELECT COUNT(*) FROM concepts c WHERE c.user_id = u.id) AS concepts, "
        "(SELECT COUNT(*) FROM concepts c WHERE c.user_id = u.id AND c.status = 'owned') AS owned, "
        "(SELECT COUNT(*) FROM attempts a WHERE a.user_id = u.id) AS attempts, "
        "(SELECT COUNT(*) FROM days d WHERE d.user_id = u.id) AS gates, "
        "(SELECT MAX(day) FROM days d WHERE d.user_id = u.id) AS last_gate, "
        "(SELECT work_tokens FROM usage_user x WHERE x.user_id = u.id AND x.day = ?) AS tokens_today, "
        "(SELECT COALESCE(SUM(work_tokens), 0) FROM usage_user x WHERE x.user_id = u.id AND x.day >= ?) AS tokens_week, "
        "(SELECT data FROM user_config k WHERE k.user_id = u.id) AS cfg "
        "FROM users u ORDER BY u.created", (today, week))
    return [_user_row(r) for r in rows]


@bp.get("/overview")
def overview():
    return jsonify(users=_users(), settings=appsettings.get(), me=users.public(_admin()))


# ---------- accounts ----------

@bp.post("/users")
def create_user():
    b = body()
    temp = None
    password = b.get("password")
    if not password:
        password = temp = users.temp_password()
    user, _ = users.create(b.get("username"), password, b.get("display_name"),
                           is_admin=bool(b.get("is_admin")), must_change=True)
    appsettings.apply_new_account_defaults(user["id"])
    _log("admin_user_created", user, "admin" if user["is_admin"] else "")
    return jsonify(user=users.public(user), temp_password=temp)


@bp.post("/users/<uid>/role")
def set_role(uid):
    err = _need_reauth()
    if err:
        return err
    user, make = _target(uid), bool(body().get("is_admin"))
    if not make and _is_last_admin(user):
        return jsonify(error="That's the last admin. Make someone else an admin first.", kind="guard"), 409
    users.set_admin(uid, make)
    _log("admin_made" if make else "admin_removed", user)
    return jsonify(ok=True)


@bp.post("/users/<uid>/disabled")
def set_disabled(uid):
    user, off = _target(uid), bool(body().get("disabled"))
    if off and user["id"] == _admin()["id"]:
        return jsonify(error="You can't turn off your own account.", kind="guard"), 409
    if off and _is_last_admin(user):
        return jsonify(error="That's the last admin. Make someone else an admin first.", kind="guard"), 409
    users.set_disabled(uid, off)
    if off:
        terminal.close_all(uid, "account turned off")
    _log("account_disabled" if off else "account_enabled", user)
    return jsonify(ok=True)


@bp.post("/users/<uid>/reset-password")
def reset_password(uid):
    err = _need_reauth()
    if err:
        return err
    user = _target(uid)
    temp = users.set_temp_password(uid)
    terminal.close_all(uid, "password reset")
    _log("password_reset", user)
    return jsonify(temp_password=temp)  # shown once; the person must choose their own at next sign-in


@bp.post("/users/<uid>/unlock")
def unlock(uid):
    user = _target(uid)
    security.unlock(user["username"])
    security.unlock(f"confirm:{uid}")
    _log("account_unlocked", user)
    return jsonify(ok=True)


@bp.post("/users/<uid>/signout")
def sign_out(uid):
    user = _target(uid)
    users.sign_out_everywhere(uid)
    terminal.close_all(uid, "signed out by an admin")
    _log("signed_out_by_admin", user)
    return jsonify(ok=True)


@bp.post("/users/<uid>/cap")
def set_cap(uid):
    user = _target(uid)
    try:
        cap = max(0, min(100_000_000, int(body().get("cap"))))
    except (TypeError, ValueError):
        return jsonify(error="The cap must be a number of tokens (0 = no cap).", kind="bad_request"), 400
    row = db.one("SELECT data FROM user_config WHERE user_id = ?", (uid,))
    cfg = db.loads(row["data"], {}) if row else {}
    cfg["account_token_cap"] = cap
    with db.write() as c:
        c.execute("INSERT INTO user_config (user_id, data) VALUES (?, ?) "
                  "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data", (uid, db.dumps(cfg)))
    _log("token_cap_set", user, f"{cap} tokens a day" if cap else "no cap")
    return jsonify(ok=True, cap=cap)


@bp.delete("/users/<uid>")
def delete_user(uid):
    err = _need_reauth()
    if err:
        return err
    user = _target(uid)
    if user["id"] == _admin()["id"]:
        return jsonify(error="You can't delete your own account.", kind="guard"), 409
    if _is_last_admin(user):
        return jsonify(error="That's the last admin. Make someone else an admin first.", kind="guard"), 409
    if (body().get("confirm") or "").strip().lower() != user["username"].lower():
        return jsonify(error="Type the account's username to confirm.", kind="guard"), 400
    saved = backup.create("pre-delete")  # always keep a way back
    terminal.close_all(uid, "account deleted")
    users.delete(uid)
    _log("account_deleted", user, f"backup {saved['name']}")
    return jsonify(ok=True, backup=saved["name"])


# ---------- sign-up policy and defaults for new accounts ----------

@bp.get("/settings")
def get_settings():
    return jsonify(appsettings.get())


@bp.put("/settings")
def put_settings():
    b = body()
    try:
        out = appsettings.update(b.get("signup_mode"), b.get("new_account"))
    except ValueError as e:
        return jsonify(error=str(e), kind="bad_request"), 400
    _log("settings_changed", None, f"sign-up {out['signup_mode']}")
    return jsonify(out)


# ---------- backups ----------

@bp.get("/backups")
def list_backups():
    return jsonify(backups=backup.list_all(), keep_auto=backup.KEEP_AUTO)


@bp.post("/backups")
def make_backup():
    made = backup.create("manual")
    _log("backup_created", None, made["name"])
    return jsonify(backup=made, backups=backup.list_all())


@bp.delete("/backups/<name>")
def delete_backup(name):
    backup.delete(name)
    _log("backup_deleted", None, name)
    return jsonify(backups=backup.list_all())


@bp.post("/backups/<name>/restore")
def restore_backup(name):
    err = _need_reauth()
    if err:
        return err
    if body().get("confirm") != "RESTORE":
        return jsonify(error="Type RESTORE to confirm.", kind="guard"), 400
    admin = _admin()
    try:
        safety = backup.restore(name)
    except ValueError as e:
        return jsonify(error=str(e), kind="bad_request"), 400
    # the restored database may not contain this admin; the log entry goes in if it still does
    if users.get(admin["id"]):
        security.audit(admin["id"], "backup_restored", f"{name} (safety copy {safety['name']})")
    return jsonify(ok=True, safety=safety["name"])


# ---------- health and audit ----------

@bp.get("/health")
def health():
    conn = current_app.config.get("ADDGATE_CONN_CACHE", {}).get("value") or {}
    items = backup.list_all()
    db_file = db.DB_FILE
    schema = db.connect().execute("PRAGMA user_version").fetchone()[0]
    return jsonify(
        version=APP_VERSION, python=sys.version.split()[0], schema=schema,
        uptime_seconds=int(time.time() - STARTED),
        claude={"connected": bool(conn.get("connected")), "checked": bool(conn), "message": conn.get("message"),
                "binary": cc.claude_path()},
        hook=hook_install.status(),
        database={"size": db_file.stat().st_size if db_file.exists() else 0, "path": "~/gate/addgate.db"},
        accounts={"total": db.one("SELECT COUNT(*) AS n FROM users")["n"], "admins": len(users.active_admins()),
                  "disabled": db.one("SELECT COUNT(*) AS n FROM users WHERE disabled = 1")["n"]},
        backups={"count": len(items), "latest": items[0]["created"] if items else None},
        usage_today=cc.usage_today_all())


@bp.get("/audit")
def audit():
    return jsonify(events=security.recent_audit(request.args.get("limit", 100),
                                                request.args.get("user") or None, request.args.get("event") or None))
