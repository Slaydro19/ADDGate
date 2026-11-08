import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtDate } from "../api.js";
import QuizCard from "../components/QuizCard.jsx";
import { Info, Spinner } from "../icons.jsx";

function Row({ c, on, done, onPick, children }) {
  return (
    <button className={`qrow ${on ? "on" : ""}`} onClick={() => onPick(c)} disabled={done}>
      <span className="nm"><span style={{ fontWeight: 600 }}>{c.name}</span><span className="mono muted">{c.category}</span></span>
      <span className="row" style={{ gap: 8 }}>
        {children}
        <span className={`status s-${done ? "owned" : c.status}`}>{done ? "done" : c.status}</span>
      </span>
    </button>
  );
}

function Group({ title, note, items, empty, active, doneIds, onPick, extra }) {
  return (
    <section className="panel" aria-label={title}>
      <div><h2>{title}</h2>{note && <div className="faint" style={{ marginTop: 6 }}>{note}</div>}</div>
      {items.length === 0 && <div className="muted">{empty}</div>}
      <div className="studylist">
        {items.map((c) => (
          <Row key={c.id} c={c} on={active?.id === c.id} done={doneIds.includes(c.id)} onPick={onPick}>
            {extra?.(c)}
          </Row>
        ))}
      </div>
    </section>
  );
}

export default function Study({ go, refreshUsage }) {
  const [vault, setVault] = useState(null);
  const [due, setDue] = useState(null);
  const [stats, setStats] = useState(null);
  const [hintDelay, setHintDelay] = useState(60);
  const [category, setCategory] = useState(null);
  const [active, setActive] = useState(null);
  const [question, setQuestion] = useState(null);
  const [loadingQ, setLoadingQ] = useState(false);
  const [error, setError] = useState(null);
  const [doneIds, setDoneIds] = useState([]);

  const load = useCallback(() => {
    api("/vault").then((r) => setVault(r.concepts));
    api("/review").then((r) => { setDue(r.due); setHintDelay(r.hint_delay); });
    api("/stats").then(setStats).catch(() => setStats({ categories: [], retention: { didnt_hold: [] } }));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function start(c) {
    setActive(c); setQuestion(null); setError(null); setLoadingQ(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
    try { setQuestion(await api(`/review/${c.id}/question`, { method: "POST" })); refreshUsage(); }
    catch (e) { setError(e.message); }
    finally { setLoadingQ(false); }
  }
  async function submit(payload) {
    const res = await api(`/review/${active.id}/answer`, { method: "POST", body: payload });
    setDoneIds((d) => [...d, active.id]);
    refreshUsage();
    return res;
  }

  const byName = useMemo(() => Object.fromEntries((vault || []).map((c) => [c.name, c])), [vault]);

  if (!vault || !due || !stats) return <main><div className="row muted"><Spinner /> Loading…</div></main>;

  const relearn = vault.filter((c) => c.status === "relearn");
  const dueOthers = due.filter((c) => c.status !== "relearn");
  const didnt = (stats.retention?.didnt_hold || []).map((h) => byName[h.name]).filter(Boolean);
  const cats = (stats.categories || []).slice().sort((a, b) => (b.misses / (b.attempts || 1)) - (a.misses / (a.attempts || 1)));
  const inCat = category ? vault.filter((c) => c.category === category).sort((a, b) => (a.status === "owned") - (b.status === "owned")) : [];
  const remaining = [...relearn, ...dueOthers].filter((c) => !doneIds.includes(c.id));
  const next = remaining.find((c) => c.id !== active?.id);
  const nothing = !vault.length;

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Study</div>
          <h1>{remaining.length ? `${remaining.length} to work on.` : nothing ? "Nothing to study yet." : "All caught up."}</h1>
          <p className="sub">Lessons for what you keep missing first, then what's due. Practice any weak spot whenever you like.</p>
        </div>
        {remaining.length > 0 && !active && <button className="btn primary" onClick={() => start(remaining[0])}>Start with {remaining[0].name}</button>}
      </section>

      {active && (
        <div className="cols" style={{ flexDirection: "column", alignItems: "stretch" }}>
          {loadingQ && <section className="panel"><div className="row muted"><Spinner /> Claude is writing a new scenario…</div></section>}
          {error && <section className="panel"><div className="note red" role="alert"><Info /><div>{error}</div></div></section>}
          {question && (
            <QuizCard key={active.id} title={`${active.name}`} item={question} hintDelay={hintDelay} onSubmit={submit}
              onNext={next ? () => start(next) : () => { setActive(null); setQuestion(null); load(); }}
              nextLabel={next ? "Next concept" : "Done"} />
          )}
          <div><button className="btn small" onClick={() => { setActive(null); setQuestion(null); load(); }}>Back to the list</button></div>
        </div>
      )}

      {nothing ? (
        <div className="panel"><div className="empty"><strong>Your vault is empty.</strong>
          <span>Close a gate and answer a few questions. What you miss shows up here.</span>
          <button className="btn primary" onClick={() => go("gate")}>Go to the Gate</button></div></div>
      ) : (
        <>
          <Group title="Relearn first" note="Missed twice. Each starts with a short lesson."
            items={relearn} empty="No concept is stuck. Nice." active={active} doneIds={doneIds} onPick={start} />
          <Group title="Due for review" note="Includes anything that came due on days you skipped the gate."
            items={dueOthers} empty="Nothing due." active={active} doneIds={doneIds} onPick={start}
            extra={(c) => c.next_due && <span className="mono muted">{fmtDate(c.next_due)}</span>} />
          <Group title="Didn't hold" note="Owned the first time, missed when asked again. Only knowing it fixes these."
            items={didnt} empty={stats.retention?.checked ? "Everything you owned has held up." : "Fills in as owned concepts come back."}
            active={active} doneIds={doneIds} onPick={start} />

          <section className="panel" aria-label="Practice a weak category">
            <div><h2>Practice a category</h2><div className="faint" style={{ marginTop: 6 }}>Weakest first. Pick one to see its concepts.</div></div>
            {cats.length === 0 && <div className="muted">Categories appear once you've answered a few questions.</div>}
            <div className="chips" role="group" aria-label="Categories">
              {cats.map((c) => {
                const rate = c.attempts ? Math.round((100 * c.misses) / c.attempts) : 0;
                return (
                  <button key={c.category} className={category === c.category ? "on" : ""} aria-pressed={category === c.category}
                    onClick={() => setCategory(category === c.category ? null : c.category)}>
                    {c.category}<span className="rate">{rate}% missed</span>
                  </button>
                );
              })}
            </div>
            {category && (
              <div className="studylist">
                {inCat.map((c) => <Row key={c.id} c={c} on={active?.id === c.id} done={doneIds.includes(c.id)} onPick={start} />)}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
