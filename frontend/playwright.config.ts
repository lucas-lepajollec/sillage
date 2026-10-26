import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    actionTimeout: 10_000,
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:5776",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "cd .. && uv run python tests/serve_e2e.py",
        url: "http://127.0.0.1:5776/api/health",
        reuseExistingServer: false,
        timeout: 30_000,
      },
});
