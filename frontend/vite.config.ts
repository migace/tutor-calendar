import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin in development, so the browser never needs CORS for the API.
    // 127.0.0.1 rather than localhost: uvicorn listens on IPv4 only, and Node
    // resolving "localhost" to ::1 first makes the proxy fail intermittently.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
