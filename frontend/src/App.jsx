import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Logo, Refresh, Spinner } from "./icons.jsx";
import Auth from "./pages/Auth.jsx";
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

function UserMenu({ user, onSignOut, go }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="usermenu" ref={ref}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu">
        <span className="avatar" aria-hidden="true">{user.display_name[0].toUpperCase()}</span>
        {user.display_name}
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="who"><div style={{ fontWeight: 600 }}>{user.display_name}</div><div className="faint">@{user.username}</div></div>
          <button role="menuitem" onClick={() => { setOpen(false); go("settings"); }}>Account settings</button>
          <button role="menuitem" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [auth, setAuth] = useState(null);   // { user, has_users }
  const [conn, setConn] = useState(null);
  const [page, setPage] = useState(pageFromHash());
  const [usage, setUsage] = useState(null);
  const [dueCount, setDueCount] = useState(0);

  const loadAuth = useCallback(() => api("/auth/me").then(setAuth).catch(() => setAuth({ user: null, has_users: true })), []);

  const checkConn = useCallback(async (refresh = false) => {
    setConn((c) => (c ? { ...c, checking: true, wasConnected: !!c.connected } : { checking: true }));
    try { setConn({ ...(await api(`/status${refresh ? "?refresh=1" : ""}`)), checkedAt: Date.now() }); }
    catch (e) { setConn({ connected: false, message: e.message, checkedAt: Date.now() }); }
  }, []);
  const retry = useCallback(() => checkConn(true), [checkConn]);

  const refreshUsage = useCallback(() => {
    api("/usage").then(setUsage).catch(() => {});
    api("/review").then((r) => setDueCount(r.due.length)).catch(() => {});
  }, []);

  const signedIn = !!auth?.user;

  useEffect(() => { loadAuth(); }, [loadAuth]);
  useEffect(() => {
    const out = () => setAuth((a) => ({ ...(a || {}), user: null, has_users: true }));
    addEventListener("addgate:signed-out", out);
    return () => removeEventListener("addgate:signed-out", out);
  }, []);
  useEffect(() => { if (signedIn) checkConn(); }, [signedIn, checkConn]);
  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (!signedIn || !conn?.connected) return;
    refreshUsage();
    const id = setInterval(refreshUsage, 30000);
    return () => clearInterval(id);
  }, [signedIn, conn?.connected, refreshUsage]);

  const go = (p) => { location.hash = p; setPage(p); refreshUsage(); };

  async function signOut() {
    try { await api("/auth/logout", { method: "POST" }); } catch { /* already signed out */ }
    setAuth({ user: null, has_users: true });
    setConn(null); setUsage(null); setDueCount(0);
    location.hash = "";
  }

  if (!auth) return <div className="center"><div className="row muted"><Spinner /> Loading…</div></div>;
  if (!signedIn) return <Auth hasUsers={auth.has_users} onSignedIn={(user) => { setAuth({ user, has_users: true }); setPage("capture"); location.hash = "capture"; }} />;
  if (!conn || (!conn.connected && !(conn.checking && conn.wasConnected))) return <Connect conn={conn} onRetry={retry} />;

  const props = { go, refreshUsage, user: auth.user };
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
          <button className="pill ok" style={{ border: 0, cursor: "pointer" }} onClick={retry} disabled={conn.checking}
            title="Re-check the Claude Code connection">
            <span className="dot" aria-hidden="true" />
            {conn.checking ? "Checking…" : "Claude connected"}
            <Refresh spinning={conn.checking} size={14} />
          </button>
          <UserMenu user={auth.user} onSignOut={signOut} go={go} />
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
