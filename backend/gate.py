"""Gate open/close, quizzing, grading and the spaced-review schedule, on SQLite.

Slow Claude calls always happen OUTSIDE a transaction; the results are then written in one
short db.write() block that re-reads the row it changes, so parallel requests can't
overwrite each other."""
import random
import re
import uuid
from datetime import date, datetime, timedelta

import capture
import shell_capture
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
    for a in db.all_rows("SELECT slug, at, source, question, answer, verdict, confidence, choice_correct, flags "
                         "FROM attempts WHERE user_id = ? ORDER BY at, id", (uid,)):
        hist.setdefault(a["slug"], []).append(
            {"date": a["at"], "source": a["source"], "question": a["question"], "answer": a["answer"],
             "verdict": a["verdict"], "confidence": a["confidence"], "choice_correct": a["choice_correct"],
             "flags": db.loads(a["flags"], [])})
    out = {}
    for r in rows:
        h = hist.get(r["slug"], [])
        con = _concept(r, h)
        # Held up? Owned the first time, then still owned on the most recent later attempt.
        con["held"] = (h[-1]["verdict"] == "owned") if len(h) > 1 and h[0]["verdict"] == "owned" else None
        out[r["slug"]] = con
    return out


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
    choices = db.loads(q.get("choices"))
    answered = bool(q["verdict"])
    out = {"id": q["id"], "concept_id": q["slug"], "concept": q["concept"], "category": q["category"],
           "why": q["why"], "question": q["question"], "hint": q["hint"], "closed_at": q["closed_at"],
           "answer": q["answer"], "result": None,
           # before answering, the browser only gets the choice text: no answer key, no misconceptions
           "choices": ([{"text": c["text"]} for c in choices] if choices and not answered else choices)}
    if answered:
        out["result"] = {"verdict": q["verdict"], "feedback": q["feedback"] or "",
                         "correct": q.get("correct"), "choice": q.get("choice"),
                         "confidence": q.get("confidence"), "flags": db.loads(q.get("flags"), [])}
        out["model_answer"] = q["model_answer"]
    return out


def _clean_choices(raw):
    """Validate Claude's four choices and shuffle them. Returns (choices, correct_index) or (None, None)."""
    if not isinstance(raw, list) or len(raw) != 4:
        return None, None
    items = []
    for i, c in enumerate(raw):
        text = (c.get("text") if isinstance(c, dict) else None) or ""
        if not text.strip():
            return None, None
        items.append({"text": text.strip(), "misconception": None if i == 0 else (c.get("misconception") or "").strip(),
                      "_correct": i == 0})
    random.shuffle(items)
    correct = next(i for i, c in enumerate(items) if c.pop("_correct"))
    return items, correct


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
    shell_capture.ingest()
    typed = shell_capture.commands_since(uid, st["opened_at"]) if shell_capture.owner_id() == uid else []
    if not sessions and not real_commits and not typed:
        raise cc.ClaudeError("Nothing captured since the gate opened. Do some work with Claude Code first.",
                             "empty")

    cfg = load_config()
    known_rows = db.all_rows("SELECT name FROM concepts WHERE user_id = ? ORDER BY name LIMIT 80", (uid,))
    known = ", ".join(r["name"] for r in known_rows) or "none yet"
    data = capture.transcript_for_llm(sessions) + capture.commits_for_llm(commits) + shell_capture.for_llm(typed)
    # Slow part, outside any transaction:
    reply = cc.ask_json(prompts.CLOSE.format(n=cfg["questions_per_close"], known=known), data)
    concepts = reply.get("concepts", []) if isinstance(reply, dict) else reply

    stamp, day = now().isoformat(), date.today().isoformat()
    titles = [capture.summarize(s)["title"] for s in sessions] + \
             [shell_capture.summarize_block(b)["title"] for b in shell_capture.blocks(typed)]
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
            choices, correct = _clean_choices(item.get("choices"))
            c.execute("INSERT INTO questions (id, user_id, day, position, slug, concept, category, why, question, "
                      "hint, rubric, model_answer, closed_at, choices, correct) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (uuid.uuid4().hex[:12], uid, day, pos, s, item["name"], item.get("category", ""),
                       item.get("why", ""), item["question"], item.get("hint", ""),
                       db.dumps(item.get("rubric", [])), item.get("model_answer", ""), stamp,
                       db.dumps(choices) if choices else None, correct))
        _save_state(c, "closed", st["opened_at"], stamp)
    return today()


# ---------- grading ----------

CONFIDENCE = ("sure", "fairly", "guessing")
PASTE_LIMIT = 40          # pasting more than this many characters caps the verdict at partial
LEFT_TAB_SECONDS = 5      # time away from the tab worth noting
TOO_FAST_CPS = 12         # typing faster than ~140 wpm for 80+ characters isn't typing
RANK = {"borrowed": 0, "partial": 1, "owned": 2}


def flags_from(signals, looked_up=False):
    """Turn what the browser observed into a plain record. Nothing here blocks anything."""
    s = signals if isinstance(signals, dict) else {}
    num = lambda k: max(0, float(s.get(k) or 0))
    flags = []
    if looked_up:
        flags.append({"kind": "looked_up"})
    pasted, away, typed_s, chars = int(num("pasted_chars")), int(num("away_seconds")), num("typed_seconds"), int(num("chars"))
    if pasted >= PASTE_LIMIT:
        flags.append({"kind": "pasted", "chars": pasted})
    if away >= LEFT_TAB_SECONDS:
        flags.append({"kind": "left_tab", "seconds": away})
    typed = max(0, chars - pasted)
    if typed >= 80 and typed / max(typed_s, 1) > TOO_FAST_CPS:
        flags.append({"kind": "too_fast", "cps": round(typed / max(typed_s, 1), 1)})
    return flags


