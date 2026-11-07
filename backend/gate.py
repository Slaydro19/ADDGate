"""Gate open/close, quizzing, grading and the spaced-review schedule, on SQLite.

Slow Claude calls always happen OUTSIDE a transaction; the results are then written in one
short db.write() block that re-reads the row it changes, so parallel requests can't
overwrite each other."""
import re
import uuid
from datetime import date, datetime, timedelta

import capture
import claude_client as cc
import db
import prompts
from config import current_user, load_config

HIDDEN = ("rubric", "model_answer")


def now():
    return datetime.now().astimezone()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or uuid.uuid4().hex[:8]


# ---------- gate state ----------

def state():
    """A new day always starts with the gate open from midnight."""
    st = db.one("SELECT status, opened_at, closed_at FROM gate_state WHERE user_id = ?", (current_user(),))
    if st:
        key = "closed_at" if st["status"] == "closed" else "opened_at"
        if (st.get(key) or "")[:10] == date.today().isoformat():
            return st
    start_of_day = datetime.combine(date.today(), datetime.min.time()).astimezone()
    return {"status": "open", "opened_at": start_of_day.isoformat(), "closed_at": (st or {}).get("closed_at")}


def _save_state(c, status, opened_at, closed_at):
    c.execute("INSERT INTO gate_state (user_id, status, opened_at, closed_at) VALUES (?, ?, ?, ?) "
              "ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, "
              "opened_at = excluded.opened_at, closed_at = excluded.closed_at",
              (current_user(), status, opened_at, closed_at))


def open_gate():
    st = {"status": "open", "opened_at": now().isoformat(), "closed_at": state().get("closed_at")}
    with db.write() as c:
        _save_state(c, st["status"], st["opened_at"], st["closed_at"])
    return st


# ---------- concepts ----------

def _concept(row, history=None):
    out = {"id": row["slug"], "name": row["name"], "category": row["category"], "why": row["why"],
           "status": row["status"], "interval_index": row["interval_index"], "fails": row["fails"],
           "next_due": row["next_due"], "last_question": row["last_question"], "created": row["created"]}
    if history is not None:
        out["history"] = history
    return out


def vault():
    uid = current_user()
    rows = db.all_rows("SELECT * FROM concepts WHERE user_id = ? ORDER BY created DESC, name", (uid,))
    hist = {}
    for a in db.all_rows("SELECT slug, at, source, question, answer, verdict FROM attempts "
                         "WHERE user_id = ? ORDER BY at", (uid,)):
        hist.setdefault(a["slug"], []).append(
            {"date": a["at"], "source": a["source"], "question": a["question"],
             "answer": a["answer"], "verdict": a["verdict"]})
    return {r["slug"]: _concept(r, hist.get(r["slug"], [])) for r in rows}


def due_concepts():
    rows = db.all_rows("SELECT * FROM concepts WHERE user_id = ? AND next_due IS NOT NULL AND next_due <= ? "
                       "ORDER BY (status != 'relearn'), next_due", (current_user(), date.today().isoformat()))
    return [_concept(r) for r in rows]


def _schedule(c, slug_, verdict):
    """Apply a verdict to a concept inside an open write transaction."""
    row = c.execute("SELECT interval_index, fails FROM concepts WHERE user_id = ? AND slug = ?",
                    (current_user(), slug_)).fetchone()
    if not row:
        return
    intervals = load_config()["review_intervals_days"]
    idx, fails = row["interval_index"], row["fails"]
    if verdict == "owned":
        idx, fails, status = min(idx + 1, len(intervals) - 1), 0, "owned"
        days = intervals[idx]
    elif verdict == "partial":
        idx, status, days = max(idx - 1, -1), "partial", 1
    else:
        idx, fails = -1, fails + 1
        status, days = ("relearn" if fails >= 2 else "borrowed"), 1
    c.execute("UPDATE concepts SET status = ?, interval_index = ?, fails = ?, next_due = ?, pending = NULL "
              "WHERE user_id = ? AND slug = ?",
              (status, idx, fails, (date.today() + timedelta(days=days)).isoformat(), current_user(), slug_))


