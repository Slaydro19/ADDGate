"""Local accounts, stored in the users table. Passwords are hashed with scrypt (werkzeug)."""
import re
import secrets
import sqlite3
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

import db

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
MIN_PASSWORD = 8
# A dummy hash so a login with an unknown username takes as long as a real one.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class AuthError(Exception):
    pass


TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes (0/O, 1/l/I)


def public(user):
    return {"id": user["id"], "username": user["username"], "display_name": user["display_name"],
            "created": user["created"], "is_owner": bool(user.get("is_owner")),
            "is_admin": bool(user.get("is_admin")), "must_change_password": bool(user.get("must_change_password"))}


def temp_password():
    return "".join(secrets.choice(TEMP_ALPHABET) for _ in range(14))


def get(user_id):
    return db.one("SELECT * FROM users WHERE id = ?", (user_id,))


def has_users():
    return db.one("SELECT 1 AS x FROM users LIMIT 1") is not None


def create(username, password, display_name="", is_admin=False, must_change=False):
    """Returns (user, is_first_account). The first account owns this Mac and is an admin."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise AuthError("Username must be 3–32 characters: letters, numbers, dot, dash or underscore.")
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    user = {"id": secrets.token_hex(8), "username": username,
            "display_name": (display_name or "").strip()[:60] or username,
            "password_hash": generate_password_hash(password),
            "created": datetime.now().astimezone().isoformat()}
    try:
        with db.write() as c:
            first = c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            user["is_owner"] = int(first)  # first account on this Mac owns it (terminal)
            user["is_admin"] = int(first or is_admin)
            user["must_change_password"] = int(bool(must_change))
            c.execute("INSERT INTO users (id, username, display_name, password_hash, created, is_owner, is_admin, "
                      "must_change_password, last_login, last_seen) VALUES (:id, :username, :display_name, "
                      ":password_hash, :created, :is_owner, :is_admin, :must_change_password, :login, :login)",
                      {**user, "login": None if (is_admin or must_change) and not first else user["created"]})
    except sqlite3.IntegrityError:
        raise AuthError("That username is taken.")
    return user, first


def authenticate(username, password):
    user = db.one("SELECT * FROM users WHERE username = ?", ((username or "").strip(),))
    if not user:
        check_password_hash(_DUMMY_HASH, password or "")
        raise AuthError("Wrong username or password.")
    if not check_password_hash(user["password_hash"], password or ""):
        raise AuthError("Wrong username or password.")
    if user.get("disabled"):  # said only after the right password, so it can't be used to probe usernames
        raise AuthError("This account is turned off. Ask an admin to turn it back on.")
    with db.write() as c:
        c.execute("UPDATE users SET last_login = ?, last_seen = ? WHERE id = ?",
                  (_now(), _now(), user["id"]))
    return user


def check_password(user_id, password):
    user = get(user_id)
    return bool(user) and check_password_hash(user["password_hash"], password or "")


def change_password(user_id, current, new):
    user = get(user_id)
    if not user or not check_password_hash(user["password_hash"], current or ""):
        raise AuthError("Current password is wrong.")
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    with db.write() as c:  # a new password also signs out every other browser
        c.execute("UPDATE users SET password_hash = ?, must_change_password = 0, session_epoch = session_epoch + 1 "
                  "WHERE id = ?", (generate_password_hash(new), user_id))
    return get(user_id)["session_epoch"]


def reset_password(username, new):
    """For the command-line reset tool (no email on a local app)."""
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    with db.write() as c:
        n = c.execute("UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE username = ?",
                      (generate_password_hash(new), username)).rowcount
    if not n:
        raise AuthError(f"No account named {username}.")


# ---------- admin operations ----------

_seen_at = {}


def _now():
    return datetime.now().astimezone().isoformat()


def touch_seen(user_id):
    """Last-active time, written at most every 5 minutes per account."""
    import time
    if time.time() - _seen_at.get(user_id, 0) < 300:
        return
    _seen_at[user_id] = time.time()
    with db.write() as c:
        c.execute("UPDATE users SET last_seen = ? WHERE id = ?", (_now(), user_id))


def find(username):
    return db.one("SELECT * FROM users WHERE username = ?", ((username or "").strip(),))


def active_admins(excluding=None):
    """Enabled admin accounts, optionally not counting one (to protect the last admin)."""
    rows = db.all_rows("SELECT id FROM users WHERE is_admin = 1 AND disabled = 0")
    return [r for r in rows if r["id"] != excluding]


def set_admin(user_id, value):
    with db.write() as c:
        c.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(bool(value)), user_id))


def set_disabled(user_id, value):
    with db.write() as c:  # turning an account off also signs it out
        c.execute("UPDATE users SET disabled = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                  (int(bool(value)), user_id))


def sign_out_everywhere(user_id):
    with db.write() as c:
        c.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (user_id,))


def set_temp_password(user_id):
    """Returns the temporary password. It is shown once; the person must choose their own at next sign-in."""
    temp = temp_password()
    with db.write() as c:
        c.execute("UPDATE users SET password_hash = ?, must_change_password = 1, session_epoch = session_epoch + 1 "
                  "WHERE id = ?", (generate_password_hash(temp), user_id))
    return temp


def delete(user_id):
    with db.write() as c:  # concepts, attempts, quizzes, settings and usage cascade
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _seen_at.pop(user_id, None)


def set_admin_cli(username, value):
    user = find(username)
    if not user:
        raise AuthError(f"No account named {username}.")
    set_admin(user["id"], value)
