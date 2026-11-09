import React, { useCallback, useEffect, useState } from "react";
import { api, fmtDate } from "../api.js";
import { Check, Info, Spinner } from "../icons.jsx";

/* Admin console. Counts, dates and token totals only: nothing here can show anyone's answers, vault,
   transcripts or typed commands. Destructive actions ask for the admin's own password first. */

const ago = (iso) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return fmtDate(iso.slice(0, 10));
};
const k = (n) => (n >= 1000 ? `${Math.round(n / 100) / 10}k` : `${n}`);
const bytes = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const when = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const EVENTS = {
  login: "Signed in", login_failed: "Wrong password", login_locked: "Locked after 5 wrong passwords", confirm_locked: "Unlock locked",
  account_created: "Account created (sign-up)", password_changed: "Changed own password",
  admin_user_created: "Admin created an account", admin_made: "Made an admin", admin_removed: "Removed an admin",
  account_disabled: "Turned an account off", account_enabled: "Turned an account on", password_reset: "Reset a password",
  account_unlocked: "Unlocked an account", signed_out_by_admin: "Signed an account out", token_cap_set: "Set a token cap",
  account_deleted: "Deleted an account", settings_changed: "Changed settings", backup_created: "Made a backup",
  backup_deleted: "Deleted a backup", backup_restored: "Restored a backup",
  terminal_open: "Terminal opened", terminal_close: "Terminal closed", terminal_refused: "Terminal refused",
  terminal_enabled: "Terminal turned on", terminal_disabled: "Terminal turned off",
  shell_capture_on: "Shell capture on", shell_capture_off: "Shell capture off",
};

