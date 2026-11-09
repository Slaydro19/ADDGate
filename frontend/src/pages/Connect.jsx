import React, { useEffect } from "react";
import { Logo, Refresh, Spinner } from "../icons.jsx";

const HELP = {
  missing: <>Install Claude Code, then make sure <code>claude</code> runs in your terminal.</>,
  auth: <>Open a terminal, run <code>claude</code>, and sign in with your Claude account. Then refresh.</>,
  limit: <>You've hit your Claude usage limit. ADDGate will work again once it resets.</>,
  timeout: <>Claude Code didn't answer in time. Check that <code>claude -p "hi"</code> works in your terminal, then refresh.</>,
};

export default function Connect({ conn, onRetry }) {
  const checking = !conn || conn.checking;

  // Keep re-checking quietly every 15s while disconnected, so signing in elsewhere just works.
  useEffect(() => {
    if (checking) return;
    const id = setTimeout(onRetry, 15000);
    return () => clearTimeout(id);
  }, [checking, conn?.checkedAt, onRetry]);

  return (
    <div className="center">
      <div className="card">
        <div className="brand"><Logo size={32} /> <span><b>ADD</b><span className="light">Gate</span></span></div>
        <div>
          <h1 style={{ fontSize: 26 }}>Connect to Claude</h1>
          <p className="sub">ADDGate runs on your own Claude subscription through Claude Code.
            No API key, and your work never leaves this machine except to Claude.</p>
        </div>
        {checking ? (
          <div className="row muted"><Spinner /> Checking Claude Code…</div>
        ) : (
          <div className="note red" role="alert">
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Not connected</div>
              <div>{HELP[conn.kind] || conn.message}</div>
              {conn.kind && conn.message && <div className="mono" style={{ marginTop: 8, opacity: .8 }}>{conn.message}</div>}
            </div>
          </div>
        )}
        <div className="row">
          <button className="btn primary" style={{ flex: 1 }} onClick={onRetry} disabled={checking}>
            {checking ? "Checking…" : "Connect Claude Code"}
          </button>
          <button className="btn" onClick={onRetry} disabled={checking} aria-label="Refresh connection status">
            <Refresh spinning={checking} /> Refresh
          </button>
        </div>
        {!checking && conn?.checkedAt && (
          <div className="muted" style={{ fontSize: 13 }}>
            Last checked {new Date(conn.checkedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}
            {" "}· checking again automatically
          </div>
        )}
      </div>
    </div>
  );
}
