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


def public(user):
    return {"id": user["id"], "username": user["username"], "display_name": user["display_name"],
            "created": user["created"], "is_owner": bool(user.get("is_owner"))}


def get(user_id):
    return db.one("SELECT * FROM users WHERE id = ?", (user_id,))


def has_users():
    return db.one("SELECT 1 AS x FROM users LIMIT 1") is not None


def create(username, password, display_name=""):
    """Returns (user, is_first_account)."""
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
            user["is_owner"] = int(first)  # first account on this Mac owns it (terminal, admin)
            c.execute("INSERT INTO users (id, username, display_name, password_hash, created, is_owner) "
                      "VALUES (:id, :username, :display_name, :password_hash, :created, :is_owner)", user)
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
    with db.write() as c:
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), user_id))


def reset_password(username, new):
    """For the command-line reset tool (no email on a local app)."""
    if len(new or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    with db.write() as c:
        n = c.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                      (generate_password_hash(new), username)).rowcount
    if not n:
        raise AuthError(f"No account named {username}.")
