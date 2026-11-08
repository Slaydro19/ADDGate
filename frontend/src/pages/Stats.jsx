import React, { useEffect, useState } from "react";
import { api, fmtDate, fmtTime } from "../api.js";
import { Spinner } from "../icons.jsx";

// Blue and amber on the stone surface: distinct for colour-blind viewers, 3:1 or better.
const OWNED = "#2456d6";
const NOT_OWNED = "#a85f00";

function Tile({ label, value, sub }) {
  return (
    <div className="panel tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {sub && <span className="faint">{sub}</span>}
    </div>
  );
}

function niceMax(n) {
  if (n <= 4) return Math.max(n, 1);
  const step = n <= 10 ? 2 : n <= 25 ? 5 : 10;
  return Math.ceil(n / step) * step;
}

function DailyChart({ daily }) {
  const [hover, setHover] = useState(null);
  const [table, setTable] = useState(false);
  const max = niceMax(Math.max(...daily.map((d) => d.owned + d.not_owned), 0));
  const ticks = [0, max / 2, max].map((t) => Math.round(t));
  const total = daily.reduce((s, d) => s + d.owned + d.not_owned, 0);

  return (
    <section className="panel wide" aria-labelledby="dailyh">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 id="dailyh">Answers per day</h2>
          <div className="faint">Last 30 days · {total} answers</div>
        </div>
        <div className="row" style={{ gap: 16 }}>
          <span className="legend"><i style={{ background: OWNED }} />Owned</span>
          <span className="legend"><i style={{ background: NOT_OWNED }} />Borrowed or partial</span>
          <button className="btn small" onClick={() => setTable(!table)} aria-pressed={table}>{table ? "Chart" : "Table"}</button>
        </div>
      </div>

      {table ? (
        <div style={{ overflowX: "auto", maxHeight: 280 }}>
          <table className="dtable">
            <thead><tr><th>Day</th><th>Owned</th><th>Borrowed or partial</th></tr></thead>
            <tbody>{daily.filter((d) => d.owned + d.not_owned).reverse().map((d) => (
              <tr key={d.day}><td>{fmtDate(d.day)}</td><td>{d.owned}</td><td>{d.not_owned}</td></tr>
            ))}</tbody>
          </table>
        </div>
      ) : (
        <div className="chart" onMouseLeave={() => setHover(null)}>
          <div className="yaxis" aria-hidden="true">{ticks.slice().reverse().map((t) => <span key={t}>{t}</span>)}</div>
          <div className="plot" role="img" aria-label={`Answers per day for the last 30 days, ${total} total. Use the Table button for exact values.`}>
            {ticks.map((t) => <div key={t} className="grid" style={{ bottom: `${(t / max) * 100}%` }} />)}
            <div className="dbars">
              {daily.map((d, i) => {
                const n = d.owned + d.not_owned;
                return (
                  <div key={d.day} className={`dcol ${hover === i ? "on" : ""}`} onMouseEnter={() => setHover(i)}>
                    <div className="stack" style={{ height: `${(n / max) * 100}%` }}>
                      {d.not_owned > 0 && <div className="seg" style={{ flex: d.not_owned, background: NOT_OWNED }} />}
                      {d.owned > 0 && <div className="seg" style={{ flex: d.owned, background: OWNED }} />}
                    </div>
                    {hover === i && (
                      <div className={`tip ${i > daily.length * 0.7 ? "left" : ""}`}>
                        <strong>{fmtDate(d.day)}</strong>
                        <span><i style={{ background: OWNED }} />Owned {d.owned}</span>
                        <span><i style={{ background: NOT_OWNED }} />Borrowed or partial {d.not_owned}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="xaxis" aria-hidden="true">
            <span>{fmtDate(daily[0].day)}</span><span>{fmtDate(daily[15].day)}</span><span>Today</span>
          </div>
        </div>
      )}
    </section>
  );
}

function Categories({ categories }) {
  if (!categories.length) return null;
  return (
    <section className="panel side" style={{ flexBasis: 380 }} aria-labelledby="cath">
      <div><h2 id="cath">Where you borrow most</h2><div className="faint">Share of answers not owned, by category</div></div>
      <div className="hbars">
        {categories.map((c) => {
          const rate = c.attempts ? Math.round((100 * c.misses) / c.attempts) : 0;
          return (
            <div key={c.category} className="hbar" title={`${c.misses} of ${c.attempts} answers not owned · ${c.owned} of ${c.concepts} concepts owned`}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span>{c.category}</span><span className="mono">{rate}%</span>
              </div>
              <div className="track"><div className="fill" style={{ width: `${rate}%`, background: NOT_OWNED }} /></div>
              <span className="faint">{c.misses} of {c.attempts} answers · {c.owned}/{c.concepts} concepts owned</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Today({ sessions }) {
  return (
    <section className="panel" aria-labelledby="todayh">
      <div><h2 id="todayh">Today</h2></div>
      {sessions.length === 0 ? <div className="muted">Nothing captured yet today.</div> : (
        <div className="timeline">
          {sessions.map((s) => (
            <div key={s.id} className="tl-row">
              <span className="time">{fmtTime(s.start)}</span>
              <span className={`pip ${s.kind === "shell" ? "typed" : ""} ${s.after_open ? "" : "old"}`} aria-hidden="true" />
              <span><strong style={{ fontWeight: 600 }}>{s.title}</strong>{s.project && <span className="muted"> · {s.project}</span>}
                {!s.after_open && <span className="muted"> · already quizzed</span>}</span>
              <span className="meta">{s.minutes} min · {s.kind === "shell"
                ? `${s.commands} command${s.commands === 1 ? "" : "s"}${s.failed ? `, ${s.failed} failed` : ""}`
                : `${s.files.length} file${s.files.length === 1 ? "" : "s"}`}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Stats({ user }) {
  const [s, setS] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [error, setError] = useState(null);
  useEffect(() => {
    api("/stats").then(setS).catch((e) => setError(e.message));
    api("/capture").then((c) => setSessions(c.sessions || [])).catch(() => {});
  }, []);

  if (error) return <main><div className="note red" role="alert">{error}</div></main>;
  if (!s) return <main><div className="row muted"><Spinner /> Loading…</div></main>;
  const t = s.totals;
  const weekMax = Math.max(...s.upcoming.map((d) => d.due), 1);

  if (!t.concepts) {
    return (
      <main>
        <Today sessions={sessions} />
        <div className="panel"><div className="empty">
          <strong>No stats yet.</strong>
          <span>Close your first gate and answer a few questions. Your numbers show up here.</span>
        </div></div>
      </main>
    );
  }

  return (
    <main>
      <section className="hero">
        <div>
          <div className="eyebrow">Stats · {user.display_name}</div>
          <h1>{t.ownership_pct}% of what you've built, you own.</h1>
          <p className="sub">{t.owned} of {t.concepts} concepts owned{t.relearn ? ` · ${t.relearn} in relearn` : ""}.</p>
        </div>
      </section>

      <Today sessions={sessions} />

      <div className="tiles">
        <Tile label="Held up" value={s.retention.pct == null ? "–" : `${s.retention.pct}%`}
          sub={s.retention.checked ? `${s.retention.held} of ${s.retention.checked} first-try concepts still owned later` : "shows once a concept you owned comes back in review"} />
        <Tile label="Streak" value={`${t.streak} day${t.streak === 1 ? "" : "s"}`} sub="days in a row with a gate or review" />
        <Tile label="Answers owned" value={t.attempts ? `${Math.round((100 * t.attempts_owned) / t.attempts)}%` : "–"} sub={`${t.attempts_owned} of ${t.attempts} answers`} />
        <Tile label="Due today" value={t.due_today} sub={t.due_today ? <a href="#study">Study now</a> : "all caught up"} />
      </div>

      <div className="cols">
        <DailyChart daily={s.daily} />
        <Categories categories={s.categories} />
      </div>

      <div className="cols">
        <section className="panel wide" aria-labelledby="honh">
          <div><h2 id="honh">Honest record</h2><div className="faint">Just for you. Nothing here is a penalty.</div></div>
          <div className="hon"><span>Looked it up</span><span className="mono">{s.honesty.looked_up}</span></div>
          <div className="hon"><span>Pasted an explanation</span><span className="mono">{s.honesty.pasted}</span></div>
          <div className="hon"><span>Left the tab mid-question</span><span className="mono">{s.honesty.left_tab}</span></div>
          <div className="hon"><span>Said "sure" but missed</span><span className="mono">{s.honesty.sure_but_wrong}</span></div>
          <div className="faint">Saying "I looked it up" is the honest move: it costs nothing and the concept comes back tomorrow.</div>
        </section>
      </div>

      <div className="cols">
        <section className="panel wide" aria-labelledby="hardh">
          <h2 id="hardh">Hardest concepts</h2>
          {s.hardest.length === 0 && <div className="muted">Nothing missed yet.</div>}
          {s.hardest.map((h) => (
            <div key={h.name} className="item">
              <div className="top">
                <span style={{ fontWeight: 500 }}>{h.name}</span>
                <span className={`status s-${h.status}`}>{h.status}</span>
              </div>
              <span className="faint"><span className="mono">{h.category}</span> · missed {h.misses} of {h.attempts}</span>
            </div>
          ))}
        </section>

        <section className="panel side" aria-labelledby="weekh">
          <div><h2 id="weekh">Reviews coming up</h2><div className="faint">Concepts due each day this week</div></div>
          <div className="week" role="img" aria-label={s.upcoming.map((d) => `${fmtDate(d.day)}: ${d.due}`).join(", ")}>
            {s.upcoming.map((d, i) => (
              <div key={d.day} className="wcol">
                <span className="mono wval">{d.due || ""}</span>
                <div className="wbar" style={{ height: `${(d.due / weekMax) * 100}%`, background: OWNED }} />
                <span className="faint">{i === 0 ? "Today" : new Date(d.day + "T12:00").toLocaleDateString([], { weekday: "short" })}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
