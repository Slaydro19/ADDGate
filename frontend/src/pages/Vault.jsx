import React, { useEffect, useState } from "react";
import { api, fmtDate } from "../api.js";
import { Spinner } from "../icons.jsx";
import { flagText } from "../components/QuizCard.jsx";

const CONF = { sure: "sure", fairly: "fairly sure", guessing: "guessing" };

const FILTERS = ["all", "owned", "partial", "borrowed", "relearn"];

export default function Vault() {
  const [items, setItems] = useState(null);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);

  useEffect(() => { api("/vault").then((r) => setItems(r.concepts)); }, []);
  if (!items) return <main><div className="row muted"><Spinner /> Loading…</div></main>;

  const counts = Object.fromEntries(FILTERS.map((f) => [f, f === "all" ? items.length : items.filter((c) => c.status === f).length]));
  const shown = filter === "all" ? items : items.filter((c) => c.status === filter);

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Vault</div>
          <h1>{counts.owned} of {items.length} concepts owned.</h1>
          <p className="sub">Everything you've been quizzed on, and when it comes back.</p>
        </div>
      </section>
      <div className="filters" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button key={f} className={filter === f ? "on" : ""} aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {f[0].toUpperCase() + f.slice(1)} · {counts[f]}</button>
        ))}
      </div>
      {shown.length === 0 && <div className="panel"><div className="empty">Nothing here yet.</div></div>}
      <div className="grid">
        {shown.map((c) => (
          <div key={c.id} className="panel" style={{ gap: 10 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 16 }}>{c.name}</div>
                <div className="mono muted">{c.category}</div>
              </div>
              <span className="row" style={{ gap: 6 }}>
                {c.held === false && <span className="heldtag no" title="Owned the first time, missed when asked again">didn't hold</span>}
                {c.held === true && <span className="heldtag yes" title="Owned the first time and still owned later">held</span>}
                <span className={`status s-${c.status}`}>{c.status}</span>
              </span>
            </div>
            {c.why && <div className="muted" style={{ fontSize: 14 }}>{c.why}</div>}
            <div className="row mono muted" style={{ justifyContent: "space-between" }}>
              <span>since {fmtDate(c.created)}</span>
              <span>{c.next_due ? `next ${fmtDate(c.next_due)}` : "not scheduled"}</span>
            </div>
            {c.history?.length > 0 && (
              <button className="btn small" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                {open === c.id ? "Hide" : "Show"} {c.history.length} attempt{c.history.length > 1 ? "s" : ""}</button>
            )}
            {open === c.id && c.history.slice().reverse().map((h, i) => (
              <div key={i} className="item" style={{ fontSize: 14 }}>
                <div className="top"><span className="mono muted">{fmtDate(h.date.slice(0, 10))} · {h.source}
                  {h.choice_correct != null && ` · picked ${h.choice_correct ? "right" : "wrong"}`}
                  {h.confidence && ` · ${CONF[h.confidence]}`}</span>
                  <span className={`status s-${h.verdict}`}>{h.verdict}</span></div>
                <div>{h.question}</div>
                <div className="muted">{h.answer || "(no answer)"}</div>
                {h.flags?.length > 0 && <div className="flagchips">{h.flags.map((f, j) => <span key={j} className="flagchip">{flagText(f)}</span>)}</div>}
              </div>
            ))}
          </div>
        ))}
      </div>
    </main>
  );
}