def _record(c, slug_, question, answer, verdict, source):
    c.execute("INSERT INTO attempts (user_id, slug, at, source, question, answer, verdict) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)",
              (current_user(), slug_, now().isoformat(), source, question, answer or "", verdict))
    _schedule(c, slug_, verdict)


def _concept_after(slug_):
    row = db.one("SELECT * FROM concepts WHERE user_id = ? AND slug = ?", (current_user(), slug_))
    return _concept(row) if row else None


# ---------- gate close + today's quiz ----------

def _question_out(q):
    out = {"id": q["id"], "concept_id": q["slug"], "concept": q["concept"], "category": q["category"],
           "why": q["why"], "question": q["question"], "hint": q["hint"], "closed_at": q["closed_at"],
           "answer": q["answer"], "result": None}
    if q["verdict"]:
        out["result"] = {"verdict": q["verdict"], "feedback": q["feedback"] or ""}
        out["model_answer"] = q["model_answer"]
    return out


def today():
    uid, day = current_user(), date.today().isoformat()
    d = db.one("SELECT * FROM days WHERE user_id = ? AND day = ?", (uid, day))
    if not d:
        return None
    qs = db.all_rows("SELECT * FROM questions WHERE user_id = ? AND day = ? ORDER BY position", (uid, day))
    return {"date": d["day"], "closed_at": d["closed_at"], "sessions": db.loads(d["sessions"], []),
            "commits": d["commits"], "questions": [_question_out(q) for q in qs]}


def public_day(d):
    return d  # today() already strips rubric and unanswered reference answers


def close_gate():
    uid = current_user()
    st = state()
    since = datetime.fromisoformat(st["opened_at"])
    sessions = capture.sessions_today(since=since)
    commits = capture.git_commits(since=since)
    real_commits = [c for c in commits if "hash" in c]
    if not sessions and not real_commits:
        raise cc.ClaudeError("Nothing captured since the gate opened. Do some work with Claude Code first.",
                             "empty")

    cfg = load_config()
    known_rows = db.all_rows("SELECT name FROM concepts WHERE user_id = ? ORDER BY name LIMIT 80", (uid,))
    known = ", ".join(r["name"] for r in known_rows) or "none yet"
    data = capture.transcript_for_llm(sessions) + capture.commits_for_llm(commits)
    # Slow part, outside any transaction:
    reply = cc.ask_json(prompts.CLOSE.format(n=cfg["questions_per_close"], known=known), data)
    concepts = reply.get("concepts", []) if isinstance(reply, dict) else reply

    stamp, day = now().isoformat(), date.today().isoformat()
    titles = [capture.summarize(s)["title"] for s in sessions]
    with db.write() as c:
        existing = c.execute("SELECT sessions, commits FROM days WHERE user_id = ? AND day = ?", (uid, day)).fetchone()
        all_titles = (db.loads(existing["sessions"], []) if existing else []) + titles
        c.execute("INSERT INTO days (user_id, day, closed_at, sessions, commits) VALUES (?, ?, ?, ?, ?) "
                  "ON CONFLICT(user_id, day) DO UPDATE SET closed_at = excluded.closed_at, "
                  "sessions = excluded.sessions, commits = days.commits + excluded.commits",
                  (uid, day, stamp, db.dumps(all_titles), len(real_commits)))
        pos = c.execute("SELECT COALESCE(MAX(position), -1) FROM questions WHERE user_id = ? AND day = ?",
                        (uid, day)).fetchone()[0]
        for item in concepts:
            if not isinstance(item, dict) or not item.get("name") or not item.get("question"):
                continue
            s = slug(item["name"])
            c.execute("INSERT INTO concepts (user_id, slug, name, category, why, last_question, created) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, slug) DO UPDATE SET "
                      "category = excluded.category, why = excluded.why, last_question = excluded.last_question",
                      (uid, s, item["name"], item.get("category", ""), item.get("why", ""), item["question"], day))
            pos += 1
            c.execute("INSERT INTO questions (id, user_id, day, position, slug, concept, category, why, question, "
                      "hint, rubric, model_answer, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (uuid.uuid4().hex[:12], uid, day, pos, s, item["name"], item.get("category", ""),
                       item.get("why", ""), item["question"], item.get("hint", ""),
                       db.dumps(item.get("rubric", [])), item.get("model_answer", ""), stamp))
        _save_state(c, "closed", st["opened_at"], stamp)
    return today()