def _cap(result, ceiling, why):
    if RANK[result["verdict"]] > RANK[ceiling]:
        result["verdict"] = ceiling
        result["feedback"] = (result.get("feedback") or "").rstrip() + f" (Counted as {ceiling}: {why}.)"


def grade(item, payload):
    """item: the question row/pending dict. payload: what the person submitted.
    Returns {verdict, feedback, flags, confidence, choice, correct}."""
    why_text = (payload.get("answer") or "").strip()
    confidence = payload.get("confidence") if payload.get("confidence") in CONFIDENCE else None
    looked_up = bool(payload.get("looked_up"))
    flags = flags_from(payload.get("signals"), looked_up)
    choices = db.loads(item.get("choices")) if isinstance(item.get("choices"), str) else item.get("choices")
    correct = item.get("correct")
    choice = payload.get("choice")
    choice = choice if isinstance(choice, int) and choices and 0 <= choice < len(choices) else None
    base = {"flags": flags, "confidence": confidence, "choice": choice, "correct": correct if choices else None}

    if looked_up:  # honest exit: no Claude call, no penalty beyond seeing it again tomorrow
        return {**base, "verdict": "borrowed",
                "feedback": "Thanks for being straight about it. Read the answer below; this comes back tomorrow."}
    if choice is None and (not why_text or why_text.lower() in ("idk", "i don't know", "i dont know", "pass")):
        return {**base, "verdict": "borrowed", "feedback": "No answer, so this one goes to review. Read the answer below."}

    rubric = item.get("rubric")
    rubric = db.loads(rubric, []) if isinstance(rubric, str) else (rubric or [])
    if choices and choice is not None:
        picked = choices[choice]
        right = choice == correct
        res = cc.ask_json(prompts.GRADE_CHOICE.format(
            question=item["question"], correct=choices[correct]["text"], picked=picked["text"],
            pick_status="correct" if right else "wrong",
            misconception=f"The misconception behind their pick: {picked.get('misconception')}" if not right else "",
            rubric="; ".join(rubric), model_answer=item.get("model_answer", "")), why_text or "(no explanation)")
    else:
        right = None
        res = cc.ask_json(prompts.GRADE.format(question=item["question"], rubric="; ".join(rubric),
                                               model_answer=item.get("model_answer", "")), why_text)

    result = {**base, "verdict": res.get("verdict") if res.get("verdict") in RANK else "borrowed",
              "feedback": res.get("feedback", "")}
    # Rules applied after Claude, so a generous grade can't slip past them:
    if right is False:
        _cap(result, "partial", "the pick was wrong")
    if right is True and len(why_text) < 15:
        _cap(result, "partial", "right pick, but no reasoning to show you know why")
    if confidence == "guessing":
        _cap(result, "partial", "you said you were guessing")
    if any(f["kind"] == "pasted" for f in flags):
        _cap(result, "partial", "the explanation was pasted")
    if any(f["kind"] == "too_fast" for f in flags):
        _cap(result, "partial", "the explanation appeared faster than anyone types")
    return result


def _record(c, slug_, question, payload, result, source):
    c.execute("INSERT INTO attempts (user_id, slug, at, source, question, answer, verdict, confidence, "
              "choice_correct, looked_up, flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (current_user(), slug_, now().isoformat(), source, question, payload.get("answer") or "",
               result["verdict"], result["confidence"],
               None if result["choice"] is None else int(result["choice"] == result["correct"]),
               int(any(f["kind"] == "looked_up" for f in result["flags"])), db.dumps(result["flags"])))
    _schedule(c, slug_, result["verdict"])


def answer_gate(qid, payload):
    uid = current_user()
    q = db.one("SELECT * FROM questions WHERE id = ? AND user_id = ?", (qid, uid))
    if not q:
        raise KeyError("question not found")
    if not q["verdict"]:  # first submit only: a double-click or second tab doesn't count twice
        result = grade(q, payload)
        with db.write() as c:
            fresh = c.execute("SELECT verdict FROM questions WHERE id = ?", (qid,)).fetchone()
            if not fresh["verdict"]:
                c.execute("UPDATE questions SET answer = ?, verdict = ?, feedback = ?, choice = ?, confidence = ?, "
                          "flags = ? WHERE id = ? AND user_id = ?",
                          (payload.get("answer") or "", result["verdict"], result["feedback"], result["choice"],
                           result["confidence"], db.dumps(result["flags"]), qid, uid))
                _record(c, q["slug"], q["question"], payload, result, "gate")
    out = _question_out(db.one("SELECT * FROM questions WHERE id = ?", (qid,)))
    return {**out["result"], "model_answer": out["model_answer"], "choices": out["choices"],
            "concept": _concept_after(q["slug"])}


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


def answer_review(slug_, payload):
    """Reviews are open recall in a new scenario: harder than the gate's multiple choice."""
    uid = current_user()
    row = db.one("SELECT pending FROM concepts WHERE user_id = ? AND slug = ?", (uid, slug_))
    p = db.loads(row["pending"]) if row else None
    if not p:
        raise KeyError("no review question pending")
    result = grade(p, payload)
    with db.write() as c:
        still = c.execute("SELECT pending FROM concepts WHERE user_id = ? AND slug = ?", (uid, slug_)).fetchone()
        if still and still["pending"]:
            c.execute("UPDATE concepts SET last_question = ? WHERE user_id = ? AND slug = ?", (p["question"], uid, slug_))
            _record(c, slug_, p["question"], payload, result, "review")
    return {**result, "model_answer": p["model_answer"], "concept": _concept_after(slug_)}
