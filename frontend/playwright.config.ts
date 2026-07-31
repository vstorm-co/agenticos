import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E test configuration.
 *
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: "./e2e",
  /* Run tests in files in parallel */
  // Off, and one worker, because every spec shares one database and most of
  // them write to it. In parallel the sign-out spec ends the session another
  // spec is using and the sharing specs contend for the same rows: locally
  // that showed up as 8 failures that all passed in isolation, which is the
  // kind of red people learn to re-run instead of read. Serialised, the whole
  // suite is under two minutes.
  fullyParallel: false,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  // No retries. A suite whose entire purpose is to be able to fail must not
  // have a setting that turns a real failure green on the second attempt.
  retries: 0,
  /* Opt out of parallel tests on CI. */
  workers: 1,
  expect: {
    /*
     * Raised from Playwright's 5s default, for one reason: locally the suite
     * runs against `bun run dev`, which compiles a route the first time
     * something navigates to it. The first visit to `/agents/[id]` or
     * `/dashboard` can take several seconds of pure compilation, and the
     * assertion that pays for it is whichever one follows the click.
     *
     * That produced eight failures whose messages all described something else
     * — "expected /dashboard, received /login" reads exactly like rejected
     * credentials, and the login request had in fact returned 200. A timeout
     * short enough to expire on a compile is a timeout that lies about what
     * broke.
     *
     * It costs nothing in CI, which runs `bun run start` against a build where
     * nothing compiles on demand, and a genuinely broken assertion still fails
     * — fifteen seconds later.
     */
    timeout: 15_000,
  },
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [["list"], ["html", { outputFolder: "playwright-report" }]],
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: "on-first-retry",

    /* Capture screenshot on failure */
    screenshot: "only-on-failure",

    /* Video recording on failure */
    video: "on-first-retry",
  },

  /* Configure projects for major browsers */
  projects: [
    /* Sign in once. Everything else reuses the session this writes. */
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },

    /*
     * Create the rows bootstrap does not, so the specs have something real to
     * assert on. Its own project rather than another file in `setup`: it needs
     * the session, and files inside one project have no ordering between them.
     */
    {
      name: "seed",
      testMatch: /seed\.setup\.ts/,
      dependencies: ["setup"],
    },

    /*
     * One browser, on purpose.
     *
     * These specs share one database: they publish agents, store keys, share
     * rows and revoke them. Five browser projects against a single backend is
     * five copies of every write racing each other, and a spec that fails
     * because Safari revoked the grant Chrome had just asserted teaches nobody
     * anything. Cross-browser rendering is a job for the component tests, which
     * cost nothing to run in a second engine because they mutate nothing.
     */
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
      dependencies: ["seed"],
    },
  ],

  /*
   * The frontend under test, started by Playwright.
   *
   * This used to be switched off under CI, which meant the CI job ran the whole
   * suite against a closed port 3000. Every spec failed for the same reason and
   * none of them for a reason worth knowing. It runs in CI now; what changes
   * there is only *which* server: `next start` against the build the job just
   * produced, rather than a dev server that compiles each route on first hit.
   *
   * `reuseExistingServer` stays off in CI so a stale process can never be
   * mistaken for the build under test, and on locally so a running `bun run dev`
   * is reused instead of fighting over the port.
   */
  webServer: {
    // `bun run start` is `next start`, and Next refuses to serve an
    // `output: "standalone"` build that way - it prints
    // `"next start" does not work with "output: standalone" configuration`
    // and serves an app whose data layer is broken. Twenty-one specs failed on
    // that in CI while the same suite passed locally against the dev server, so
    // the difference looked like flakiness rather than the server being wrong.
    //
    // `start:standalone` runs `.next/standalone/server.js` after copying
    // `public/` and `.next/static` beside it, which is exactly what
    // `frontend/Dockerfile` does. CI now exercises the server that ships.
    command: process.env.CI ? "bun run start:standalone" : "bun run dev",
    // Deliberately the app's own door and not `/api/health`: that endpoint
    // proxies to the backend, so a broken data layer would look like a frontend
    // that never started, and Playwright would report nothing at all instead of
    // the specs that failed.
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
