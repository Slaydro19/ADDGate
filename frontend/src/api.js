export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
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
