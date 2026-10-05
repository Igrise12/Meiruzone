import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "compose.ts",
  workers: 1,
  timeout: 120_000,
  reporter: "line",
  use: { browserName: "chromium", baseURL: "http://127.0.0.1:5173" },
});
