import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end: the real backend and the production frontend build, driven by a
 * real browser. Both servers are started here, so `npm run test:e2e` is the
 * whole setup.
 *
 * The backend runs hermetically: a throwaway SQLite database, AI_ANALYSIS_PAUSED
 * (the placeholder critique — no Anthropic call, no key needed), and no
 * ANTHROPIC_API_KEY, so subject localization uses whatever local tier the
 * installed lock provides. CI installs the lite lock: no torch, saliency tier.
 */

const here = dirname(fileURLToPath(import.meta.url));
const backendDir = resolve(here, "../backend");
const venvPython =
  process.platform === "win32"
    ? join(backendDir, ".venv/Scripts/python.exe")
    : join(backendDir, ".venv/bin/python");
const python = process.env.E2E_PYTHON ?? (existsSync(venvPython) ? venvPython : "python");
const dbDir = mkdtempSync(join(tmpdir(), "framegrader-e2e-"));

const API_PORT = 8787;
const WEB_PORT = 4173;

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 120_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    acceptDownloads: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: backendDir,
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${join(dbDir, "e2e.db").replace(/\\/g, "/")}`,
        AI_ANALYSIS_PAUSED: "true",
        ANTHROPIC_API_KEY: "",
        ALLOWED_ORIGINS: `http://localhost:${WEB_PORT}`,
        // The suite submits a handful of photos; don't let the paid-endpoint
        // limiter (10/hour) be the thing under test.
        AI_RATE_LIMIT: "1000/hour",
        LOG_FORMAT: "text",
      },
    },
    {
      // The production bundle, not the dev server: what ships is what's tested.
      command: `npm run build && npx vite preview --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { VITE_API_PROXY: `http://localhost:${API_PORT}` },
    },
  ],
});
