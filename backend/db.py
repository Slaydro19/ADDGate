"""SQLite storage for ADDGate: one file at ~/gate/addgate.db.

- WAL mode, so reads never block writes.
- One connection per thread (Flask serves requests on threads).
- write() opens a BEGIN IMMEDIATE transaction: read-modify-write sequences can't
  interleave, which is what JSON files couldn't guarantee.
- Every query uses ? parameters, never string formatting, so input can't inject SQL.
All SQL lives in this module and gate.py/users.py, so swapping engines later is contained."""
import json
import sqlite3
import threading
from contextlib import contextmanager

from config import GATE_HOME

DB_FILE = GATE_HOME / "addgate.db"
SCHEMA_VERSION = 1
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_config (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data    TEXT NOT NULL                       -- JSON object of settings
);

CREATE TABLE IF NOT EXISTS gate_state (
    user_id   TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    status    TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    opened_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS concepts (
    user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug           TEXT NOT NULL,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT '',
    why            TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'new'
                   CHECK (status IN ('new', 'owned', 'partial', 'borrowed', 'relearn')),
    interval_index INTEGER NOT NULL DEFAULT -1,
    fails          INTEGER NOT NULL DEFAULT 0,
    next_due       TEXT,                          -- YYYY-MM-DD
    last_question  TEXT NOT NULL DEFAULT '',
    pending        TEXT,                          -- JSON: review question waiting for an answer
    created        TEXT NOT NULL,
    PRIMARY KEY (user_id, slug)
);
CREATE INDEX IF NOT EXISTS concepts_due ON concepts (user_id, next_due);

CREATE TABLE IF NOT EXISTS attempts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  TEXT NOT NULL,
    slug     TEXT NOT NULL,
    at       TEXT NOT NULL,
    source   TEXT NOT NULL CHECK (source IN ('gate', 'review')),
    question TEXT NOT NULL,
    answer   TEXT NOT NULL DEFAULT '',
    verdict  TEXT NOT NULL CHECK (verdict IN ('owned', 'partial', 'borrowed')),
    FOREIGN KEY (user_id, slug) REFERENCES concepts(user_id, slug) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS attempts_concept ON attempts (user_id, slug, at);

CREATE TABLE IF NOT EXISTS days (
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day       TEXT NOT NULL,                      -- YYYY-MM-DD
    closed_at TEXT NOT NULL,
    sessions  TEXT NOT NULL DEFAULT '[]',         -- JSON list of session titles
    commits   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS questions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    day          TEXT NOT NULL,
    position     INTEGER NOT NULL,
    slug         TEXT NOT NULL,
    concept      TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    why          TEXT NOT NULL DEFAULT '',
    question     TEXT NOT NULL,
    hint         TEXT NOT NULL DEFAULT '',
    rubric       TEXT NOT NULL DEFAULT '[]',      -- JSON list
    model_answer TEXT NOT NULL DEFAULT '',
    closed_at    TEXT NOT NULL,
    answer       TEXT,
    verdict      TEXT CHECK (verdict IN ('owned', 'partial', 'borrowed')),
    feedback     TEXT,
    FOREIGN KEY (user_id, day) REFERENCES days(user_id, day) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS questions_day ON questions (user_id, day, position);

CREATE TABLE IF NOT EXISTS usage (                -- one Claude login per Mac, so shared
    day           TEXT PRIMARY KEY,
    tokens        INTEGER NOT NULL DEFAULT 0,
    calls         INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    limit_message TEXT
);
"""


def connect():
    conn = getattr(_local, "conn", None)
    if conn is None:
        GATE_HOME.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_FILE, timeout=30, isolation_level=None)  # autocommit; we manage txns
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


@contextmanager
def write():
    """Serialized write transaction. Rolls back on any error."""
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def one(sql, params=()):
    row = connect().execute(sql, params).fetchone()
    return dict(row) if row else None


def all_rows(sql, params=()):
    return [dict(r) for r in connect().execute(sql, params).fetchall()]


def init():
    conn = connect()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    if DB_FILE.exists():
        DB_FILE.chmod(0o600)  # contains password hashes


def dumps(value):
    return json.dumps(value)


def loads(text, default=None):
    if text is None:
        return default
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default
