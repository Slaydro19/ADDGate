import React, { useEffect, useRef, useState } from "react";
import { Info, Spinner } from "../icons.jsx";

const VERDICT = { owned: "Owned", partial: "Partly there", borrowed: "Borrowed" };
const CONFIDENCE = [["sure", "Sure"], ["fairly", "Fairly sure"], ["guessing", "Guessing"]];
const LETTERS = "ABCD";

export function flagText(f) {
  switch (f.kind) {
    case "looked_up": return "you looked it up";
    case "pasted": return `pasted ${f.chars} characters`;
    case "left_tab": return `left the tab for ${f.seconds}s`;
    case "too_fast": return "appeared faster than typing";
    default: return f.kind;
  }
}

/** Watches how an answer gets written. It never blocks anything; it just keeps an honest record. */
function useSignals(active) {
  const s = useRef({ pasted: 0, away: 0, firstKey: null, hiddenAt: null });
  useEffect(() => {
    if (!active) return;
    const leave = () => { if (!s.current.hiddenAt) s.current.hiddenAt = Date.now(); };
    const back = () => {
      if (s.current.hiddenAt) { s.current.away += (Date.now() - s.current.hiddenAt) / 1000; s.current.hiddenAt = null; }
    };
    const vis = () => (document.hidden ? leave() : back());
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("blur", leave);
    window.addEventListener("focus", back);
    return () => {
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("blur", leave);
      window.removeEventListener("focus", back);
    };
  }, [active]);
  return {
    onPaste: (e) => { s.current.pasted += (e.clipboardData?.getData("text") || "").length; },
    onKey: () => { if (!s.current.firstKey) s.current.firstKey = Date.now(); },
    read: (text) => ({
      pasted_chars: s.current.pasted,
      away_seconds: Math.round(s.current.away),
      typed_seconds: s.current.firstKey ? (Date.now() - s.current.firstKey) / 1000 : 0,
      chars: text.length,
    }),
    reset: () => { s.current = { pasted: 0, away: 0, firstKey: null, hiddenAt: null }; },
  };
}

