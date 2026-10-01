import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, Vite proxies API calls to uvicorn so the browser sees one origin (same as nginx in Docker).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
