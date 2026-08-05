import { defineConfig, devices } from "@playwright/test";

/**
 * The two ports the suite occupies, each derived from the environment so the
 * suite can run beside another checkout that already holds the defaults.
 *
 * Derived rather than `setdefault`: `Number(process.env.X ?? default)` reads
 * whatever is set and falls back only when nothing is — so `E2E_PORT=3100`
 * moves the whole suite while an unset environment (CI, and `make test-e2e`
 * with nothing exported) stays on the historical 3000/4010. A default that
 * ignored an already-set value would leave CI on the fixed port with the new
 * code never exercised there, which is the trap #189 named for the test
 * database name.
 *
 * `E2E_STUB_MODEL_PORT` is read here *and* in `journey.spec.ts` and
 * `delegation.spec.ts`, both with the same `?? 4010` default: the specs dial
 * the stub through a model profile whose Endpoint is
 * `http://127.0.0.1:${E2E_STUB_MODEL_PORT}/v1`, so the number the backend
 * learns and the number the stub binds have to be the one value. Passing it
 * into the stub's `webServer.env` below is what forbids them to disagree even
 * if the config later chose the port itself.
 *
 * The stub binds loopback (`127.0.0.1`), and the backend reaches it by that
 * address — so the backend has to share the host's loopback. That is the
 * host-uvicorn path CI runs and `journey.spec.ts` needs; a backend in a
 * container cannot reach `127.0.0.1:${E2E_STUB_MODEL_PORT}` and this file does
 * not pretend otherwise. Moving the port does not change that.
 */
const FRONTEND_PORT = Number(process.env.E2E_PORT ?? 3000);
const STUB_MODEL_PORT = Number(process.env.E2E_STUB_MODEL_PORT ?? 4010);
const BASE_URL = `http://localhost:${FRONTEND_PORT}`;

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
  /*
   * Reporter to use. See https://playwright.dev/docs/test-reporters
   *
   * `fixture-reporter` is last so its banner is the final thing printed. It says
   * one thing the other two cannot: that a red run was the `setup` or `seed`
   * project, and that no product spec ran at all — which is what three separate
   * branches spent a diagnosis each working out by hand (#132).
   */
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report" }],
    ["./e2e/fixture-reporter.ts"],
  ],
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: BASE_URL,

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
  webServer: [
    {
      /*
       * An OpenAI-compatible model server, so the journey spec can run an agent
       * without a provider key and without spending anything. See
       * `e2e/stub-model-server.ts` for what it does and deliberately does not.
       *
       * Started here rather than in CI's workflow so `bun run test:e2e` behaves
       * the same on a laptop, and torn down with the run either way. Never
       * reused: a stale process on this port would answer with whatever an
       * older checkout thought a model should say.
       */
      command: "bun run e2e/stub-model-server.ts",
      url: `http://127.0.0.1:${STUB_MODEL_PORT}/health`,
      // Handed the port explicitly rather than left to inherit it: the server
      // and the two specs that dial it read the same variable, so binding one
      // port while the profile names another becomes impossible instead of a
      // pair of silent `element(s) not found` failures in journey and
      // delegation.
      env: { E2E_STUB_MODEL_PORT: String(STUB_MODEL_PORT) },
      reuseExistingServer: false,
      timeout: 30 * 1000,
    },
    {
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
      url: BASE_URL,
      // Both commands read `PORT` - `next dev` when it is not given `-p`, and the
      // standalone `server.js` always - so this one variable moves whichever one
      // runs. The `dev` and `start` scripts dropped their hardcoded `-p 3000` for
      // exactly this: the port lives here now, not in package.json.
      env: { PORT: String(FRONTEND_PORT) },
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
  ],
});
