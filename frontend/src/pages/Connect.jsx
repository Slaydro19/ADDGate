import React from "react";
import { Logo, Spinner } from "../icons.jsx";

const HELP = {
  missing: <>Install Claude Code, then make sure <code>claude</code> runs in your terminal.</>,
  auth: <>Open a terminal, run <code>claude</code>, and sign in with your Claude account. Then retry.</>,
  limit: <>You've hit your Claude usage limit. ADDGate will work again once it resets.</>,
};

export default function Connect({ conn, onRetry }) {
  const checking = !conn || conn.checking;
  return (
    <div className="center">
      <div className="card">
        <div className="brand"><Logo /> ADDGate</div>
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
        <button className="btn primary" onClick={onRetry} disabled={checking}>
          {checking ? "Checking…" : "Connect Claude Code"}
        </button>
      </div>
    </div>
  );
}