/* ── re-enter your password before anything destructive ── */
function ReauthModal({ onDone, onCancel }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onCancel]);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/auth/confirm", { method: "POST", body: { password: pw } }); onDone(); }
    catch (err) { setError(err.message); setBusy(false); }
  }
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="reauth-t" onSubmit={submit}>
        <h2 id="reauth-t" style={{ margin: 0, font: "500 22px var(--font)", textTransform: "none", letterSpacing: "-.02em", color: "var(--ink)" }}>Confirm it's you</h2>
        <p className="muted" style={{ margin: 0 }}>Enter your own password. It unlocks admin actions for 15 minutes.</p>
        <div className="field">
          <label htmlFor="reauth-pw">Your password</label>
          <input id="reauth-pw" type="password" autoComplete="current-password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} />
        </div>
        {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
        <div className="row">
          <button className="btn primary" type="submit" disabled={busy || !pw}>{busy ? <><Spinner /> Checking…</> : "Confirm"}</button>
          <button className="btn" type="button" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

function useReauth() {
  const [pending, setPending] = useState(null);
  const guard = useCallback(async (fn) => {
    try { return await fn(); }
    catch (e) {
      if (e.kind !== "reauth") throw e;
      await new Promise((resolve, reject) => setPending({ resolve, reject }));
      return await fn();
    }
  }, []);
  const modal = pending ? (
    <ReauthModal onDone={() => { pending.resolve(); setPending(null); }}
      onCancel={() => { const c = new Error("Cancelled."); c.kind = "cancel"; pending.reject(c); setPending(null); }} />
  ) : null;
  return [guard, modal];
}

function Flash({ flash, onClose }) {
  const [copied, setCopied] = useState(false);
  if (!flash) return null;
  return (
    <div className={`note ${flash.bad ? "red" : "blue"}`} role={flash.bad ? "alert" : "status"} style={{ alignItems: "center" }}>
      <Info />
      <div style={{ flex: 1 }}>
        {flash.text}
        {flash.temp && (
          <div className="row" style={{ marginTop: 8 }}>
            <code style={{ fontSize: 16, padding: "4px 10px", userSelect: "all" }}>{flash.temp}</code>
            <button className="btn small" onClick={() => { navigator.clipboard?.writeText(flash.temp); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
            <span className="faint">Shown once. They choose their own at next sign-in.</span>
          </div>
        )}
      </div>
      <button className="linkbtn" onClick={onClose}>Dismiss</button>
    </div>
  );
}

/* ── accounts ── */
function AddAccount({ onCreated, onCancel, guard }) {
  const [f, setF] = useState({ username: "", display_name: "", password: "", is_admin: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (key) => (e) => setF({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { onCreated(await api("/admin/users", { method: "POST", body: f })); }
    catch (err) { setError(err.message); setBusy(false); }
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>New account</h2>
      <div className="cols" style={{ gap: 14 }}>
        <div className="field" style={{ flex: "1 1 180px" }}><label htmlFor="na-u">Username</label>
          <input id="na-u" type="text" autoCapitalize="none" spellCheck="false" autoFocus value={f.username} onChange={set("username")} /></div>
        <div className="field" style={{ flex: "1 1 180px" }}><label htmlFor="na-d">Name <span className="faint">(optional)</span></label>
          <input id="na-d" type="text" value={f.display_name} onChange={set("display_name")} /></div>
        <div className="field" style={{ flex: "1 1 220px" }}><label htmlFor="na-p">Password <span className="faint">(blank makes a temporary one)</span></label>
          <input id="na-p" type="text" autoComplete="off" value={f.password} onChange={set("password")} /></div>
      </div>
      <label className="check"><input type="checkbox" checked={f.is_admin} onChange={set("is_admin")} /> Make this account an admin</label>
      <div className="faint">Either way, they'll be asked to choose their own password the first time they sign in.</div>
      {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
      <div className="row">
        <button className="btn primary" type="submit" disabled={busy || !f.username}>{busy ? <><Spinner /> Creating…</> : "Create account"}</button>
        <button className="btn" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Manage({ u, me, run, onDone }) {
  const [cap, setCap] = useState(String(u.account_token_cap || 0));
  const [del, setDel] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const self = u.id === me.id;
  const post = (path, body, ok, extra) => run(() => api(`/admin/users/${u.id}${path}`, { method: "POST", body: body || {} }), ok, extra);
  return (
    <div className="manage">
      <div className="row">
        <button className="btn small" onClick={() => post("/role", { is_admin: !u.is_admin }, u.is_admin ? `${u.username} is no longer an admin.` : `${u.username} is now an admin.`)}>
          {u.is_admin ? "Remove admin" : "Make admin"}</button>
        <button className="btn small" onClick={() => post("/reset-password", {}, `Temporary password for ${u.username}.`, (r) => ({ temp: r.temp_password }))}>Reset password</button>
        {u.locked && <button className="btn small" onClick={() => post("/unlock", {}, `${u.username} is unlocked.`)}>Unlock</button>}
        {!self && <button className="btn small" onClick={() => post("/signout", {}, `${u.username} was signed out everywhere.`)}>Sign out everywhere</button>}
        {!self && <button className="btn small" onClick={() => post("/disabled", { disabled: !u.disabled }, u.disabled ? `${u.username} is back on.` : `${u.username} is turned off.`)}>
          {u.disabled ? "Turn on" : "Turn off"}</button>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); post("/cap", { cap: Number(cap) || 0 }, Number(cap) ? `${u.username} is capped at ${k(Number(cap))} tokens a day.` : `${u.username} has no daily cap.`); }}>
        <label htmlFor={`cap-${u.id}`} style={{ minWidth: 150 }}>Daily token cap</label>
        <input id={`cap-${u.id}`} type="number" min="0" step="1000" value={cap} onChange={(e) => setCap(e.target.value)} style={{ width: 140 }} />
        <button className="btn small" type="submit">Save</button>
        <span className="faint">ADDGate's own Claude tokens for this account. 0 = no cap.</span>
      </form>
      {!self && (!del ? (
        <div><button className="btn small danger" onClick={() => setDel(true)}>Delete account…</button></div>
      ) : (
        <form className="row danger-zone" onSubmit={(e) => { e.preventDefault(); run(() => api(`/admin/users/${u.id}`, { method: "DELETE", body: { confirm: confirmName } }),
          `${u.username} was deleted. A backup was saved first.`).then(onDone); }}>
          <label htmlFor={`del-${u.id}`}>Type <strong>{u.username}</strong> to delete it and all its data</label>
          <input id={`del-${u.id}`} type="text" autoComplete="off" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} style={{ width: 200 }} />
          <button className="btn small danger" type="submit" disabled={confirmName.trim().toLowerCase() !== u.username.toLowerCase()}>Delete forever</button>
          <button className="btn small" type="button" onClick={() => { setDel(false); setConfirmName(""); }}>Cancel</button>
        </form>
      ))}
    </div>
  );
}

function Accounts({ data, reload, run, guard, me }) {
  const [open, setOpen] = useState(() => data.users.find((u) => u.username === hashPart(2))?.id || null);
  const [adding, setAdding] = useState(false);
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="faint" style={{ margin: 0, maxWidth: "62ch" }}>You see who has an account and how much it's used. Answers, vault entries, transcripts and typed commands stay private to each person.</p>
        {!adding && <button className="btn primary" onClick={() => setAdding(true)}>Add account</button>}
      </div>
      {adding && <AddAccount guard={guard} onCancel={() => setAdding(false)}
        onCreated={(r) => { setAdding(false); reload(); run(async () => r, `Created ${r.user.username}.`, (x) => ({ temp: x.temp_password })); }} />}
      <div className="acct-list" role="list">
        {data.users.map((u) => (
          <div key={u.id} className={`acct ${open === u.id ? "open" : ""} ${u.disabled ? "off" : ""}`} role="listitem">
            <div className="acct-row">
              <div className="who">
                <span className="avatar" aria-hidden="true">{u.display_name[0].toUpperCase()}</span>
                <div>
                  <div style={{ fontWeight: 600 }}>{u.display_name}{u.id === me.id && <span className="muted" style={{ fontWeight: 400 }}> (you)</span>}</div>
                  <div className="mono muted">@{u.username}</div>
                </div>
              </div>
              <div className="badges">
                {u.is_admin && <span className="badge gold">Admin</span>}
                {u.is_owner && <span className="badge">Owner</span>}
                {u.disabled && <span className="badge red">Off</span>}
                {u.locked && <span className="badge amber">Locked</span>}
                {u.must_change_password && <span className="badge amber">Temp password</span>}
              </div>
              <div className="acct-stat"><span className="lbl">Last active</span>{ago(u.last_seen)}<span className="faint"> · signed in {ago(u.last_login)}</span></div>
              <div className="acct-stat"><span className="lbl">Learning</span>{u.owned}/{u.concepts} owned<span className="faint"> · {u.gates} gates</span></div>
              <div className="acct-stat"><span className="lbl">Tokens today</span>{k(u.tokens_today)}{u.account_token_cap > 0 && <span className="faint"> of {k(u.account_token_cap)}</span>}</div>
              <button className="btn small" aria-expanded={open === u.id} onClick={() => setOpen(open === u.id ? null : u.id)}>{open === u.id ? "Close" : "Manage"}</button>
            </div>
            {open === u.id && <Manage u={u} me={me} run={run} onDone={() => setOpen(null)} />}
          </div>
        ))}
      </div>
    </>
  );
}

/* ── access: who can sign up, and what new accounts start with ── */
function Access({ data, reload, run }) {
  const [mode, setMode] = useState(data.settings.signup_mode);
  const [d, setD] = useState(data.settings.new_account);
  const set = (key) => (e) => setD({ ...d, [key]: e.target.value });
  return (
    <section className="panel">
      <h2>Sign-up</h2>
      <div className="chips" role="radiogroup" aria-label="Who can create an account">
        {[["open", "Anyone at this Mac"], ["admin_only", "Admins only"]].map(([v, label]) => (
          <button key={v} role="radio" aria-checked={mode === v} className={mode === v ? "on" : ""} onClick={() => setMode(v)}>{label}</button>
        ))}
      </div>
      <div className="faint">{mode === "open" ? "The Create account tab shows on the sign-in screen." : "The sign-in screen hides Create account. Admins add people here."}</div>

      <h2 style={{ marginTop: 8 }}>Starting settings for new accounts</h2>
      <div className="cols" style={{ gap: 14 }}>
        {[["questions_per_close", "Questions per gate close", 1], ["hint_delay_seconds", "Hint unlocks after (seconds)", 0],
          ["daily_token_limit", "Warn after this many tokens a day", 0], ["account_token_cap", "Daily token cap (0 = none)", 0]].map(([key, label, min]) => (
          <div className="field" key={key} style={{ flex: "1 1 200px" }}>
            <label htmlFor={`d-${key}`}>{label}</label>
            <input id={`d-${key}`} type="number" min={min} value={d[key]} onChange={set(key)} />
          </div>
        ))}
      </div>
      <div className="faint">These apply to accounts created from now on. Existing accounts keep what they have.</div>
      <div><button className="btn primary" onClick={() => run(() => api("/admin/settings", { method: "PUT", body: { signup_mode: mode, new_account: d } }), "Saved.").then(reload)}>Save</button></div>
    </section>
  );
}

/* ── backups ── */
function Backups({ run, guard }) {
  const [items, setItems] = useState(null);
  const [keep, setKeep] = useState(14);
  const [restoring, setRestoring] = useState(null);
  const [typed, setTyped] = useState("");
  const load = useCallback(() => api("/admin/backups").then((r) => { setItems(r.backups); setKeep(r.keep_auto); }), []);
  useEffect(() => { load(); }, [load]);
  if (!items) return <div className="row muted"><Spinner /> Loading…</div>;
  const KIND = { auto: "Daily", manual: "Manual", "pre-delete": "Before delete", "pre-restore": "Before restore" };
  return (
    <section className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div><h2>Backups</h2><div className="faint" style={{ marginTop: 6 }}>A backup is made automatically each day (the last {keep} are kept), and before any account is deleted or a backup restored.</div></div>
        <button className="btn primary" onClick={() => run(() => api("/admin/backups", { method: "POST" }), "Backup saved.").then(load)}>Back up now</button>
      </div>
      {items.length === 0 && <div className="muted">No backups yet.</div>}
      <div className="studylist">
        {items.map((b) => (
          <div key={b.name} className="item">
            <div className="top">
              <span><strong style={{ fontWeight: 600 }}>{when(b.created)}</strong> <span className="badge">{KIND[b.kind] || b.kind}</span></span>
              <span className="row" style={{ gap: 8 }}>
                <span className="mono muted">{bytes(b.size)}</span>
                <button className="btn small" onClick={() => { setRestoring(restoring === b.name ? null : b.name); setTyped(""); }}>Restore…</button>
                <button className="btn small" onClick={() => run(() => api(`/admin/backups/${encodeURIComponent(b.name)}`, { method: "DELETE" }), "Backup deleted.").then(load)}>Delete</button>
              </span>
            </div>
            {restoring === b.name && (
              <form className="row danger-zone" onSubmit={(e) => { e.preventDefault(); run(() => api(`/admin/backups/${encodeURIComponent(b.name)}/restore`, { method: "POST", body: { confirm: typed } }),
                "Restored. A safety copy of the previous state was saved. Signing out in a moment…").then((ok) => ok && setTimeout(() => window.location.reload(), 1800)); }}>
                <span className="faint" style={{ flex: "1 1 100%" }}>Restoring replaces <strong>everything</strong> (all accounts, vaults and settings) with this backup. Anything newer is lost, though a safety copy is saved first.</span>
                <label htmlFor="rst">Type <strong>RESTORE</strong></label>
                <input id="rst" type="text" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} style={{ width: 160 }} />
                <button className="btn small danger" type="submit" disabled={typed !== "RESTORE"}>Restore this backup</button>
              </form>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── health ── */
function Health() {
  const [h, setH] = useState(null);
  const load = useCallback(() => api("/admin/health").then(setH), []);
  useEffect(() => { load(); }, [load]);
  if (!h) return <div className="row muted"><Spinner /> Loading…</div>;
  const up = h.uptime_seconds > 3600 ? `${Math.round(h.uptime_seconds / 360) / 10} h` : `${Math.max(1, Math.round(h.uptime_seconds / 60))} min`;
  const Row = ({ label, value, tone }) => <div className="hon"><span>{label}</span><span className="mono" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</span></div>;
  return (
    <div className="cols">
      <section className="panel wide">
        <h2>Connections</h2>
        <Row label="Claude Code" value={h.claude.connected ? "connected" : h.claude.checked ? "not connected" : "not checked yet"} tone={h.claude.connected ? "green" : h.claude.checked ? "red" : undefined} />
        <Row label="Stop hook" value={h.hook.installed ? "installed" : h.hook.stale ? "stale, needs repair" : "not installed (scanning transcripts)"} tone={h.hook.installed ? "green" : "amber"} />
        <Row label="Claude today (all accounts)" value={`${k(h.usage_today.tokens)} tokens · ${h.usage_today.calls} calls`} tone={h.usage_today.limit_message ? "red" : undefined} />
      </section>
      <section className="panel side">
        <h2>This install</h2>
        <Row label="Version" value={h.version} />
        <Row label="Running for" value={up} />
        <Row label="Database" value={`${bytes(h.database.size)} · schema ${h.schema}`} />
        <Row label="Accounts" value={`${h.accounts.total} (${h.accounts.admins} admin${h.accounts.admins === 1 ? "" : "s"}${h.accounts.disabled ? `, ${h.accounts.disabled} off` : ""})`} />
        <Row label="Backups" value={`${h.backups.count}${h.backups.latest ? ` · latest ${ago(h.backups.latest)}` : ""}`} tone={h.backups.count ? undefined : "amber"} />
      </section>
    </div>
  );
}

/* ── audit ── */
function Audit() {
  const [events, setEvents] = useState(null);
  const [filter, setFilter] = useState("");
  const load = useCallback(() => api(`/admin/audit?limit=200${filter ? `&event=${filter}` : ""}`).then((r) => setEvents(r.events)), [filter]);
  useEffect(() => { load(); }, [load]);
  return (
    <section className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>Activity log</h2>
        <div className="chips" role="group" aria-label="Filter">
          {[["", "Everything"], ["login", "Sign-ins"], ["account", "Accounts"], ["password", "Passwords"], ["backup", "Backups"], ["terminal", "Terminal"]].map(([v, label]) => (
            <button key={v} className={filter === v ? "on" : ""} aria-pressed={filter === v} onClick={() => setFilter(v)}>{label}</button>
          ))}
        </div>
      </div>
      {!events ? <div className="row muted"><Spinner /> Loading…</div> : events.length === 0 ? <div className="muted">Nothing logged.</div> : (
        <div className="audit" style={{ maxHeight: 520 }} aria-label="Activity log">
          {events.map((e, i) => (
            <div key={i}>
              <span className="mono muted">{when(e.at)}</span>
              <span>{EVENTS[e.event] || e.event}{e.username && <span className="muted"> · @{e.username}</span>}</span>
              <span className="faint">{e.detail}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const TABS = [["accounts", "Accounts"], ["access", "Access"], ["backups", "Backups"], ["health", "Health"], ["audit", "Activity"]];

const hashPart = (i) => decodeURIComponent(location.hash.slice(1).split("/")[i] || "");

export default function Admin({ user, go }) {
  const [tab, setTab] = useState(TABS.some(([key]) => key === hashPart(1)) ? hashPart(1) : "accounts");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [flash, setFlash] = useState(null);
  const [guard, modal] = useReauth();

  const reload = useCallback(() => api("/admin/overview").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { reload(); }, [reload]);

  /** Runs an admin action: re-asks for the password if needed, then shows the result and refreshes. */
  const run = useCallback(async (fn, okText, extra) => {
    setFlash(null);
    try {
      const r = await guard(fn);
      setFlash({ text: okText, ...(extra ? extra(r) : {}) });
      reload();
      return r;
    } catch (e) {
      if (e.kind !== "cancel") setFlash({ text: e.message, bad: true });
      return null;
    }
  }, [guard, reload]);

  if (error) return <main><div className="note red" role="alert"><Info /><div>{error}</div></div></main>;
  if (!data) return <main><div className="row muted"><Spinner /> Loading…</div></main>;

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Admin</div>
          <h1>{data.users.length} account{data.users.length === 1 ? "" : "s"}.</h1>
          <p className="sub">People, access and backups for this ADDGate. Only admins see this tab.</p>
        </div>
      </section>

      <div className="subnav" role="tablist" aria-label="Admin sections">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => { setTab(key); setFlash(null); history.replaceState(null, "", `#admin/${key}`); }}>{label}</button>
        ))}
      </div>

      <Flash flash={flash} onClose={() => setFlash(null)} />

      {tab === "accounts" && <Accounts data={data} reload={reload} run={run} guard={guard} me={data.me} />}
      {tab === "access" && <Access data={data} reload={reload} run={run} />}
      {tab === "backups" && <Backups run={run} guard={guard} />}
      {tab === "health" && <Health />}
      {tab === "audit" && <Audit />}
      {modal}
    </main>
  );
}
