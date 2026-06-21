// @ts-check
const { defineConfig } = require("@playwright/test");

function positiveTimeout(name, defaultValue) {
  const rawValue = process.env[name] || String(defaultValue);
  const value = Number(rawValue);

  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a positive number`);
  }
  return value;
}

const timeout = positiveTimeout("API_TIMEOUT_MS", 30_000);

module.exports = defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout,
  expect: {
    timeout: 10_000,
  },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "api",
      testMatch: /.*\.spec\.js/,
    },
  ],
});
