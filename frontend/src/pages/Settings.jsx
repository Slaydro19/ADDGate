import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { Check, Info, Spinner } from "../icons.jsx";

function PasswordForm() {
  const [f, setF] = useState({ current: "", new: "", confirm: "" });
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => { setMsg(null); setF({ ...f, [k]: e.target.value }); };
  async function submit(e) {
    e.preventDefault();
    if (f.new !== f.confirm) { setMsg({ bad: true, text: "New passwords don't match." }); return; }
    setBusy(true);
    try {
      await api("/auth/password", { method: "POST", body: { current: f.current, new: f.new } });
      setF({ current: "", new: "", confirm: "" }); setMsg({ text: "Password changed." });
    } catch (err) { setMsg({ bad: true, text: err.message }); }
    finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="cols" style={{ gap: 12 }}>
        <div className="field" style={{ flex: "1 1 180px" }}><label htmlFor="cp">Current password</label>
          <input id="cp" type="password" autoComplete="current-password" value={f.current} onChange={set("current")} /></div>
        <div className="field" style={{ flex: "1 1 180px" }}><label htmlFor="np">New password</label>
          <input id="np" type="password" autoComplete="new-password" value={f.new} onChange={set("new")} /></div>
        <div className="field" style={{ flex: "1 1 180px" }}><label htmlFor="np2">Confirm new</label>
          <input id="np2" type="password" autoComplete="new-password" value={f.confirm} onChange={set("confirm")} /></div>
      </div>
      <div className="row">
        <button className="btn" type="submit" disabled={busy || !f.current || !f.new}>Change password</button>
        {msg && <span role="status" style={{ color: msg.bad ? "var(--red)" : "var(--green)" }}>{msg.text}</span>}
      </div>
    </form>
  );
}

