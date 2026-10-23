import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

// Unit tests only: pure functions, no DOM. The browser flow is covered by the
// Playwright suite in e2e/, which vitest must not pick up.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
    setupFiles: ["src/test/setup.ts"],
  },
});
