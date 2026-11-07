import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` on :5173 proxies /api to Flask on :5055.
// Build: outputs into backend/static so Flask serves everything on one port.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:5055" } },
  build: { outDir: "../backend/static", emptyOutDir: true },
});
