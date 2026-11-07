import React, { useEffect, useState } from "react";
import { api, fmtTime } from "../api.js";
import QuizCard from "../components/QuizCard.jsx";
import { Spinner } from "../icons.jsx";

export default function Gate({ go, refreshUsage }) {
  const [data, setData] = useState(null);
  const [current, setCurrent] = useState(null);

  const load = () => api("/gate/today").then((d) => {
    setData(d);
    const qs = d.day?.questions || [];
    setCurrent((cur) => cur ?? (qs.find((q) => !q.result) || qs[0])?.id ?? null);
  });
  useEffect(() => { load(); }, []);

  if (!data) return <main><div className="row muted"><Spinner /> Loading…</div></main>;
  const qs = data.day?.questions || [];
  if (!qs.length) {
    return (
      <main><div className="panel"><div className="empty">
        <div style={{ fontSize: 18, fontWeight: 600 }}>No quiz yet today.</div>
        <div className="muted">Close the gate on the Capture page and Claude will write cold questions about what you built.</div>
        <button className="btn primary" onClick={() => go("capture")}>Go to Capture</button>
      </div></div></main>
    );
  }

  const answered = qs.filter((q) => q.result);
  const owned = answered.filter((q) => q.result.verdict === "owned").length;
  const pct = answered.length ? Math.round((100 * owned) / answered.length) : 0;
  const idx = Math.max(0, qs.findIndex((q) => q.id === current));
  const q = qs[idx];
  const nextOpen = qs.find((x, i) => i > idx && !x.result) || qs.find((x) => !x.result && x.id !== q.id);
  const done = answered.length === qs.length;

  async function submit(answer) {
    const res = await api("/gate/answer", { method: "POST", body: { question_id: q.id, answer } });
    setData((d) => ({ ...d, day: { ...d.day, questions: d.day.questions.map((x) =>
      x.id === q.id ? { ...x, answer, result: { verdict: res.verdict, feedback: res.feedback }, model_answer: res.model_answer } : x) } }));
    refreshUsage();
    return res;
  }

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Gate closed · {fmtTime(data.day.closed_at)}</div>
          <h1>{done ? "Gate cleared." : "You shipped it. Can you explain it?"}</h1>
          <p className="sub">{data.day.sessions.length} session{data.day.sessions.length === 1 ? "" : "s"}
            {data.day.commits ? ` · ${data.day.commits} commits` : ""} · {qs.length} questions</p>
        </div>
        <button className="btn" onClick={() => go("capture")}>Back to Capture</button>
      </section>

      <div className="cols">
        <section className="panel side" aria-labelledby="caught">
          <h2 id="caught">Concepts captured</h2>
          {qs.map((x) => {
            const st = x.result ? x.result.verdict : "open";
            return (
              <button key={x.id} className={`session ${x.id === q.id ? "on" : ""}`} onClick={() => setCurrent(x.id)}
                style={{ alignItems: "center", justifyContent: "space-between" }}>
                <span>{x.concept}</span>
                <span className={`status s-${st}`}>{x.result ? x.result.verdict : "to do"}</span>
              </button>
            );
          })}
        </section>

        <QuizCard key={q.id} title={`Cold question ${idx + 1} of ${qs.length}`} item={q}
          hintDelay={data.hint_delay} onSubmit={submit}
          onNext={nextOpen ? () => setCurrent(nextOpen.id) : done ? () => go("vault") : null}
          nextLabel={nextOpen ? "Next question" : "See your vault"} />

        <section className="panel side" aria-labelledby="score">
          <h2 id="score">Ownership</h2>
          <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
            <span className="big">{pct}%</span><span className="muted">owned</span>
          </div>
          <div className="split" role="img" aria-label={`${owned} owned, ${answered.length - owned} not yet`}>
            {owned > 0 && <div style={{ flex: owned, background: "var(--blue)" }} />}
            {answered.length - owned > 0 && <div style={{ flex: answered.length - owned, background: "var(--accent)" }} />}
            {qs.length - answered.length > 0 && <div style={{ flex: qs.length - answered.length, background: "var(--raised)" }} />}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
            <div className="row" style={{ justifyContent: "space-between" }}><span style={{ color: "var(--blue)" }}>Owned</span><span>{owned}</span></div>
            <div className="row" style={{ justifyContent: "space-between" }}><span style={{ color: "var(--accent)" }}>Borrowed or partial</span><span>{answered.length - owned}</span></div>
            <div className="row" style={{ justifyContent: "space-between" }}><span className="muted">Not answered</span><span>{qs.length - answered.length}</span></div>
          </div>
          <p className="muted" style={{ margin: 0, paddingTop: 14, borderTop: "1px solid var(--line)", fontSize: 14 }}>
            Anything not owned comes back tomorrow in Review, asked a different way.</p>
        </section>
      </div>
    </main>
  );
}
