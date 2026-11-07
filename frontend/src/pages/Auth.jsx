import React, { useState } from "react";
import { api } from "../api.js";
import { Info, Logo, Spinner } from "../icons.jsx";

export default function Auth({ hasUsers, onSignedIn }) {
  const [mode, setMode] = useState(hasUsers ? "login" : "signup");
  const [form, setForm] = useState({ username: "", password: "", confirm: "", display_name: "", remember: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const signup = mode === "signup";
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (signup && form.password !== form.confirm) { setError("Passwords don't match."); return; }
    setBusy(true);
    try {
      const { user } = await api(signup ? "/auth/signup" : "/auth/login", { method: "POST", body: form });
      onSignedIn(user);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const switchMode = (m) => { setMode(m); setError(null); };

  return (
    <div className="center">
      <form className="card" onSubmit={submit} noValidate>
        <div className="brand"><Logo /> ADDGate</div>
        <div>
          <h1 style={{ fontSize: 26 }}>{signup ? "Create your account" : "Welcome back"}</h1>
          <p className="sub">{signup
            ? (hasUsers ? "Your quizzes, vault and review schedule stay separate from other accounts on this Mac."
              : "First account on this Mac. Any ADDGate data you already have moves into it.")
            : "Sign in to pick up your gate and reviews."}</p>
        </div>

        <div className="tabs" role="tablist" aria-label="Account">
          <button type="button" role="tab" aria-selected={!signup} className={!signup ? "on" : ""} onClick={() => switchMode("login")}>Sign in</button>
          <button type="button" role="tab" aria-selected={signup} className={signup ? "on" : ""} onClick={() => switchMode("signup")}>Create account</button>
        </div>

        {signup && (
          <div className="field">
            <label htmlFor="dn">Name <span className="faint">(optional)</span></label>
            <input id="dn" type="text" autoComplete="name" value={form.display_name} onChange={set("display_name")} placeholder="e.g. Jalen" />
          </div>
        )}
        <div className="field">
          <label htmlFor="un">Username</label>
          <input id="un" type="text" autoComplete="username" autoCapitalize="none" spellCheck="false" required autoFocus
            value={form.username} onChange={set("username")} />
          {signup && <span className="faint">3–32 letters, numbers, dot, dash or underscore</span>}
        </div>
        <div className="field">
          <label htmlFor="pw">Password</label>
          <input id="pw" type="password" autoComplete={signup ? "new-password" : "current-password"} required
            value={form.password} onChange={set("password")} />
          {signup && <span className="faint">At least 8 characters</span>}
        </div>
        {signup && (
          <div className="field">
            <label htmlFor="pw2">Confirm password</label>
            <input id="pw2" type="password" autoComplete="new-password" required value={form.confirm} onChange={set("confirm")} />
          </div>
        )}
        {!signup && (
          <label className="check"><input type="checkbox" checked={form.remember} onChange={set("remember")} /> Keep me signed in for 30 days</label>
        )}

        {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}

        <button className="btn primary" type="submit" disabled={busy || !form.username || !form.password}>
          {busy ? <><Spinner /> {signup ? "Creating…" : "Signing in…"}</> : signup ? "Create account" : "Sign in"}
        </button>
        <p className="faint" style={{ margin: 0, textAlign: "center" }}>
          Accounts live only on this Mac, in ~/gate. Forgot your password? Ask whoever runs ADDGate here to reset it.
        </p>
      </form>
    </div>
  );
}
