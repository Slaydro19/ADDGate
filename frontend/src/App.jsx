import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { Logo } from "./icons.jsx";
import Connect from "./pages/Connect.jsx";
import Capture from "./pages/Capture.jsx";
import Gate from "./pages/Gate.jsx";
import Review from "./pages/Review.jsx";
import Vault from "./pages/Vault.jsx";
import Settings from "./pages/Settings.jsx";

const PAGES = { capture: "Capture", gate: "Gate", review: "Review", vault: "Vault", settings: "Settings" };
const pageFromHash = () => (location.hash.slice(1) in PAGES ? location.hash.slice(1) : "capture");

function UsageMeter({ usage }) {
  if (!usage) return null;
  const pct = Math.min(100, usage.percent);
  const label = usage.level === "red" ? "Claude limit reached"
    : usage.level === "amber" ? "Heavy ADDGate usage today" : "ADDGate usage today";
  return (
    <div className={`meter ${usage.level}`} title={usage.limit_message || `${usage.calls} Claude calls today`}>
      <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <span>{label}</span>
        <span className="mono">{Math.round(usage.tokens / 1000)}k / {Math.round(usage.budget / 1000)}k</span>
      </div>
      <div className="bar" role="img" aria-label={`${pct}% of daily token budget`}>
        <div className="fill" style={{ width: `${usage.level === "red" ? 100 : pct}%` }} />
      </div>
    </div>
  );
}

export default function App() {
  const [conn, setConn] = useState(null);
  const [page, setPage] = useState(pageFromHash());
  const [usage, setUsage] = useState(null);
  const [dueCount, setDueCount] = useState(0);

  const checkConn = useCallback(async (refresh = false) => {
    setConn((c) => (c ? { ...c, checking: true } : { checking: true }));
    try { setConn(await api(`/status${refresh ? "?refresh=1" : ""}`)); }
    catch (e) { setConn({ connected: false, message: e.message }); }
  }, []);

  const refreshUsage = useCallback(() => {
    api("/usage").then(setUsage).catch(() => {});
    api("/review").then((r) => setDueCount(r.due.length)).catch(() => {});
  }, []);

  useEffect(() => { checkConn(); }, [checkConn]);
  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (!conn?.connected) return;
    refreshUsage();
    const id = setInterval(refreshUsage, 30000);
    return () => clearInterval(id);
  }, [conn?.connected, refreshUsage]);

  const go = (p) => { location.hash = p; setPage(p); refreshUsage(); };

  if (!conn || !conn.connected) return <Connect conn={conn} onRetry={() => checkConn(true)} />;

  const props = { go, refreshUsage };
  return (
    <>
      <header className="topbar">
        <div className="brand"><Logo /> ADDGate</div>
        <nav className="nav" aria-label="Main">
          {Object.entries(PAGES).map(([key, label]) => (
            <button key={key} className={page === key ? "on" : ""} aria-current={page === key ? "page" : undefined}
              onClick={() => go(key)}>
              {label}{key === "review" && dueCount > 0 && <span className="count">{dueCount}</span>}
            </button>
          ))}
        </nav>
        <div className="topright">
          <UsageMeter usage={usage} />
          <span className="pill ok"><span className="dot" aria-hidden="true" />Connected via Claude Code</span>
        </div>
      </header>
      {page === "capture" && <Capture {...props} />}
      {page === "gate" && <Gate {...props} />}
      {page === "review" && <Review {...props} />}
      {page === "vault" && <Vault {...props} />}
      {page === "settings" && <Settings {...props} />}
    </>
  );
}
