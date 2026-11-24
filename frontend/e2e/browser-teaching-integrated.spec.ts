import { test } from "./fixtures";

/**
 * Integrated synthetic acceptance for browser teaching (#113, first slice).
 *
 * DRAFT, skipped. The journey must join the real hosted teaching UI, the teaching
 * APIs and the provisioned browser's input and lease path, on local synthetic HTTPS
 * pages. Mocking the browser, the socket or the capture would pass without proving
 * that join, so this file does not do that. The blockers hold at 658a0398:
 *
 * 1. Teaching is off in the E2E backend. `BROWSER_TEACHING_ENABLED` defaults to false,
 *    and `deployment_enabled()` also needs the organization in
 *    `BROWSER_TEACHING_ORGANIZATION_IDS` (backend/app/core/config.py,
 *    backend/app/services/browser_procedure_teaching/_access.py).
 * 2. No operator-provisioned built-in browser. `BROWSER_SIGN_IN_CDP_URL` and
 *    `BROWSER_CDP_ALLOWED_HOSTS` are empty, and no CI job starts the compose `browser`
 *    profile (backend/app/agents/capabilities/browser_use/__init__.py,
 *    .github/workflows/ci.yml).
 * 3. The provisioned browser sends page traffic through `browser-egress`, which refuses
 *    loopback and private addresses (docker-compose.yml). A local synthetic origin
 *    cannot load through it without changing that boundary.
 *
 * Journey to implement once unblocked:
 * 1. The owner starts a managed run on a synthetic HTTPS page with known labels.
 * 2. The current holder starts Teach a browser procedure. A second tab or member cannot
 *    append to the recording, and losing the lease pauses it.
 * 3. The holder types a synthetic value and passes a sign-in page. Pause and resume need
 *    a fresh takeover token. No typed value or page text reaches stored steps, API
 *    responses or test artifacts.
 * 4. Stop opens the review. The owner keeps the step order, names parameters and creates
 *    a deterministic draft with no model call.
 * 5. The owner applies the proposal and publishes it. A later run on the same origin
 *    discovers the approved procedure and observes the page fresh.
 * 6. The page structure changes. The run refuses the stale procedure and observes again.
 */
test.describe("Browser teaching — integrated synthetic acceptance", () => {
  test.skip(
    true,
    "blocked: no provisioned built-in browser or teaching flag in E2E; see file header",
  );

  test("records, reviews, applies and reuses a taught procedure on the hosted stack", () => {
    throw new Error("Not implemented: complete the journey in this file's header first.");
  });
});
