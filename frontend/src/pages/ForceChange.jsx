import React, { useState } from "react";
import { api } from "../api.js";
import { Info, Logo, Spinner } from "../icons.jsx";

/** Shown after signing in with a temporary password an admin issued: choose your own before anything else. */
export default function ForceChange({ user, onDone, onSignOut }) {
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => { setError(null); setF({ ...f, [k]: e.target.value }); };
  async function submit(e) {
    e.preventDefault();
    if (f.next !== f.confirm) { setError("The new passwords don't match."); return; }
    setBusy(true);
    try { const r = await api("/auth/password", { method: "POST", body: { current: f.current, new: f.next } }); onDone(r.user); }
    catch (err) { setError(err.message); setBusy(false); }
  }
  return (
    <div className="center">
      <form className="card" onSubmit={submit}>
        <div className="brand"><Logo size={32} /> <span><b>ADD</b><span className="light">Gate</span></span></div>
        <div>
          <h1>Choose your password</h1>
          <p className="sub">Hi {user.display_name}. An admin gave you a temporary password. Pick one only you know to continue.</p>
        </div>
        <div className="field"><label htmlFor="fc-c">Temporary password</label>
          <input id="fc-c" type="password" autoComplete="current-password" autoFocus value={f.current} onChange={set("current")} /></div>
        <div className="field"><label htmlFor="fc-n">New password</label>
          <input id="fc-n" type="password" autoComplete="new-password" value={f.next} onChange={set("next")} />
          <span className="faint">At least 8 characters</span></div>
        <div className="field"><label htmlFor="fc-n2">Confirm new password</label>
          <input id="fc-n2" type="password" autoComplete="new-password" value={f.confirm} onChange={set("confirm")} /></div>
        {error && <div className="note red" role="alert"><Info /><div>{error}</div></div>}
        <button className="btn primary" type="submit" disabled={busy || !f.current || !f.next}>{busy ? <><Spinner /> Saving…</> : "Save and continue"}</button>
        <button className="btn" type="button" onClick={onSignOut}>Sign out</button>
      </form>
    </div>
  );
}
