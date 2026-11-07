"""Per-account stats. Every query is scoped with `WHERE user_id = ?`, and the id comes from
the server-side session (config.current_user()), never from the request, so one account
can't read another's numbers."""
from datetime import date, timedelta

import db
from config import current_user


def _streak(active_days):
    """Consecutive days with a gate close or an answer, counting back from today
    (or from yesterday, so the streak isn't 0 just because today isn't done yet)."""
    days = set(active_days)
    d = date.today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def stats(days_back=30):
    uid = current_user()
    today = date.today()
    since = (today - timedelta(days=days_back - 1)).isoformat()

    totals = db.one("""
        SELECT COUNT(*)                                  AS concepts,
               COALESCE(SUM(status = 'owned'), 0)        AS owned,
               COALESCE(SUM(status = 'relearn'), 0)      AS relearn,
               COALESCE(SUM(next_due <= :today), 0)      AS due_today
        FROM concepts WHERE user_id = :uid""", {"uid": uid, "today": today.isoformat()})

    attempts = db.one("""
        SELECT COUNT(*) AS total, COALESCE(SUM(verdict = 'owned'), 0) AS owned
        FROM attempts WHERE user_id = ?""", (uid,))

    gates = db.one("SELECT COUNT(*) AS n FROM days WHERE user_id = ?", (uid,))["n"]

    # Answers per day for the last N days: owned vs not (partial + borrowed).
    by_day = {r["day"]: r for r in db.all_rows("""
        SELECT substr(at, 1, 10) AS day,
               SUM(verdict = 'owned')  AS owned,
               SUM(verdict != 'owned') AS not_owned
        FROM attempts WHERE user_id = ? AND substr(at, 1, 10) >= ?
        GROUP BY day""", (uid, since))}
    daily = []
    for i in range(days_back):
        d = (today - timedelta(days=days_back - 1 - i)).isoformat()
        r = by_day.get(d) or {}
        daily.append({"day": d, "owned": r.get("owned") or 0, "not_owned": r.get("not_owned") or 0})

    categories = db.all_rows("""
        SELECT COALESCE(NULLIF(c.category, ''), 'uncategorized') AS category,
               COUNT(DISTINCT c.slug)                             AS concepts,
               COUNT(DISTINCT CASE WHEN c.status = 'owned' THEN c.slug END) AS owned,
               COUNT(a.id)                                        AS attempts,
               COALESCE(SUM(a.verdict != 'owned'), 0)             AS misses
        FROM concepts c
        LEFT JOIN attempts a ON a.user_id = c.user_id AND a.slug = c.slug
        WHERE c.user_id = ?
        GROUP BY 1
        ORDER BY CAST(misses AS REAL) / MAX(attempts, 1) DESC, concepts DESC""", (uid,))

    hardest = db.all_rows("""
        SELECT c.name, c.category, c.status,
               COUNT(a.id)                AS attempts,
               SUM(a.verdict != 'owned')  AS misses
        FROM concepts c JOIN attempts a ON a.user_id = c.user_id AND a.slug = c.slug
        WHERE c.user_id = ?
        GROUP BY c.slug HAVING misses > 0
        ORDER BY misses DESC, attempts DESC LIMIT 5""", (uid,))

    upcoming = {r["next_due"]: r["n"] for r in db.all_rows("""
        SELECT next_due, COUNT(*) AS n FROM concepts
        WHERE user_id = ? AND next_due BETWEEN ? AND ?
        GROUP BY next_due""", (uid, today.isoformat(), (today + timedelta(days=6)).isoformat()))}
    week = [{"day": (today + timedelta(days=i)).isoformat(),
             "due": upcoming.get((today + timedelta(days=i)).isoformat(), 0)} for i in range(7)]

    active = [r["d"] for r in db.all_rows("""
        SELECT DISTINCT substr(at, 1, 10) AS d FROM attempts WHERE user_id = ?
        UNION SELECT day FROM days WHERE user_id = ?""", (uid, uid))]

    # Did it hold? Concepts owned on the first try that have been asked again since:
    # judged by the most recent later attempt. This is the number a screenshot can't fake.
    retention = db.all_rows("""
        WITH ordered AS (
            SELECT slug, verdict,
                   ROW_NUMBER() OVER (PARTITION BY slug ORDER BY at, id)           AS first_rank,
                   ROW_NUMBER() OVER (PARTITION BY slug ORDER BY at DESC, id DESC) AS last_rank,
                   COUNT(*)     OVER (PARTITION BY slug)                           AS n
            FROM attempts WHERE user_id = :uid)
        SELECT c.name, c.category, f.n AS attempts, l.verdict AS latest
        FROM ordered f
        JOIN ordered l  ON l.slug = f.slug AND l.last_rank = 1
        JOIN concepts c ON c.user_id = :uid AND c.slug = f.slug
        WHERE f.first_rank = 1 AND f.verdict = 'owned' AND f.n > 1""", {"uid": uid})
    held = sum(r["latest"] == "owned" for r in retention)
    didnt_hold = [{"name": r["name"], "category": r["category"], "attempts": r["attempts"], "latest": r["latest"]}
                  for r in retention if r["latest"] != "owned"]

    honesty = db.one("""
        SELECT COALESCE(SUM(looked_up), 0)                                   AS looked_up,
               COALESCE(SUM(flags LIKE '%"pasted"%'), 0)                     AS pasted,
               COALESCE(SUM(flags LIKE '%"left_tab"%'), 0)                   AS left_tab,
               COALESCE(SUM(confidence = 'sure' AND verdict != 'owned'), 0)  AS sure_but_wrong,
               COALESCE(SUM(confidence IS NOT NULL), 0)                      AS rated
        FROM attempts WHERE user_id = ?""", (uid,))

    return {
        "retention": {"checked": len(retention), "held": held,
                      "pct": round(100 * held / len(retention)) if retention else None,
                      "didnt_hold": didnt_hold[:6]},
        "honesty": honesty,
        "totals": {**totals, "attempts": attempts["total"], "attempts_owned": attempts["owned"],
                   "gates_closed": gates, "streak": _streak(active),
                   "ownership_pct": round(100 * totals["owned"] / totals["concepts"]) if totals["concepts"] else 0},
        "daily": daily, "categories": categories, "hardest": hardest, "upcoming": week,
    }
