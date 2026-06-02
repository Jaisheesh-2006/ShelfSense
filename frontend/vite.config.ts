import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server binds all interfaces (so it works inside a container / over LAN). The production
// bundle is built to dist/ and served by nginx (see Dockerfile).
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 },
  build: { outDir: "dist", sourcemap: false },
});
