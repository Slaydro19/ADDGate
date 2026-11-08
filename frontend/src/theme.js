// Theme: "light" | "dark" | "system" (default). Stored per browser; the page follows the Mac when set to system.
const KEY = "addgate-theme";
const mq = window.matchMedia("(prefers-color-scheme: dark)");
const read = () => { try { return localStorage.getItem(KEY) || "system"; } catch { return "system"; } };
const apply = (pref) => {
  const dark = pref === "dark" || (pref === "system" && mq.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0a0a0b" : "#dfdedb");
};
export const getTheme = read;
export function setTheme(pref) {
  try { localStorage.setItem(KEY, pref); } catch { /* private window: lasts until reload */ }
  apply(pref);
  window.dispatchEvent(new Event("addgate:theme"));
}
export function initTheme() {
  apply(read());
  mq.addEventListener("change", () => read() === "system" && apply("system"));
}
