import React, { useCallback, useEffect, useState } from "react";
import { api, fmtTime } from "../api.js";
import QuizCard from "../components/QuizCard.jsx";
import TerminalArea from "./Terminal.jsx";
import { Info, Lock, Unlock, Spinner } from "../icons.jsx";

/* ── after the gate closes: today's questions, then anything due from earlier days ── */
function QuizFlow({ go, refreshUsage, onReopen, busy }) {
  const [data, setData] = useState(null);
  const [current, setCurrent] = useState(null);
  const [stage, setStage] = useState("today");       // today | review | done
  const [due, setDue] = useState(null);
  const [hintDelay, setHintDelay] = useState(60);
  const [active, setActive] = useState(null);        // review concept
  const [question, setQuestion] = useState(null);
  const [loadingQ, setLoadingQ] = useState(false);
  const [error, setError] = useState(null);
  const [doneIds, setDoneIds] = useState([]);

  useEffect(() => {
    api("/gate/today").then((d) => {
      setData(d);
      const qs = d.day?.questions || [];
      setCurrent((qs.find((q) => !q.result) || qs[0])?.id ?? null);
      if (qs.length && qs.every((q) => q.result)) setStage("review");
    });
  }, []);

  const startReview = useCallback(async (c) => {
    setActive(c); setQuestion(null); setError(null); setLoadingQ(true);
    try { setQuestion(await api(`/review/${c.id}/question`, { method: "POST" })); refreshUsage(); }
    catch (e) { setError(e.message); }
    finally { setLoadingQ(false); }
  }, [refreshUsage]);

  useEffect(() => {
    if (stage !== "review") return;
    api("/review").then((r) => {
      setHintDelay(r.hint_delay);
      setDue(r.due);
      if (r.due.length) startReview(r.due[0]); else setStage("done");
    }).catch((e) => setError(e.message));
  }, [stage, startReview]);

  if (!data) return <div className="gatepad"><div className="row muted"><Spinner /> Loading…</div></div>;
  const qs = data.day?.questions || [];

  if (!qs.length) {
    return (
      <div className="gatepad"><div className="panel"><div className="empty">
        <strong>No quiz yet today.</strong>
        <span>Claude didn't write questions for this gate. Open it again and keep working.</span>
        <button className="btn primary" onClick={onReopen} disabled={busy}><Unlock /> Open gate</button>
      </div></div></div>
    );
  }

  const answered = qs.filter((q) => q.result);
  const owned = answered.filter((q) => q.result.verdict === "owned").length;
  const idx = Math.max(0, qs.findIndex((q) => q.id === current));
  const q = qs[idx];
  const nextOpen = qs.find((x, i) => i > idx && !x.result) || qs.find((x) => !x.result && x.id !== q.id);
  const reviewsLeft = due ? due.filter((c) => !doneIds.includes(c.id)) : [];
  const nextReview = reviewsLeft.find((c) => c.id !== active?.id);

  async function submit(payload) {
    const res = await api("/gate/answer", { method: "POST", body: { question_id: q.id, ...payload } });
    const { model_answer, choices, concept, ...result } = res;
    setData((d) => ({ ...d, day: { ...d.day, questions: d.day.questions.map((x) =>
      x.id === q.id ? { ...x, answer: payload.answer, result, model_answer, choices: choices || x.choices } : x) } }));
    refreshUsage();
    return res;
  }
  async function submitReview(payload) {
    const res = await api(`/review/${active.id}/answer`, { method: "POST", body: payload });
    setDoneIds((d) => [...d, active.id]);
    refreshUsage();
    return res;
  }

  const total = qs.length + (due ? due.length : 0);
  const step = stage === "today" ? idx + 1 : stage === "review" ? qs.length + doneIds.length + 1 : total;
  const pct = stage === "done" ? 100 : Math.round((100 * (stage === "today" ? answered.length : qs.length + doneIds.length)) / Math.max(total, 1));

  return (
    <div className="gatepad">
      <section className="hero">
        <div>
          <div className="eyebrow">Gate closed · {fmtTime(data.day.closed_at)}</div>
          <h1>{stage === "done" ? "Gate cleared." : stage === "review" ? "From earlier days." : "Can you explain it?"}</h1>
          <p className="sub">{data.day.sessions.length} session{data.day.sessions.length === 1 ? "" : "s"}
            {data.day.commits ? ` · ${data.day.commits} commits` : ""} · {qs.length} question{qs.length === 1 ? "" : "s"} today
            {due && due.length ? ` · ${due.length} due from before` : ""}</p>
        </div>
        <button className="btn" onClick={onReopen} disabled={busy}><Unlock /> Open gate</button>
      </section>

      <div className="split" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Quiz progress">
        <div style={{ width: `${pct}%`, background: "var(--accent)", borderRadius: 4, transition: "width .3s" }} />
      </div>

      {stage === "today" && (
        <QuizCard key={q.id} title={`Question ${step} of ${total}`} item={q} hintDelay={data.hint_delay} onSubmit={submit}
          onNext={nextOpen ? () => setCurrent(nextOpen.id) : () => setStage("review")}
          nextLabel={nextOpen ? "Next question" : "Continue"} />
      )}

      {stage === "review" && (
        <>
          {loadingQ && <div className="panel"><div className="row muted"><Spinner /> Claude is writing a new scenario…</div></div>}
          {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
          {active && question && (
            <QuizCard key={active.id} title={`Review ${step} of ${total} · ${active.name}`} item={question} hintDelay={hintDelay}
              onSubmit={submitReview}
              onNext={nextReview ? () => startReview(nextReview) : () => setStage("done")}
              nextLabel={nextReview ? "Next concept" : "Finish"} />
          )}
        </>
      )}

      {stage === "done" && (
        <div className="panel">
          <div className="row" style={{ alignItems: "baseline", gap: 12 }}>
            <span className="big">{answered.length ? Math.round((100 * owned) / answered.length) : 0}%</span>
            <span className="muted">of today's questions owned ({owned} of {answered.length})</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>Anything not owned comes back tomorrow, asked a different way.</p>
          <div className="row">
            <button className="btn primary" onClick={() => go("vault")}>See your vault</button>
            <button className="btn" onClick={() => go("study")}>Open Study</button>
            <button className="btn" onClick={() => go("stats")}>Stats</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── while the gate is open: terminal (or today's sessions) beside a quiet rail ── */
function SessionList({ sessions }) {
  if (!sessions.length) {
    return <div className="panel" style={{ flex: 1 }}><div className="empty">
      <strong>No sessions today.</strong><span>Open Claude Code and build something. It shows up here.</span></div></div>;
  }
  return (
    <div className="panel" style={{ flex: 1, overflow: "auto" }}>
      <h2>Today's sessions</h2>
      <div className="timeline">
        {sessions.map((s) => (
          <div key={s.id} className="tl-row">
            <span className="time">{fmtTime(s.start)}</span>
            <span className={`pip ${s.kind === "shell" ? "typed" : ""} ${s.after_open ? "" : "old"}`} aria-hidden="true" />
            <span><strong style={{ fontWeight: 600 }}>{s.title}</strong>{s.project && <span className="muted"> · {s.project}</span>}</span>
            <span className="meta">{s.kind === "shell" ? `${s.commands} cmd` : `${s.files.length} file${s.files.length === 1 ? "" : "s"}`}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Gate({ go, refreshUsage, user }) {
  const [cap, setCap] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => api("/capture").then(setCap).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, [load]);

  async function closeGate() {
    setBusy("close"); setError(null);
    try { await api("/gate/close", { method: "POST" }); refreshUsage(); await load(); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  }
  async function openGate() {
    setBusy("open");
    try { await api("/gate/open", { method: "POST" }); await load(); } finally { setBusy(null); }
  }
  async function installHook() {
    setBusy("hook");
    try { await api("/hook/install", { method: "POST" }); await load(); }
    catch (e) { setError(e.message); } finally { setBusy(null); }
  }

  if (!cap) return <div className="gatepad"><div className="row muted"><Spinner /> Loading…</div></div>;
  if (cap.gate.status === "closed") return <QuizFlow go={go} refreshUsage={refreshUsage} onReopen={openGate} busy={!!busy} />;

  const sessions = cap.sessions || [];
  const fresh = sessions.filter((s) => s.after_open);
  const live = sessions.filter((s) => s.after_open)[sessions.filter((s) => s.after_open).length - 1] || sessions[sessions.length - 1];
  const withClaude = sessions.filter((x) => x.kind !== "shell").length;
  const typed = sessions.filter((x) => x.kind === "shell").reduce((n, x) => n + x.commands, 0);
  // v2.8 wording: say "ran" for commands you typed, "worked on" for things done with Claude
  const things = `${withClaude} thing${withClaude === 1 ? "" : "s"} with Claude`;
  const cmds = `${typed} command${typed === 1 ? "" : "s"} you ran`;
  const headline = withClaude && typed ? `${things}, ${cmds}.` : withClaude ? `${things}.` : typed ? `${cmds}.` : "Nothing yet.";

  return (
    <div className="gatepage">
      <div className="gatemain">
        {user.is_owner ? <TerminalArea /> : <SessionList sessions={sessions} />}
      </div>

      <aside className="rail" aria-label="Gate status">
        <div>
          <div className="eyebrow green"><span className="dot" aria-hidden="true" /> Gate open</div>
          <div style={{ fontSize: 26, fontWeight: 500, letterSpacing: "-.03em", lineHeight: 1.15, margin: "10px 0 4px" }}>
            {headline}
          </div>
          <div className="muted" style={{ fontSize: 14 }}>Recording since {fmtTime(cap.gate.opened_at)}.</div>
        </div>

        <div>
          <button className="btn primary closebtn" onClick={closeGate} disabled={!!busy || fresh.length === 0}>
            {busy === "close" ? <><Spinner /> Claude is reading your day…</> : <><Lock /> Close gate &amp; quiz me</>}
          </button>
          {fresh.length === 0 && <div className="faint" style={{ marginTop: 8 }}>Do some work first. There's nothing to quiz yet.</div>}
        </div>

        {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
        {cap.due > 0 && (
          <div className="note blue"><Info /><div>{cap.due} concept{cap.due > 1 ? "s" : ""} due. They roll in after today's questions, or
            <> <button className="linkbtn" onClick={() => go("study")}>study now</button>.</></div></div>
        )}

        {user.is_owner && live && (
          <div className="livecap">
            <h2>Live capture</h2>
            <div className="log" aria-live="polite">
              {live.log.slice(-14).map((l, i) => (
                <div key={i}><span className="t">{l.t}</span>
                  <span className={`who-${l.who}${l.exit ? " failed" : ""}`}>{l.who === "you" || l.who === "claude" ? `${l.who}: ` : ""}{l.text}</span></div>
              ))}
            </div>
          </div>
        )}

        <div>
          <h2>Sources</h2>
          <div className="src"><span>Claude Code</span>
            <span style={{ color: cap.hook.installed ? "var(--green)" : "var(--amber)" }}>{cap.hook.installed ? "hooked" : "scanning"}</span></div>
          <div className="src"><span>Git</span><span>{cap.repos.length ? `${cap.repos.length} repo${cap.repos.length > 1 ? "s" : ""}` : "none"}</span></div>
          {cap.shell && <div className="src"><span>Shell</span><span>{cap.shell.enabled ? `${cap.shell.today} today` : "off"}</span></div>}
          {(!cap.hook.installed || (cap.shell && !cap.shell.enabled)) && (
            <div className="row" style={{ marginTop: 10 }}>
              {!cap.hook.installed && <button className="btn small" onClick={installHook} disabled={!!busy}>{busy === "hook" ? "Installing…" : cap.hook.stale ? "Repair hook" : "Install hook"}</button>}
              <button className="btn small" onClick={() => go("settings")}>Set up sources</button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
