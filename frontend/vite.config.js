import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { execSync } from "node:child_process";

const branch = (() => {
  try { return execSync("git rev-parse --abbrev-ref HEAD").toString().trim(); }
  catch { return ""; }
})();

// Dev: `npm run dev` on :5173 proxies /api and the terminal WebSocket to Flask on :5055.
// Build: outputs into backend/static so Flask serves everything on one port.
export default defineConfig({
  plugins: [react()],
  define: { __GIT_BRANCH__: JSON.stringify(branch) },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5055",
      "/ws": { target: "ws://127.0.0.1:5055", ws: true },
    },
  },
  build: { outDir: "../backend/static", emptyOutDir: true },
});
