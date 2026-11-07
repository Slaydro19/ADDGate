import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { Check, Info, Spinner } from "../icons.jsx";

export default function Settings() {
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
        <p className="sub">Saved to ~/gate/config.json.</p></div></section>

      <section className="panel">
        <h2>Claude Code Stop hook</h2>
        {hook?.installed ? (
          <div className="row" style={{ color: "var(--green-text)" }}><Check /> Installed in {hook.settings_path}</div>
        ) : (
          <>
            <p style={{ margin: 0 }} className="muted">Lets ADDGate know the moment Claude finishes a reply. It adds one entry to
              your Claude Code settings and backs up the file first. Without it, ADDGate scans today's transcripts instead.</p>
            <div><button className="btn" onClick={installHook}>Install Stop hook</button></div>
          </>
        )}
      </section>

      <section className="panel">
        <h2>Git repos to watch</h2>
        <div className="field">
          <label htmlFor="repos">One absolute path per line</label>
          <textarea id="repos" value={repos} onChange={(e) => { setSaved(false); setRepos(e.target.value); }}
            placeholder={"/Users/you/code/homelab\n/Users/you/code/ADDGate"} />
        </div>
      </section>

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
            <label htmlFor="budget">Daily token budget for the meter</label>
            <input id="budget" type="number" min="0" step="10000" value={cfg.daily_token_budget} onChange={set("daily_token_budget")} />
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
        {saved && <span className="row" style={{ color: "var(--green-text)", gap: 6 }}><Check /> Saved</span>}
      </div>
    </main>
  );
}
