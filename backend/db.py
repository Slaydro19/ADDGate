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
SCHEMA_VERSION = 5
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


# Upgrades applied in order on top of SCHEMA. Only ever append; never edit a shipped step.
MIGRATIONS = {
    2: [
        # usage: tokens that count (excludes cheap cache reads)
        "ALTER TABLE usage ADD COLUMN work_tokens INTEGER NOT NULL DEFAULT 0",
        # questions: multiple choice + how it was answered
        "ALTER TABLE questions ADD COLUMN choices TEXT",          # JSON [{text, misconception}]
        "ALTER TABLE questions ADD COLUMN correct INTEGER",       # index into choices
        "ALTER TABLE questions ADD COLUMN choice INTEGER",        # what they picked
        "ALTER TABLE questions ADD COLUMN confidence TEXT",
        "ALTER TABLE questions ADD COLUMN flags TEXT",            # JSON honesty signals
        # attempts: same signals, for history and didn't-hold tracking
        "ALTER TABLE attempts ADD COLUMN confidence TEXT",
        "ALTER TABLE attempts ADD COLUMN choice_correct INTEGER",
        "ALTER TABLE attempts ADD COLUMN looked_up INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE attempts ADD COLUMN flags TEXT",
    ],
    3: [
        # the owner (first account) is the only one who can use the terminal
        "ALTER TABLE users ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0",
        "UPDATE users SET is_owner = 1 WHERE id = (SELECT id FROM users ORDER BY created, rowid LIMIT 1)",
        """CREATE TABLE IF NOT EXISTS audit (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            at      TEXT NOT NULL,
            event   TEXT NOT NULL,
            detail  TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS audit_at ON audit (at)",
    ],
    4: [
        # commands you typed yourself (owner only), already redacted
        """CREATE TABLE IF NOT EXISTS shell_commands (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            started_at TEXT NOT NULL,
            ended_at   TEXT NOT NULL,
            exit_code  INTEGER,
            cwd        TEXT NOT NULL,
            source     TEXT NOT NULL CHECK (source IN ('terminal', 'shell')),
            command    TEXT NOT NULL,
            redacted   INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS shell_commands_time ON shell_commands (user_id, started_at)",
    ],
    5: [
        # admin role, account controls and per-account Claude usage
        "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0",   # bump to sign an account out everywhere
        "ALTER TABLE users ADD COLUMN last_login TEXT",
        "ALTER TABLE users ADD COLUMN last_seen TEXT",
        "UPDATE users SET is_admin = 1 WHERE is_owner = 1",                         # the first account starts as admin
        "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS usage_user (
            user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day         TEXT NOT NULL,
            work_tokens INTEGER NOT NULL DEFAULT 0,
            calls       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day)
        )""",
    ],
}


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
    if version < 1:
        conn.executescript(SCHEMA)
        version = 1
        conn.execute("PRAGMA user_version = 1")
    for target in sorted(MIGRATIONS):
        if version < target:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in MIGRATIONS[target]:
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {int(target)}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            version = target
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
