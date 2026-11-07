import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import QuizCard from "../components/QuizCard.jsx";
import { Info, Spinner } from "../icons.jsx";

export default function Review({ go, refreshUsage }) {
  const [due, setDue] = useState(null);
  const [hintDelay, setHintDelay] = useState(60);
  const [active, setActive] = useState(null);   // concept
  const [question, setQuestion] = useState(null);
  const [loadingQ, setLoadingQ] = useState(false);
  const [error, setError] = useState(null);
  const [doneIds, setDoneIds] = useState([]);

  useEffect(() => { api("/review").then((r) => { setDue(r.due); setHintDelay(r.hint_delay); }); }, []);

  async function start(c) {
    setActive(c); setQuestion(null); setError(null); setLoadingQ(true);
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

  if (!due) return <main><div className="row muted"><Spinner /> Loading…</div></main>;
  const remaining = due.filter((c) => !doneIds.includes(c.id));
  const next = remaining.find((c) => c.id !== active?.id);

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Spaced review</div>
          <h1>{remaining.length ? `${remaining.length} concept${remaining.length > 1 ? "s" : ""} due today.` : "Nothing due. Nice."}</h1>
          <p className="sub">Each one comes back in a new scenario, so you're testing the idea, not your memory of the question.</p>
        </div>
      </section>

      <div className="cols">
        <section className="panel side" aria-labelledby="dueh">
          <h2 id="dueh">Due</h2>
          {due.length === 0 && <div className="muted">Close a gate to start building your review queue.</div>}
          {due.map((c) => (
            <button key={c.id} className={`session ${active?.id === c.id ? "on" : ""} ${doneIds.includes(c.id) ? "old" : ""}`}
              onClick={() => !doneIds.includes(c.id) && start(c)} disabled={doneIds.includes(c.id)}
              style={{ alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ display: "flex", flexDirection: "column" }}>
                <span>{c.name}</span><span className="muted mono">{c.category}</span>
              </span>
              <span className={`status s-${doneIds.includes(c.id) ? "owned" : c.status}`}>
                {doneIds.includes(c.id) ? "done" : c.status}</span>
            </button>
          ))}
        </section>

        {!active && remaining.length > 0 && (
          <section className="panel wide"><div className="empty">
            <div>Pick a concept, or start with the first one.</div>
            <button className="btn primary" onClick={() => start(remaining[0])}>Start review</button>
          </div></section>
        )}
        {active && loadingQ && <section className="panel wide"><div className="row muted"><Spinner /> Claude is writing a new scenario…</div></section>}
        {active && error && <section className="panel wide"><div className="note red" role="alert"><Info /><div>{error}</div></div></section>}
        {active && question && (
          <QuizCard key={active.id} title={`Review · ${active.name}`} item={question} hintDelay={hintDelay}
            onSubmit={submit} onNext={next ? () => start(next) : () => go("vault")}
            nextLabel={next ? "Next concept" : "See your vault"} />
        )}
      </div>
    </main>
  );
}