/** One cold question. Multiple choice + "why" when the question has choices, open recall otherwise. */
export default function QuizCard({ title, item, hintDelay = 60, onSubmit, onNext, nextLabel = "Next question" }) {
  const initial = item.result ? { ...item.result, model_answer: item.model_answer, choices: item.choices } : null;
  const [answer, setAnswer] = useState(item.answer || "");
  const [choice, setChoice] = useState(null);
  const [confidence, setConfidence] = useState(null);
  const [result, setResult] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [showHint, setShowHint] = useState(false);
  const signals = useSignals(!result);
  const mc = Array.isArray(item.choices) && item.choices.length > 0;

  useEffect(() => {
    setAnswer(item.answer || ""); setChoice(null); setConfidence(null); setShowHint(false); setElapsed(0); setError(null);
    setResult(item.result ? { ...item.result, model_answer: item.model_answer, choices: item.choices } : null);
    signals.reset();
  }, [item.id, item.concept_id, item.question]);

  useEffect(() => {
    if (result) return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [result, item.question]);

  async function submit(extra = {}) {
    setBusy(true); setError(null);
    const payload = { answer, choice, confidence, signals: signals.read(answer), ...extra };
    try { setResult(await onSubmit(payload)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const canSubmit = mc ? choice !== null && answer.trim().length > 0 : answer.trim().length > 0;
  const hintIn = Math.max(0, hintDelay - elapsed);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  const shownChoices = result?.choices || item.choices || [];

  return (
    <section className="panel wide focus" aria-labelledby="qtitle">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 id="qtitle">{title}</h2>
        {!result && <span className="mono muted">no peeking · {mm}:{ss}</span>}
      </div>

      {item.lesson && <div className="note blue"><Info /><div><strong>Relearn first.</strong> {item.lesson}</div></div>}

      <p className="question" id="qtext">{item.question}</p>

      {mc && (
        <fieldset className="choices" disabled={!!result || busy}>
          <legend className="sr-only">Pick an answer</legend>
          {shownChoices.map((c, i) => {
            const isCorrect = result && result.correct === i;
            const isPick = result ? result.choice === i : choice === i;
            const cls = result ? (isCorrect ? "right" : isPick ? "wrong" : "dim") : isPick ? "picked" : "";
            return (
              <label key={i} className={`choice ${cls}`}>
                <input type="radio" name={`choice-${item.id || item.concept_id}`} checked={isPick}
                  onChange={() => setChoice(i)} />
                <span className="letter" aria-hidden="true">{LETTERS[i]}</span>
                <span className="ctext">
                  {c.text}
                  {result && isCorrect && <span className="ctag">Correct answer</span>}
                  {result && isPick && !isCorrect && <span className="ctag warn">Your pick</span>}
                  {result && isPick && !isCorrect && c.misconception && <span className="cmis">{c.misconception}</span>}
                </span>
              </label>
            );
          })}
        </fieldset>
      )}

      {!result ? (
        <>
          <div className="field">
            <label htmlFor="ans">{mc ? "Why this one? Explain it in your own words" : "Your answer, in your own words"}</label>
            <textarea id="ans" value={answer} disabled={busy} autoFocus={!mc}
              placeholder={mc ? "What makes it right, and what would break if it weren't true…" : "Explain why, not just what…"}
              onChange={(e) => setAnswer(e.target.value)} onPaste={signals.onPaste} onKeyDown={(e) => {
                signals.onKey();
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) submit();
              }} />
          </div>
          <div className="field">
            <span id="conf-label" className="faint" style={{ fontSize: 14 }}>How sure are you?</span>
            <div className="segmented" role="radiogroup" aria-labelledby="conf-label">
              {CONFIDENCE.map(([v, label]) => (
                <button key={v} type="button" role="radio" aria-checked={confidence === v}
                  className={confidence === v ? "on" : ""} onClick={() => setConfidence(confidence === v ? null : v)}>{label}</button>
              ))}
            </div>
          </div>
          <div className="row">
            <button className="btn primary" onClick={() => submit()} disabled={busy || !canSubmit}>
              {busy ? <><Spinner /> Grading…</> : "Submit answer"}</button>
            <button className="btn" onClick={() => submit({ looked_up: true })} disabled={busy}
              title="No penalty. It just comes back tomorrow.">I looked it up</button>
            <button className="btn" onClick={() => submit({ answer: "", choice: null })} disabled={busy}>I don't know</button>
            {item.hint && (
              <button className="btn" onClick={() => setShowHint(true)} disabled={busy || hintIn > 0 || showHint}>
                {showHint ? "Hint shown" : hintIn > 0 ? `Hint in ${hintIn}s` : "Show hint"}</button>
            )}
          </div>
          {mc && !canSubmit && choice !== null && <div className="faint">Add a sentence or two on why. The reasoning is what counts.</div>}
          {showHint && <div className="note"><Info /><div>{item.hint}</div></div>}
        </>
      ) : (
        <>
          <div>
            <div className={`verdict v-${result.verdict}`}>{VERDICT[result.verdict]}</div>
            {result.feedback && <p style={{ margin: "6px 0 0" }}>{result.feedback}</p>}
          </div>
          {(answer || item.answer) && <div className="item"><span className="muted" style={{ fontSize: 13 }}>Your explanation</span><span>{answer || item.answer}</span></div>}
          {result.model_answer && (
            <div className="item"><span className="muted" style={{ fontSize: 13 }}>Reference answer</span><span>{result.model_answer}</span></div>
          )}
          {result.flags?.length > 0 && (
            <div className="faint">Noted: {result.flags.map(flagText).join(" · ")}</div>
          )}
          <div className="muted" style={{ fontSize: 14 }}>
            {result.verdict === "owned" ? "This comes back later at a longer interval, as an open question."
              : result.concept?.status === "relearn" ? "Second miss. Tomorrow's review starts with a short lesson."
              : "This comes back in tomorrow's review as an open question in a new scenario."}
          </div>
          {onNext && <div className="row"><button className="btn primary" onClick={onNext} autoFocus>{nextLabel}</button></div>}
        </>
      )}
      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
    </section>
  );
}
