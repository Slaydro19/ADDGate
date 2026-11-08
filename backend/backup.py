"""Database backups in ~/gate/backups: manual, automatic daily, and the safety copies taken before
risky admin actions. Restoring replaces the live database, so it always takes a safety copy first."""
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime

import db
from config import GATE_HOME

DIR = GATE_HOME / "backups"
NAME_RE = re.compile(r"^addgate-(\d{8})-(\d{6})(?:-([a-z-]+))?\.db$")
KEEP_AUTO = 14                  # automatic daily backups kept; manual and safety copies are never pruned
_last_check = 0.0


def _info(path):
    m = NAME_RE.match(path.name)
    st = path.stat()
    return {"name": path.name, "kind": (m.group(3) if m and m.group(3) else "manual"),
            "size": st.st_size, "created": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat()}


def create(kind="manual"):
    DIR.mkdir(parents=True, exist_ok=True)
    DIR.chmod(0o700)
    while True:
        name = f"addgate-{datetime.now():%Y%m%d-%H%M%S}" + (f"-{kind}" if kind != "manual" else "") + ".db"
        dest = DIR / name
        if not dest.exists():
            break
        time.sleep(1.05)  # one backup per second per kind
    with closing(sqlite3.connect(dest)) as out:
        db.connect().backup(out)  # a consistent copy even while ADDGate is running
    dest.chmod(0o600)
    return _info(dest)


def list_all():
    if not DIR.exists():
        return []
    items = [_info(p) for p in DIR.iterdir() if NAME_RE.match(p.name)]
    return sorted(items, key=lambda i: i["created"], reverse=True)


def prune():
    autos = [i for i in list_all() if i["kind"] == "auto"]
    for old in autos[KEEP_AUTO:]:
        (DIR / old["name"]).unlink(missing_ok=True)


def maybe_daily():
    """Called as people use the app: one automatic backup a day, checked at most once an hour."""
    global _last_check
    if time.time() - _last_check < 3600:
        return None
    _last_check = time.time()
    today = datetime.now().strftime("%Y%m%d")
    if any(i["kind"] == "auto" and i["name"].startswith(f"addgate-{today}") for i in list_all()):
        return None
    made = create("auto")
    prune()
    return made


def _path(name):
    if not NAME_RE.match(name or ""):
        raise KeyError("No such backup.")
    path = DIR / name
    if not path.is_file():
        raise KeyError("No such backup.")
    return path


def delete(name):
    _path(name).unlink()


def restore(name):
    """Replace the live database with a backup. Takes a safety copy first and checks the file is ADDGate's."""
    path = _path(name)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("That backup file is damaged.")
        if not src.execute("SELECT 1 FROM sqlite_master WHERE name = 'users'").fetchone():
            raise ValueError("That file isn't an ADDGate backup.")
        safety = create("pre-restore")
        src.backup(db.connect())
    db.init()  # bring an older backup up to the current schema
    return safety
