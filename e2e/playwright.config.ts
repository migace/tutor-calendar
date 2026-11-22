import { defineConfig, devices } from "@playwright/test";

import type { JourneyOptions } from "./tests/journey";

/**
 * Runs against the application as it is deployed: the built image, its worker
 * and PostgreSQL, started with `docker compose up --build` from the repository
 * root. Nothing here starts a server, and nothing is mocked.
 */
export default defineConfig<JourneyOptions>({
  testDir: "./tests",
  // One journey at a time. Both book from the same calendar, and two at once
  // would race for the same free time.
  workers: 1,
  fullyParallel: false,
  // No second chances: a journey that passes only when repeated is a failure.
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
    mailpitURL: process.env.E2E_MAILPIT_URL ?? "http://localhost:8025",
    // The booking page shows times on the visitor's clock and the panel on the
    // tutor's. On the same clock, a time read off one page can be looked for
    // on the other, and the machine's own zone stops mattering.
    timezoneId: "Europe/Warsaw",
    // A button that is not there fails the step in seconds, not at the end of the test.
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: "retain-on-failure",
  },
  // Each language is picked in the page, in a browser that asks for the other
  // one. A journey that only passed in the browser's language would fail here.
  projects: [
    {
      name: "desktop-en",
      use: { ...devices["Desktop Chrome"], locale: "pl-PL", language: "en" },
    },
    {
      name: "phone-pl",
      use: { ...devices["Pixel 7"], locale: "en-GB", language: "pl" },
    },
  ],
});
