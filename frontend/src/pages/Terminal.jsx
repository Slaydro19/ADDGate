import React, { useCallback, useEffect, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api.js";
import { Info, Lock, Spinner } from "../icons.jsx";

const THEME = {
  background: "#0b0d11", foreground: "#e8e6e1", cursor: "#f5a524", cursorAccent: "#0b0d11",
  selectionBackground: "#3a3f4b", black: "#1c2029", brightBlack: "#6b7280",
};

function PasswordGate({ title, body, button, onSubmit, danger }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await onSubmit(pw); setPw(""); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return (
    <form className="panel" onSubmit={submit} style={{ maxWidth: 560 }}>
      <h2>{title}</h2>
      <div className="muted" style={{ fontSize: 14.5 }}>{body}</div>
      <div className="field">
        <label htmlFor="tpw">Your ADDGate password</label>
        <input id="tpw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
      </div>
      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
      <div><button className={`btn ${danger ? "" : "primary"}`} type="submit" disabled={busy || !pw}>
        {busy ? <><Spinner /> Checking…</> : button}</button></div>
    </form>
  );
}

function Shell({ onLocked }) {
  const box = useRef(null);
  const [state, setState] = useState("connecting"); // connecting | open | closed
  const [note, setNote] = useState(null);
  const [gen, setGen] = useState(0);

  useEffect(() => {
    let ws, disposed = false;
    const term = new XTerm({
      cursorBlink: true, fontFamily: '"JetBrains Mono", ui-monospace, Menlo, monospace', fontSize: 13.5,
      theme: THEME, scrollback: 5000, allowProposedApi: false,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(box.current);
    fit.fit();
    term.focus();
    const sendSize = () => ws?.readyState === 1 && ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    const ro = new ResizeObserver(() => { try { fit.fit(); sendSize(); } catch { /* hidden */ } });
    ro.observe(box.current);
    const input = term.onData((data) => ws?.readyState === 1 && ws.send(JSON.stringify({ type: "input", data })));

    (async () => {
      setState("connecting"); setNote(null);
      let ticket;
      try { ticket = (await api("/terminal/ticket", { method: "POST" })).ticket; }
      catch (e) {
        if (e.kind === "reauth") { onLocked(); return; }
        setNote(e.message); setState("closed"); return;
      }
      if (disposed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/terminal?ticket=${encodeURIComponent(ticket)}`);
      ws.onopen = () => { setState("open"); sendSize(); };
      ws.onmessage = (ev) => {
        if (ev.data.startsWith("\u0000")) {  // control message from ADDGate, never shell output
          let msg = {};
          try { msg = JSON.parse(ev.data.slice(1)); } catch { /* ignore */ }
          if (msg.type === "exit") {
            term.write(`\r\n\x1b[90m[terminal closed: ${msg.reason || "ended"}]\x1b[0m\r\n`);
            ws.close();
          }
          return;
        }
        term.write(ev.data);
      };
      ws.onclose = () => { if (!disposed) setState("closed"); };
    })();

    return () => { disposed = true; input.dispose(); ro.disconnect(); try { ws?.close(); } catch { /* */ } term.dispose(); };
  }, [gen, onLocked]);

  return (
    <section className="panel termpanel" aria-label="Terminal">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="row" style={{ gap: 8 }}>
          <span className={`tdot ${state}`} aria-hidden="true" />
          <span className="mono muted">{state === "open" ? "connected · your Mac's shell" : state === "connecting" ? "connecting…" : "disconnected"}</span>
        </span>
        {state === "closed" && <button className="btn small" onClick={() => setGen((g) => g + 1)}>New session</button>}
      </div>
      {note && <div className="note red" role="alert"><Info /><div>{note}</div></div>}
      <div className="xterm-box" ref={box} />
    </section>
  );
}

export default function TerminalPage({ go }) {
  const [st, setSt] = useState(null);
  const load = useCallback(() => api("/terminal/status").then(setSt), []);
  useEffect(() => { load(); }, [load]);
  const locked = useCallback(() => setSt((s) => ({ ...s, unlocked: false })), []);

  if (!st) return <main><div className="row muted"><Spinner /> Loading…</div></main>;

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Terminal</div>
          <h1>A real shell on your Mac.</h1>
          <p className="sub">Runs as your Mac user, in your home folder. Claude Code sessions you start here get captured like any other.</p>
        </div>
        {st.enabled && st.unlocked && (
          <span className="pill ok"><Lock /> Unlocked for {Math.max(1, Math.round(st.unlocked_seconds / 60))} min</span>
        )}
      </section>

      {!st.allowed && (
        <div className="panel"><div className="empty">
          <div style={{ fontSize: 18, fontWeight: 600 }}>Only this Mac's owner can use the terminal.</div>
          <div className="muted">The terminal runs commands as the Mac user, so it's limited to the first account created here.</div>
        </div></div>
      )}

      {st.allowed && !st.enabled && (
        <PasswordGate title="Turn on the terminal"
          body={<>The terminal gives this browser tab full control of your Mac user account, so it's off until you turn it on.
            Only you (the owner) can use it, every session needs your password within the last 15 minutes, and other
            websites can't connect to it. Every session is logged in Settings.</>}
          button="Turn on terminal"
          onSubmit={async (password) => { await api("/terminal/enable", { method: "POST", body: { enabled: true, password } }); await load(); }} />
      )}

      {st.allowed && st.enabled && !st.unlocked && (
        <PasswordGate title="Confirm it's you"
          body="Enter your password to unlock the terminal for 15 minutes."
          button="Unlock terminal"
          onSubmit={async (password) => { await api("/auth/confirm", { method: "POST", body: { password } }); await load(); }} />
      )}

      {st.allowed && st.enabled && st.unlocked && <Shell onLocked={locked} />}
    </main>
  );
}