function TerminalSettings({ go }) {
  const [st, setSt] = useState(null);
  const [events, setEvents] = useState([]);
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState(null);
  const load = () => {
    api("/terminal/status").then(setSt).catch(() => {});
    api("/audit").then((r) => setEvents(r.events)).catch(() => {});
  };
  useEffect(load, []);
  if (!st) return null;
  async function turnOff(e) {
    e.preventDefault(); setMsg(null);
    try { await api("/terminal/enable", { method: "POST", body: { enabled: false, password: pw } }); setPw(""); load(); }
    catch (err) { setMsg(err.message); }
  }
  const label = { terminal_open: "Terminal opened", terminal_close: "Terminal closed", terminal_refused: "Connection refused",
    terminal_enabled: "Terminal turned on", terminal_disabled: "Terminal turned off", login_locked: "Login locked (5 wrong passwords)",
    confirm_locked: "Unlock locked (5 wrong passwords)",
    shell_capture_on: "Shell capture turned on", shell_capture_off: "Shell capture turned off",
    zshrc_hook_added: "Shell capture added to ~/.zshrc", zshrc_hook_removed: "Shell capture removed from ~/.zshrc",
    shell_history_cleared: "Captured commands deleted" };
  return (
    <section className="panel">
      <h2>Terminal and security log</h2>
      {st.enabled ? (
        <form onSubmit={turnOff} className="row" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: "1 1 220px" }}>
            <label htmlFor="offpw">The terminal is on. Password to turn it off</label>
            <input id="offpw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
          </div>
          <button className="btn" type="submit" disabled={!pw}>Turn off terminal</button>
          {msg && <span role="alert" style={{ color: "var(--red)" }}>{msg}</span>}
        </form>
      ) : (
        <div className="row"><span className="muted">The terminal is off.</span>
          <button className="btn small" onClick={() => go("gate")}>Set it up in Gate</button></div>
      )}
      <div className="audit" aria-label="Security log">
        {events.length === 0 && <span className="muted">Nothing logged yet.</span>}
        {events.map((e, i) => (
          <div key={i}>
            <span className="mono muted">{new Date(e.at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
            <span>{label[e.event] || e.event}</span>
            <span className="faint">{e.detail}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ShellSettings() {
  const [st, setSt] = useState(null);
  const [folders, setFolders] = useState("");
  const [msg, setMsg] = useState(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const apply = (r) => { setSt(r); setFolders((r.folders || []).join("\n")); };
  useEffect(() => { api("/shell/status").then(apply).catch(() => {}); }, []);
  if (!st) return null;
  const save = async (extra) => {
    setMsg(null);
    try { apply(await api("/shell/settings", { method: "POST", body: { folders: folders.split("\n").map((f) => f.trim()).filter(Boolean), ...extra } })); setMsg("Saved."); }
    catch (e) { setMsg(e.message); }
  };
  const zshrc = async (install) => {
    try { const z = await api("/shell/zshrc", { method: "POST", body: { install } }); setSt({ ...st, zshrc: z }); }
    catch (e) { setMsg(e.message); }
  };
  return (
    <div className="subsection">
      <h3>Shell capture</h3>
      <p className="muted" style={{ margin: 0, fontSize: 14.5 }}>
        Records the commands <strong>you</strong> type (not their output), so gate questions can cover your own work too.
        Only you see them. Secrets like tokens, passwords and keys are redacted before anything is saved, and the raw
        record is deleted right after. Start a command with a <strong>space</strong> and it's never recorded.
      </p>
      <div className="row">
        <span className="pill" style={{ background: st.enabled ? "var(--green-soft)" : "var(--raised)", color: st.enabled ? "var(--green)" : "var(--muted)" }}>
          <span className="dot" aria-hidden="true" />{st.enabled ? "On" : "Off"}</span>
        <button className="btn small" onClick={() => save({ enabled: !st.enabled })}>{st.enabled ? "Turn off" : "Turn on"}</button>
      </div>
      <div className="field">
        <label htmlFor="sfold">Only capture inside these folders (one per line)</label>
        <textarea id="sfold" value={folders} onChange={(e) => setFolders(e.target.value)} placeholder={"/Users/you/code/homelab\n/Users/you/ctf"} style={{ minHeight: 90 }} />
        <span className="faint">
          {st.folders.length ? "Commands anywhere else are ignored." :
            st.effective_folders.length ? `Empty, so your git repos are used: ${st.effective_folders.join(", ")}` :
            "Nothing chosen and no git repos set, so nothing is captured yet."}
        </span>
      </div>
      <div><button className="btn" onClick={() => save({})}>Save folders</button>{msg && <span className="faint" role="status" style={{ marginLeft: 10 }}>{msg}</span>}</div>

      <div className="item" style={{ gap: 8 }}>
        <div style={{ fontWeight: 500 }}>Where it captures</div>
        <div className="faint">ADDGate's built-in Terminal: automatically (zsh).</div>
        <div className="faint">Your regular Terminal app: {st.zshrc.installed ? "yes, via ~/.zshrc" : "not yet"}.</div>
        <div className="row">
          {st.zshrc.installed
            ? <button className="btn small" onClick={() => zshrc(false)}>Remove from ~/.zshrc</button>
            : <button className="btn small" onClick={() => zshrc(true)}>Add to ~/.zshrc (backs it up first)</button>}
        </div>
        {!st.zshrc.installed && <div className="faint">Or add this line yourself: <code>{st.zshrc.line}</code> Open terminals pick it up after restarting.</div>}
      </div>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="faint">{st.stored} command{st.stored === 1 ? "" : "s"} stored</span>
        {st.stored > 0 && (confirmClear
          ? <span className="row"><span className="faint">Delete all of them?</span>
              <button className="btn small" onClick={async () => { apply(await api("/shell/clear", { method: "POST" })); setConfirmClear(false); }}>Yes, delete</button>
              <button className="btn small" onClick={() => setConfirmClear(false)}>Cancel</button></span>
          : <button className="btn small" onClick={() => setConfirmClear(true)}>Delete captured commands</button>)}
      </div>
    </div>
  );
}

export default function Settings({ user, go }) {
  const [cfg, setCfg] = useState(null);
  const [repos, setRepos] = useState("");
  const [saved, setSaved] = useState(false);
  const [hook, setHook] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/config").then((c) => { setCfg(c); setRepos(c.repos.join("\n")); });
    api("/capture").then((d) => setHook(d.hook));
  }, []);

  if (!cfg) return <main><div className="row muted"><Spinner /> Loading…</div></main>;
  const set = (k) => (e) => { setSaved(false); setCfg({ ...cfg, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value }); };

  async function save() {
    setError(null);
    try {
      const next = await api("/config", { method: "PUT", body: { ...cfg, repos: repos.split("\n").map((r) => r.trim()).filter(Boolean) } });
      setCfg(next); setRepos(next.repos.join("\n")); setSaved(true);
    } catch (e) { setError(e.message); }
  }
  async function installHook() {
    try { setHook(await api("/hook/install", { method: "POST" })); } catch (e) { setError(e.message); }
  }

  return (
    <main style={{ maxWidth: 760 }}>
      <section className="hero"><div><div className="eyebrow">Settings</div><h1>Setup</h1>
        <p className="sub">These settings are just for your account.</p></div></section>

      <section className="panel">
        <h2>Account</h2>
        <div className="row" style={{ gap: 12 }}>
          <span className="avatar" aria-hidden="true">{user.display_name[0].toUpperCase()}</span>
          <div><div style={{ fontWeight: 600 }}>{user.display_name}</div><div className="faint">@{user.username}</div></div>
        </div>
        <PasswordForm />
      </section>

      <section className="panel">
        <h2>Sources</h2>
        <p className="muted" style={{ margin: 0, fontSize: 15 }}>Where ADDGate learns what you worked on.</p>

        <div className="subsection">
          <h3>Claude Code</h3>
          {hook?.installed ? (
            <div className="row" style={{ color: "var(--green)" }}><Check /> Stop hook installed in {hook.settings_path}</div>
          ) : (
            <>
              <p style={{ margin: 0 }} className="muted">The Stop hook tells ADDGate the moment Claude finishes a reply. It adds one entry to
                your Claude Code settings and backs up the file first. Without it, ADDGate scans today's transcripts instead.</p>
              {hook?.stale && <p style={{ margin: 0, color: "var(--amber)" }}>An older ADDGate hook points at a file that moved. Repairing replaces it.</p>}
              <div><button className="btn" onClick={installHook}>{hook?.stale ? "Repair Stop hook" : "Install Stop hook"}</button></div>
            </>
          )}
        </div>

        <div className="subsection">
          <h3>Git repos</h3>
          <div className="field">
            <label htmlFor="repos">One absolute path per line</label>
            <textarea id="repos" value={repos} onChange={(e) => { setSaved(false); setRepos(e.target.value); }}
              placeholder={"/Users/you/code/homelab\n/Users/you/code/ADDGate"} />
          </div>
        </div>

        {user.is_owner && <ShellSettings />}
      </section>

      {user.is_owner && <TerminalSettings go={go} />}

      <section className="panel">
        <h2>Quiz and usage</h2>
        <div className="cols" style={{ gap: 16 }}>
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label htmlFor="n">Questions per gate close</label>
            <input id="n" type="number" min="1" max="10" value={cfg.questions_per_close} onChange={set("questions_per_close")} />
          </div>
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label htmlFor="hint">Hint unlocks after (seconds)</label>
            <input id="hint" type="number" min="0" value={cfg.hint_delay_seconds} onChange={set("hint_delay_seconds")} />
          </div>
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label htmlFor="budget">Warn me after this many tokens a day (0 = off)</label>
            <input id="budget" type="number" min="0" step="10000" value={cfg.daily_token_limit} onChange={set("daily_token_limit")} />
            <span className="faint">Counts only ADDGate's own calls. Your real plan usage is in Claude → Settings → Usage.</span>
          </div>
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label htmlFor="model">Model (blank = Claude Code default)</label>
            <input id="model" type="text" value={cfg.model} onChange={set("model")} placeholder="e.g. sonnet" />
          </div>
        </div>
      </section>

      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
      <div className="row">
        <button className="btn primary" onClick={save}>Save settings</button>
        {saved && <span className="row" style={{ color: "var(--green)", gap: 6 }}><Check /> Saved</span>}
      </div>
    </main>
  );
}
