import React, { useCallback, useEffect, useState } from "react";
import { api, fmtTime } from "../api.js";
import { Lock, Unlock, Spinner, Info } from "../icons.jsx";

export default function Capture({ go, refreshUsage }) {
  const [data, setData] = useState(null);
  const [picked, setPicked] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => api("/capture").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, [load]);

  const sessions = data?.sessions || [];
  const active = sessions.find((s) => s.id === picked) || sessions[sessions.length - 1];
  const fresh = sessions.filter((s) => s.after_open);
  const closed = data?.gate.status === "closed";

  async function closeGate() {
    setBusy("close"); setError(null);
    try { await api("/gate/close", { method: "POST" }); refreshUsage(); go("gate"); }
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

  if (!data) return <main><div className="row muted"><Spinner /> Loading today…</div></main>;

  return (
    <main>
      <section className="hero">
        <div>
          {closed
            ? <div className="eyebrow">Gate closed at {fmtTime(data.gate.closed_at)}</div>
            : <div className="eyebrow green">Gate open · recording since {fmtTime(data.gate.opened_at)}</div>}
          <h1>{(() => {
            const withClaude = sessions.filter((x) => x.kind !== "shell").length;
            const typed = sessions.filter((x) => x.kind === "shell").reduce((n, x) => n + x.commands, 0);
            const things = `${withClaude} thing${withClaude === 1 ? "" : "s"} with Claude`;
            const cmds = `${typed} command${typed === 1 ? "" : "s"} on your own`;
            if (withClaude && typed) return `Today you worked on ${things} and ran ${cmds}.`;
            if (withClaude) return `Today you worked on ${things}.`;
            if (typed) return `Today you ran ${cmds}.`;
            return "Nothing captured yet today.";
          })()}</h1>
          <p className="sub">{closed
            ? "Work since the gate closed isn't quizzed until you open it again."
            : "Close the gate when you're done to get quizzed on what you built."}</p>
        </div>
        <div className="row">
          {closed && <button className="btn" onClick={openGate} disabled={!!busy}><Unlock /> Open gate</button>}
          {closed ? (
            <button className="btn primary" onClick={() => go("gate")}>Go to quiz</button>
          ) : (
            <button className="btn primary" onClick={closeGate} disabled={!!busy || fresh.length === 0}>
              {busy === "close" ? <><Spinner /> Claude is reading your day…</> : <><Lock /> Close gate &amp; quiz me</>}
            </button>
          )}
        </div>
      </section>

      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
      {data.due > 0 && (
        <div className="note blue"><Info /><div>{data.due} concept{data.due > 1 ? "s are" : " is"} due for review.{" "}
          <a href="#review">Review now</a></div></div>
      )}

      <div className="cols">
        <section className="panel side" aria-labelledby="src">
          <h2 id="src">Sources</h2>
          <div className="item">
            <div className="top"><span style={{ fontWeight: 500 }}>Claude Code</span>
              <span className="mono" style={{ color: data.hook.installed ? "var(--green)" : "var(--accent)" }}>
                {data.hook.installed ? "● hooked" : "○ no hook"}</span></div>
            <span className="mono muted">{data.hook.installed
              ? (data.hook.last_seen ? `last reply ${fmtTime(data.hook.last_seen)}` : "waiting for first reply")
              : "scanning ~/.claude/projects instead"}</span>
            {!data.hook.installed && (
              <button className="btn small" style={{ marginTop: 8 }} onClick={installHook} disabled={!!busy}>
                {busy === "hook" ? "Installing…" : data.hook.stale ? "Repair Stop hook" : "Install Stop hook"}</button>
            )}
          </div>
          <div className="item">
            <div className="top"><span style={{ fontWeight: 500 }}>Git</span>
              <span className="mono" style={{ color: data.repos.length ? "var(--green)" : "var(--muted)" }}>
                {data.repos.length ? `● ${data.repos.length} repo${data.repos.length > 1 ? "s" : ""}` : "○ none"}</span></div>
            <span className="mono muted">
              {data.commits.filter((c) => c.hash).length} commits today</span>
          </div>
          {data.shell && (
            <div className="item">
              <div className="top"><span style={{ fontWeight: 500 }}>Shell</span>
                <span className="mono" style={{ color: data.shell.enabled ? "var(--green)" : "var(--muted)" }}>
                  {data.shell.enabled ? `● ${data.shell.today} today` : "○ off"}</span></div>
              <span className="mono muted">{data.shell.enabled
                ? (data.shell.folders.length ? `in ${data.shell.folders.length} folder${data.shell.folders.length > 1 ? "s" : ""}` : "no folders chosen yet")
                : "commands you type yourself"}</span>
              {!data.shell.enabled && (
                <button className="btn small" style={{ marginTop: 8 }} onClick={() => go("settings")}>Set up shell capture</button>
              )}
            </div>
          )}
          <button className="btn small" onClick={() => go("settings")}>Manage repos</button>
        </section>

        <section className="panel wide" aria-labelledby="tl">
          <h2 id="tl">Today's sessions</h2>
          {sessions.length === 0 && (
            <div className="empty">
              <div>No Claude Code sessions today.</div>
              <div className="muted">Open Claude Code and build something. Sessions show up here automatically.</div>
            </div>
          )}
          {sessions.map((s) => (
            <button key={s.id} onClick={() => setPicked(s.id)}
              className={`session ${active?.id === s.id ? "on" : ""} ${s.after_open ? "" : "old"}`}>
              <span className="time">{fmtTime(s.start)}</span>
              <span style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, flex: 1 }}>
                <span className="row" style={{ justifyContent: "space-between" }}>
                  <span className="title">{s.title}</span>
                  <span className="muted" style={{ fontSize: 13 }}>
                    {s.kind === "shell"
                      ? <>{s.minutes} min · {s.commands} command{s.commands === 1 ? "" : "s"}{s.failed ? ` · ${s.failed} failed` : ""}</>
                      : <>{s.minutes} min · {s.files.length} file{s.files.length === 1 ? "" : "s"}</>}
                    {!s.after_open && " · already quizzed"}</span>
                </span>
                <span className="tags">
                  {s.kind === "shell" && <span className="tag typed">you typed</span>}
                  {s.project && <span className="tag">{s.project}</span>}
                  {s.files.slice(0, 4).map((f) => <span key={f} className="tag">{f}</span>)}
                </span>
              </span>
            </button>
          ))}
        </section>

        <section className="panel side" style={{ flexBasis: 320 }} aria-labelledby="live">
          <h2 id="live">Live capture</h2>
          {active ? (
            <>
              <div style={{ fontWeight: 600, fontSize: 17 }}>{active.title}</div>
              <div className="log" aria-live="polite">
                {active.log.map((l, i) => (
                  <div key={i}><span className="t">{l.t}</span>
                    <span className={`who-${l.who}${l.exit ? " failed" : ""}`}>{l.who === "you" || l.who === "claude" ? `${l.who}: ` : ""}{l.text}</span></div>
                ))}
              </div>
              <div className="muted" style={{ fontSize: 13 }}>Updates every few seconds while you work.</div>
            </>
          ) : <div className="muted">Pick a session to see what was captured.</div>}
        </section>
      </div>
    </main>
  );
}
