import React, { useCallback, useEffect, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api.js";
import { Info, Spinner } from "../icons.jsx";

const THEME = {
  background: "#26251e", foreground: "#dfdedb", cursor: "#9db8ff", cursorAccent: "#26251e",
  selectionBackground: "#4a483f", black: "#313029", brightBlack: "#9e9d99",
};

function PasswordGate({ title, body, button, onSubmit }) {
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
    <form className="panel" onSubmit={submit} style={{ maxWidth: 520, margin: "auto" }}>
      <h2>{title}</h2>
      <div className="muted" style={{ fontSize: 15 }}>{body}</div>
      <div className="field">
        <label htmlFor="tpw">Your ADDGate password</label>
        <input id="tpw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
      </div>
      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
      <div><button className="btn primary" type="submit" disabled={busy || !pw}>
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
      cursorBlink: true, fontFamily: '"DM Mono", ui-monospace, Menlo, monospace', fontSize: 13.5,
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
    <div className="termwrap" aria-label="Terminal">
      <div className="termbar">
        <span><span className={`tdot ${state}`} aria-hidden="true" />
          {state === "open" ? "your Mac's shell" : state === "connecting" ? "connecting…" : "disconnected"}</span>
        {state === "closed" && <button className="btn small" style={{ color: "#dfdedb", borderColor: "rgba(255,255,255,.3)" }}
          onClick={() => setGen((g) => g + 1)}>New session</button>}
      </div>
      {note && <div className="note red" role="alert" style={{ margin: 12 }}><Info /><div>{note}</div></div>}
      <div className="xterm-box" ref={box} />
    </div>
  );
}

/** The terminal for the Gate tab: turn on, unlock, then the shell. Owner only. */
export default function TerminalArea() {
  const [st, setSt] = useState(null);
  const load = useCallback(() => api("/terminal/status").then(setSt), []);
  useEffect(() => { load(); }, [load]);
  const locked = useCallback(() => setSt((s) => ({ ...s, unlocked: false })), []);

  if (!st) return <div className="termwrap"><div className="row muted" style={{ margin: "auto", color: "#9e9d99" }}><Spinner /> Loading…</div></div>;

  if (!st.enabled) {
    return (
      <PasswordGate title="Turn on the terminal"
        body={<>The terminal gives this browser tab full control of your Mac user account, so it's off until you turn it on.
          Every session needs your password within the last 15 minutes, and other websites can't connect to it.
          Every session is logged in Settings.</>}
        button="Turn on terminal"
        onSubmit={async (password) => { await api("/terminal/enable", { method: "POST", body: { enabled: true, password } }); await load(); }} />
    );
  }
  if (!st.unlocked) {
    return (
      <PasswordGate title="Confirm it's you" body="Enter your password to unlock the terminal for 15 minutes." button="Unlock terminal"
        onSubmit={async (password) => { await api("/auth/confirm", { method: "POST", body: { password } }); await load(); }} />
    );
  }
  return <Shell onLocked={locked} />;
}
