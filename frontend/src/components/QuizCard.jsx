import React, { useEffect, useState } from "react";
import { Info, Spinner } from "../icons.jsx";

const VERDICT = { owned: "Owned", partial: "Partly there", borrowed: "Borrowed" };

/** One cold question: answer, optional delayed hint, then the grade + reference answer. */
export default function QuizCard({ title, item, hintDelay = 60, onSubmit, onNext, nextLabel = "Next question" }) {
  const [answer, setAnswer] = useState(item.answer || "");
  const [result, setResult] = useState(item.result ? { ...item.result, model_answer: item.model_answer } : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    setAnswer(item.answer || ""); setShowHint(false); setElapsed(0); setError(null);
    setResult(item.result ? { ...item.result, model_answer: item.model_answer } : null);
  }, [item.id, item.concept_id, item.question]);

  useEffect(() => {
    if (result) return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [result, item.question]);

  async function submit(text) {
    setBusy(true); setError(null);
    try { setResult(await onSubmit(text)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const hintIn = Math.max(0, hintDelay - elapsed);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  return (
    <section className="panel wide focus" aria-labelledby="qtitle">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 id="qtitle">{title}</h2>
        {!result && <span className="mono muted">no peeking · {mm}:{ss}</span>}
      </div>

      {item.lesson && (
        <div className="note blue"><Info /><div><strong>Relearn first.</strong> {item.lesson}</div></div>
      )}

      <p className="question">{item.question}</p>

      {!result ? (
        <>
          <div className="field">
            <label htmlFor="ans">Your answer, in your own words</label>
            <textarea id="ans" value={answer} onChange={(e) => setAnswer(e.target.value)} autoFocus
              placeholder="Explain why, not just what…" disabled={busy}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && answer.trim()) submit(answer); }} />
          </div>
          <div className="row">
            <button className="btn primary" onClick={() => submit(answer)} disabled={busy || !answer.trim()}>
              {busy ? <><Spinner /> Grading…</> : "Submit answer"}</button>
            <button className="btn" onClick={() => submit("")} disabled={busy}>I don't know</button>
            {item.hint && (
              <button className="btn" onClick={() => setShowHint(true)} disabled={busy || hintIn > 0 || showHint}>
                {showHint ? "Hint shown" : hintIn > 0 ? `Hint in ${hintIn}s` : "Show hint"}</button>
            )}
          </div>
          {showHint && <div className="note"><Info /><div>{item.hint}</div></div>}
        </>
      ) : (
        <>
          <div>
            <div className={`verdict v-${result.verdict}`}>{VERDICT[result.verdict]}</div>
            {result.feedback && <p style={{ margin: "6px 0 0" }}>{result.feedback}</p>}
          </div>
          {answer && <div className="item"><span className="muted" style={{ fontSize: 13 }}>Your answer</span><span>{answer}</span></div>}
          {result.model_answer && (
            <div className="item"><span className="muted" style={{ fontSize: 13 }}>Reference answer</span><span>{result.model_answer}</span></div>
          )}
          <div className="muted" style={{ fontSize: 14 }}>
            {result.verdict === "owned" ? "This comes back later at a longer interval."
              : result.concept?.status === "relearn" ? "Second miss. Tomorrow's review starts with a short lesson."
              : "This comes back in tomorrow's review with a new scenario."}
          </div>
          {onNext && <div className="row"><button className="btn primary" onClick={onNext} autoFocus>{nextLabel}</button></div>}
        </>
      )}
      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
    </section>
  );
}
