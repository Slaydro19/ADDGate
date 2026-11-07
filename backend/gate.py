"""Gate open/close, quizzing, grading and the spaced-review schedule."""
import re
import uuid
from datetime import date, datetime, timedelta

import capture
import claude_client as cc
import prompts
from config import DAYS_DIR, STATE_FILE, VAULT_FILE, load_config, read_json, write_json

HIDDEN = ("rubric", "model_answer")


def now():
    return datetime.now().astimezone()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or uuid.uuid4().hex[:8]


# ---------- gate state ----------

def state():
    """A new day always starts with the gate open from midnight."""
    st = read_json(STATE_FILE, {})
    key = "closed_at" if st.get("status") == "closed" else "opened_at"
    if (st.get(key) or "")[:10] == date.today().isoformat():
        return st
    start_of_day = datetime.combine(date.today(), datetime.min.time()).astimezone()
    return {"status": "open", "opened_at": start_of_day.isoformat(), "closed_at": st.get("closed_at")}


def open_gate():
    st = {"status": "open", "opened_at": now().isoformat(), "closed_at": state().get("closed_at")}
    write_json(STATE_FILE, st)
    return st


# ---------- vault ----------

def vault():
    return read_json(VAULT_FILE, {})


def save_vault(v):
    write_json(VAULT_FILE, v)


def due_concepts():
    today = date.today().isoformat()
    return [c for c in vault().values() if c.get("next_due") and c["next_due"] <= today]


def schedule(concept, verdict):
    intervals = load_config()["review_intervals_days"]
    idx = concept.get("interval_index", -1)
    if verdict == "owned":
        idx = min(idx + 1, len(intervals) - 1)
        concept["status"] = "owned"
        concept["fails"] = 0
        days = intervals[idx]
    elif verdict == "partial":
        idx = max(idx - 1, -1)
        concept["status"] = "partial"
        days = 1
    else:
        idx = -1
        concept["fails"] = concept.get("fails", 0) + 1
        concept["status"] = "relearn" if concept["fails"] >= 2 else "borrowed"
        days = 1
    concept["interval_index"] = idx
    concept["next_due"] = (date.today() + timedelta(days=days)).isoformat()


# ---------- gate close ----------

def day_file(day=None):
    return DAYS_DIR / f"{(day or date.today()).isoformat()}.json"


def today():
    return read_json(day_file(), None)


def public(q):
    out = {k: v for k, v in q.items() if k not in HIDDEN}
    if q.get("result"):
        out["model_answer"] = q.get("model_answer")
    return out


def public_day(d):
    if not d:
        return None
    return {**d, "questions": [public(q) for q in d["questions"]]}


def close_gate():
    st = state()
    since = datetime.fromisoformat(st["opened_at"])
    sessions = capture.sessions_today(since=since)
    commits = capture.git_commits(since=since)
    if not sessions and not any("hash" in c for c in commits):
        raise cc.ClaudeError("Nothing captured since the gate opened. Do some work with Claude Code first.",
                             "empty")

    cfg = load_config()
    v = vault()
    known = ", ".join(sorted(c["name"] for c in v.values())[:80]) or "none yet"
    data = capture.transcript_for_llm(sessions) + capture.commits_for_llm(commits)
    reply = cc.ask_json(prompts.CLOSE.format(n=cfg["questions_per_close"], known=known), data)
    concepts = reply.get("concepts", []) if isinstance(reply, dict) else reply

    existing = read_json(day_file(), None)
    questions = existing["questions"] if existing else []
    stamp = now().isoformat()
    for c in concepts:
        if not c.get("name") or not c.get("question"):
            continue
        cid = slug(c["name"])
        entry = v.get(cid) or {"id": cid, "name": c["name"], "created": date.today().isoformat(),
                               "status": "new", "interval_index": -1, "fails": 0, "history": []}
        entry.update(category=c.get("category", ""), why=c.get("why", ""), last_question=c["question"])
        v[cid] = entry
        questions.append({
            "id": uuid.uuid4().hex[:10], "concept_id": cid, "concept": c["name"],
            "category": c.get("category", ""), "why": c.get("why", ""),
            "question": c["question"], "hint": c.get("hint", ""),
            "rubric": c.get("rubric", []), "model_answer": c.get("model_answer", ""),
            "closed_at": stamp, "result": None,
        })
    save_vault(v)

    day = {"date": date.today().isoformat(), "closed_at": stamp,
           "sessions": [capture.summarize(s)["title"] for s in sessions],
           "commits": len([c for c in commits if "hash" in c]), "questions": questions}
    write_json(day_file(), day)
    write_json(STATE_FILE, {"status": "closed", "opened_at": st["opened_at"], "closed_at": stamp})
    return public_day(day)


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


def record(concept_id, question, answer, result, source):
    v = vault()
    c = v.get(concept_id)
    if not c:
        return None
    c.setdefault("history", []).append({"date": now().isoformat(), "source": source,
                                        "question": question, "answer": answer,
                                        "verdict": result["verdict"]})
    schedule(c, result["verdict"])
    c.pop("pending", None)
    save_vault(v)
    return c


def answer_gate(qid, answer):
    d = today()
    q = next((q for q in (d or {}).get("questions", []) if q["id"] == qid), None)
    if not q:
        raise KeyError("question not found")
    result = grade(q["question"], q["rubric"], q["model_answer"], answer)
    q["answer"], q["result"] = answer, result
    write_json(day_file(), d)
    concept = record(q["concept_id"], q["question"], answer, result, "gate")
    return {**result, "model_answer": q["model_answer"], "concept": concept}


# ---------- review ----------

def review_question(concept_id):
    v = vault()
    c = v.get(concept_id)
    if not c:
        raise KeyError("concept not found")
    if c.get("pending"):
        return {k: val for k, val in c["pending"].items() if k not in HIDDEN}
    relearn = c.get("status") == "relearn"
    res = cc.ask_json(prompts.REVIEW.format(
        name=c["name"], category=c.get("category", ""), why=c.get("why", ""),
        previous=c.get("last_question", ""),
        relearn=prompts.RELEARN_NOTE if relearn else "",
        lesson_field=prompts.LESSON_FIELD if relearn else ""))
    c["pending"] = {"concept_id": concept_id, "question": res.get("question", ""),
                    "hint": res.get("hint", ""), "lesson": res.get("lesson", ""),
                    "rubric": res.get("rubric", []), "model_answer": res.get("model_answer", "")}
    save_vault(v)
    return {k: val for k, val in c["pending"].items() if k not in HIDDEN}


def answer_review(concept_id, answer):
    v = vault()
    c = v.get(concept_id)
    if not c or not c.get("pending"):
        raise KeyError("no review question pending")
    p = c["pending"]
    result = grade(p["question"], p["rubric"], p["model_answer"], answer)
    c["last_question"] = p["question"]
    save_vault(v)
    concept = record(concept_id, p["question"], answer, result, "review")
    return {**result, "model_answer": p["model_answer"], "concept": concept}
