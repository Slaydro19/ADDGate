"""One-time import of the JSON files older versions wrote into ~/gate, into addgate.db.

Handles:
  v2.2  users.json + users/<id>/{config,state,vault}.json + users/<id>/days/
  v2.1  config.json, state.json, vault.json, days/ loose in ~/gate (no accounts yet):
        held until the first account is created, then adopted by it
  both  usage.json
Each imported file or folder is renamed with an .imported suffix, never deleted, so you can
check it and remove it yourself. Anything in an unexpected shape (like the May CLI's files)
is skipped and left alone."""
import logging
from pathlib import Path

import db
from config import GATE_HOME, read_json

log = logging.getLogger("addgate.migrate")
STATUSES = {"new", "owned", "partial", "borrowed", "relearn"}
VERDICTS = {"owned", "partial", "borrowed"}
CONFIG_KEYS = {"repos", "model", "daily_token_budget", "questions_per_close", "hint_delay_seconds",
               "review_intervals_days"}


def _retire(path):
    path = Path(path)
    if path.exists():
        target = path.with_name(path.name + ".imported")
        n = 1
        while target.exists():
            n += 1
            target = path.with_name(f"{path.name}.imported{n}")
        path.rename(target)


def _import_user_data(c, uid, folder):
    """Import config/state/vault/days for one user from a folder. Returns counts."""
    folder = Path(folder)
    counts = {"concepts": 0, "attempts": 0, "days": 0, "questions": 0, "day_files": []}

    cfg = read_json(folder / "config.json", None)
    if isinstance(cfg, dict):
        clean = {k: v for k, v in cfg.items() if k in CONFIG_KEYS}
        c.execute("INSERT OR REPLACE INTO user_config (user_id, data) VALUES (?, ?)", (uid, db.dumps(clean)))

    st = read_json(folder / "state.json", None)
    if isinstance(st, dict) and st.get("status") in ("open", "closed") and st.get("opened_at"):
        c.execute("INSERT OR REPLACE INTO gate_state (user_id, status, opened_at, closed_at) VALUES (?, ?, ?, ?)",
                  (uid, st["status"], st["opened_at"], st.get("closed_at")))

    vault = read_json(folder / "vault.json", None)
    if isinstance(vault, dict):
        for slug, con in vault.items():
            if not isinstance(con, dict) or not con.get("name"):
                continue
            status = con.get("status") if con.get("status") in STATUSES else "new"
            c.execute("INSERT OR IGNORE INTO concepts (user_id, slug, name, category, why, status, interval_index, "
                      "fails, next_due, last_question, pending, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (uid, slug, con["name"], con.get("category", ""), con.get("why", ""), status,
                       int(con.get("interval_index", -1)), int(con.get("fails", 0)), con.get("next_due"),
                       con.get("last_question", ""), db.dumps(con["pending"]) if con.get("pending") else None,
                       con.get("created") or "1970-01-01"))
            counts["concepts"] += 1
            for h in con.get("history", []) or []:
                if h.get("verdict") in VERDICTS and h.get("source") in ("gate", "review"):
                    c.execute("INSERT INTO attempts (user_id, slug, at, source, question, answer, verdict) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (uid, slug, h.get("date", ""), h["source"], h.get("question", ""),
                               h.get("answer") or "", h["verdict"]))
                    counts["attempts"] += 1

    days_dir = folder / "days"
    if days_dir.is_dir():
        for f in sorted(days_dir.glob("*.json")):
            d = read_json(f, None)
            qs = d.get("questions") if isinstance(d, dict) else None
            if not (isinstance(qs, list) and d.get("date") and d.get("closed_at")
                    and all(isinstance(q, dict) and "concept_id" in q for q in qs)):
                log.info("Skipping %s (not a v2 day file)", f)
                continue
            c.execute("INSERT OR IGNORE INTO days (user_id, day, closed_at, sessions, commits) VALUES (?, ?, ?, ?, ?)",
                      (uid, d["date"], d["closed_at"], db.dumps(d.get("sessions", [])), int(d.get("commits", 0))))
            counts["days"] += 1
            counts["day_files"].append(f)
            for pos, q in enumerate(qs):
                res = q.get("result") or {}
                verdict = res.get("verdict") if res.get("verdict") in VERDICTS else None
                c.execute("INSERT OR IGNORE INTO questions (id, user_id, day, position, slug, concept, category, why, "
                          "question, hint, rubric, model_answer, closed_at, answer, verdict, feedback) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (q.get("id") or f"{d['date']}-{pos}", uid, d["date"], pos, q["concept_id"],
                           q.get("concept", ""), q.get("category", ""), q.get("why", ""), q.get("question", ""),
                           q.get("hint", ""), db.dumps(q.get("rubric", [])), q.get("model_answer", ""),
                           q.get("closed_at") or d["closed_at"], q.get("answer"), verdict,
                           res.get("feedback") if verdict else None))
                counts["questions"] += 1
    return counts


def _import_usage(c):
    usage = read_json(GATE_HOME / "usage.json", None)
    if not isinstance(usage, dict):
        return 0
    for day, u in usage.items():
        if isinstance(u, dict):
            c.execute("INSERT OR IGNORE INTO usage (day, tokens, calls, cost_usd, limit_message) VALUES (?, ?, ?, ?, ?)",
                      (day, int(u.get("tokens", 0)), int(u.get("calls", 0)), float(u.get("cost_usd", 0)),
                       u.get("limit_message")))
    return len(usage)


def run():
    """Import everything importable. Safe to call on every start."""
    users_file, users_dir = GATE_HOME / "users.json", GATE_HOME / "users"
    imported_users = []
    with db.write() as c:
        accounts = read_json(users_file, None)
        if isinstance(accounts, dict):
            for u in accounts.values():
                if not all(k in u for k in ("id", "username", "password_hash")):
                    continue
                c.execute("INSERT OR IGNORE INTO users (id, username, display_name, password_hash, created) "
                          "VALUES (?, ?, ?, ?, ?)",
                          (u["id"], u["username"], u.get("display_name") or u["username"], u["password_hash"],
                           u.get("created") or "1970-01-01"))
                counts = _import_user_data(c, u["id"], users_dir / u["id"])
                counts.pop("day_files")
                imported_users.append((u["username"], counts))
        usage_days = _import_usage(c)
    if imported_users:
        _retire(users_file)
        _retire(users_dir)
        for name, counts in imported_users:
            print(f"Imported account {name}: {counts}")
    if usage_days:
        _retire(GATE_HOME / "usage.json")


def has_legacy_data():
    """v2.1 wrote vault.json/state.json; the May CLI never did, so its files are left alone."""
    return (GATE_HOME / "vault.json").exists() or (GATE_HOME / "state.json").exists()


def adopt_legacy(uid):
    """Give pre-account data (v2.1 layout) to the first account created."""
    if not has_legacy_data():
        return None
    with db.write() as c:
        counts = _import_user_data(c, uid, GATE_HOME)
    for name in ("state.json", "vault.json"):  # config.json may be shared with the May CLI, so it stays
        _retire(GATE_HOME / name)
    for f in counts.pop("day_files"):  # only v2 day files; May CLI files in days/ stay put
        _retire(f)
    print(f"First account adopted earlier ADDGate data: {counts}")
    return counts
