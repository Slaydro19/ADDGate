import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { Logo, Refresh, Spinner } from "./icons.jsx";
import Auth from "./pages/Auth.jsx";
import Connect from "./pages/Connect.jsx";
import Gate from "./pages/Gate.jsx";
import Study from "./pages/Study.jsx";
import Vault from "./pages/Vault.jsx";
import Settings from "./pages/Settings.jsx";
import Stats from "./pages/Stats.jsx";

const PAGES = { gate: "Gate", study: "Study", vault: "Vault", stats: "Stats", settings: "Settings" };
const LEGACY = { capture: "gate", terminal: "gate", review: "study" };   // old bookmarks and links
const pageFromHash = () => {
  const h = location.hash.slice(1);
  return h in PAGES ? h : LEGACY[h] || "gate";
};

function UsageMeter({ usage }) {
  if (!usage) return null;
  const k = (n) => (n >= 1000 ? `${Math.round(n / 100) / 10}k` : `${n}`);
  const label = usage.level === "red" ? "Limit reached" : "Today";
  const title = usage.limit_message
    || "ADDGate's own Claude calls today (cached instructions not counted). Your real plan usage is in Claude: Settings → Usage.";
  return (
    <div className={`meter ${usage.level}`} title={title}>
      <span>{label}</span>
      <span className="mono">~{k(usage.tokens)} tokens</span>
      {(usage.limit > 0 || usage.level === "red") && (
        <div className="bar" role="img" aria-label={usage.level === "red" ? "Claude limit reached" : `${usage.percent}% of your ${k(usage.limit)} token warning`}>
          <div className="fill" style={{ width: `${usage.level === "red" ? 100 : Math.min(100, usage.percent)}%` }} />
        </div>
      )}
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
    const lost = () => checkConn(false);  // server already knows it's disconnected; this costs nothing
    addEventListener("addgate:claude-lost", lost);
    return () => removeEventListener("addgate:claude-lost", lost);
  }, [checkConn]);
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
  if (!signedIn) return <Auth hasUsers={auth.has_users} onSignedIn={(user) => { setAuth({ user, has_users: true }); setPage("gate"); location.hash = "gate"; }} />;
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
              {label}{key === "study" && dueCount > 0 && <span className="count">{dueCount}</span>}
            </button>
          ))}
        </nav>
        <div className="topright">
          <UsageMeter usage={usage} />
          <button className="conn" onClick={retry} disabled={conn.checking} title="Re-check the Claude Code connection">
            <span className="dot" aria-hidden="true" />
            {conn.checking ? "Checking…" : "Claude"}
            {conn.checking && <Refresh spinning size={14} />}
          </button>
          <UserMenu user={auth.user} onSignOut={signOut} go={go} />
        </div>
      </header>
      {page === "gate" && <Gate {...props} />}
      {page === "study" && <Study {...props} />}
      {page === "vault" && <Vault {...props} />}
      {page === "stats" && <Stats {...props} />}
      {page === "settings" && <Settings {...props} />}
    </>
  );
}