# ---------- grading ----------

def grade(question, rubric, model_answer, answer):
    if not answer.strip() or answer.strip().lower() in ("idk", "i don't know", "i dont know", "pass"):
        return {"verdict": "borrowed", "feedback": "No answer, so this one goes to review. Read the answer below."}
    res = cc.ask_json(prompts.GRADE.format(question=question, rubric="; ".join(rubric),
                                           model_answer=model_answer), answer)
    verdict = res.get("verdict", "borrowed")
    if verdict not in ("owned", "partial", "borrowed"):
        verdict = "borrowed"
    return {"verdict": verdict, "feedback": res.get("feedback", "")}


def answer_gate(qid, answer):
    uid = current_user()
    q = db.one("SELECT * FROM questions WHERE id = ? AND user_id = ?", (qid, uid))
    if not q:
        raise KeyError("question not found")
    if q["verdict"]:  # already graded (double-click, second tab): don't grade or count it twice
        return {"verdict": q["verdict"], "feedback": q["feedback"] or "", "model_answer": q["model_answer"],
                "concept": _concept_after(q["slug"])}
    result = grade(q["question"], db.loads(q["rubric"], []), q["model_answer"], answer)
    with db.write() as c:
        c.execute("UPDATE questions SET answer = ?, verdict = ?, feedback = ? WHERE id = ? AND user_id = ?",
                  (answer, result["verdict"], result["feedback"], qid, uid))
        _record(c, q["slug"], q["question"], answer, result["verdict"], "gate")
    return {**result, "model_answer": q["model_answer"], "concept": _concept_after(q["slug"])}


# ---------- review ----------

def review_question(slug_):
    uid = current_user()
    row = db.one("SELECT * FROM concepts WHERE user_id = ? AND slug = ?", (uid, slug_))
    if not row:
        raise KeyError("concept not found")
    pending = db.loads(row["pending"])
    if pending:
        return {k: v for k, v in pending.items() if k not in HIDDEN}
    relearn = row["status"] == "relearn"
    res = cc.ask_json(prompts.REVIEW.format(
        name=row["name"], category=row["category"], why=row["why"], previous=row["last_question"],
        relearn=prompts.RELEARN_NOTE if relearn else "",
        lesson_field=prompts.LESSON_FIELD if relearn else ""))
    pending = {"concept_id": slug_, "question": res.get("question", ""), "hint": res.get("hint", ""),
               "lesson": res.get("lesson", ""), "rubric": res.get("rubric", []),
               "model_answer": res.get("model_answer", "")}
    with db.write() as c:
        c.execute("UPDATE concepts SET pending = ? WHERE user_id = ? AND slug = ?", (db.dumps(pending), uid, slug_))
    return {k: v for k, v in pending.items() if k not in HIDDEN}


def answer_review(slug_, answer):
    uid = current_user()
    row = db.one("SELECT pending FROM concepts WHERE user_id = ? AND slug = ?", (uid, slug_))
    p = db.loads(row["pending"]) if row else None
    if not p:
        raise KeyError("no review question pending")
    result = grade(p["question"], p["rubric"], p["model_answer"], answer)
    with db.write() as c:
        c.execute("UPDATE concepts SET last_question = ? WHERE user_id = ? AND slug = ?", (p["question"], uid, slug_))
        _record(c, slug_, p["question"], answer, result["verdict"], "review")
    return {**result, "model_answer": p["model_answer"], "concept": _concept_after(slug_)}
