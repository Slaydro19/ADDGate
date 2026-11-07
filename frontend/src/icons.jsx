import React from "react";

const base = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const Logo = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" {...base} stroke="var(--accent)">
    <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M12 4v16M8 12h1M15 12h1" />
  </svg>
);
export const Lock = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...base}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
);
export const Unlock = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...base}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 7.5-2" /></svg>
);
export const Info = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" {...base} style={{ flex: "none", marginTop: 1 }}><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></svg>
);
export const Check = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...base}><path d="m5 12 5 5 9-10" /></svg>
);
export const Spinner = () => <span className="spinner" aria-hidden="true" />;
