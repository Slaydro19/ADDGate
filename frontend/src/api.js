export async function api(path, { method = "GET", body } = {}) {
  const send = method !== "GET";
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    // The server only accepts JSON for writes (blocks cross-site form posts), so always send JSON.
    headers: send ? { "Content-Type": "application/json" } : undefined,
    body: send ? JSON.stringify(body || {}) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    if (res.status === 401 && data?.kind === "login") {
      window.dispatchEvent(new Event("addgate:signed-out"));
    }
    if (data?.kind === "auth" || data?.kind === "missing") {  // Claude Code sign-in expired or gone
      window.dispatchEvent(new Event("addgate:claude-lost"));
    }
    const err = new Error((data && data.error) || `Request failed (${res.status})`);
    err.kind = data && data.kind;
    throw err;
  }
  return data;
}

export const fmtTime = (iso) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";

export const fmtDate = (iso) =>
  iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString([], { month: "short", day: "numeric" }) : "";
