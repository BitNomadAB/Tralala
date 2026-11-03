import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");

const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8077);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 5273);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

const venvCandidates = [
  path.join(repoRoot, ".venv", "Scripts", "python.exe"), // Windows layout
  path.join(repoRoot, ".venv", "bin", "python"), // macOS / Linux layout
];
// A bare `python3` works only when the virtual environment is active, so prefer the repository's
// own interpreter whenever it exists.
const python =
  process.env.E2E_PYTHON ??
  venvCandidates.find((candidate) => existsSync(candidate)) ??
  (process.platform === "win32" ? "python" : "python3");

const dataDir = path.join(here, "e2e", ".data");
const adminPassword = process.env.E2E_ADMIN_PASSWORD ?? "e2e-password";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: FRONTEND_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      // The app imports rows generated from the migrations; dbgen is cached, so an unchanged schema
      // costs well under a second.
      command: `"${python}" -m tools.dbgen && "${python}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: path.join(repoRoot, "backend"),
      url: `${BACKEND_URL}/api/v1/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        TRALALA_DATA_DIR: dataDir,
        TRALALA_SECRET_KEY: "e2e-secret-key-not-for-production",
        TRALALA_BOOTSTRAP_USERNAME: "admin",
        TRALALA_BOOTSTRAP_PASSWORD: adminPassword,
        TRALALA_COOKIE_SECURE: "false",
        TRALALA_RATE_LIMIT_PER_MINUTE: "100000",
        TRALALA_CORS_ORIGINS: FRONTEND_URL,
      },
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${FRONTEND_PORT} --strictPort`,
      cwd: here,
      url: FRONTEND_URL,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        VITE_API_PROXY: BACKEND_URL,
      },
    },
  ],
});
