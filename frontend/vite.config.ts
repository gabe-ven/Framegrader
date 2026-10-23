import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to the FastAPI backend during development (and in
      // `vite preview`, which inherits this). The E2E suite points it at its
      // own backend port via VITE_API_PROXY.
      "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000",
    },
  },
});
