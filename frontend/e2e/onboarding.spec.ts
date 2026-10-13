import { expect, test } from "./fixtures";

import { AUTH_STATE, pageHeading } from "./helpers";

/**
 * The walkthrough, which every other spec in this suite spends its life avoiding.
 *
 * `seed.setup.ts` marks the owner's onboarding finished precisely so the first-run
 * tour does not auto-open over every page the rest of the suite loads — its
 * driver.js overlay is `allowClose: false` and swallows clicks behind it, which is
 * how six specs went red the day this feature landed. That leaves the feature with
 * no end-to-end cover at all, and the thing worth covering is exactly the seam the
 * seed papers over: whether the tour opens itself for a user who has not finished,
 * and whether dismissing it is remembered on the server rather than in a browser.
 *
 * So this spec unsets the flag, does the journey, and puts it back. `workers: 1`
 * and `fullyParallel: false` are what make that safe — no other spec is loading a
 * page while the flag is off. A run killed mid-test leaves it off, and the seed
 * sets it again at the head of the next run, so the damage is bounded to nothing.
 *
 * The popover is driver.js's, so it is found by driver's own class names rather
 * than a role: it renders a `div` with no dialog semantics, and the app styles it
 * through the same selectors (`globals.css`).
 */
test.use({ storageState: AUTH_STATE });

const POPOVER = ".driver-popover";
const TITLE = ".driver-popover-title";
const NEXT = ".driver-popover-next-btn";
const CLOSE = ".driver-popover-close-btn";
const HELP = "Show tips for this page";

/** Put the owner back where the seed left them, whatever the test did. */
test.afterEach(async ({ page }) => {
  const response = await page.request.patch("/api/users/me", {
    data: { onboarding_completed_at: new Date().toISOString() },
  });
  expect(response.ok(), `restoring onboarding done answered ${response.status()}`).toBe(true);
});

test.describe("Onboarding", () => {
  test("greets a user who has not finished, and remembers the dismissal on the server", async ({
    page,
  }) => {
    const reset = await page.request.patch("/api/users/me", {
      data: { onboarding_completed_at: null },
    });
    expect(reset.ok(), `resetting onboarding answered ${reset.status()}`).toBe(true);

    await page.goto("/dashboard");

    // Data-borne in the only way this feature can be: the copy is the catalog's,
    // and it is on screen because the *server* said this user has not finished.
    await expect(page.locator(TITLE)).toHaveText("Welcome to AgenticOS");
    await expect(page.locator(POPOVER)).toContainText("Step 1 of");

    // Next walks it, which is the whole of the interaction.
    await page.locator(NEXT).click();
    await expect(page.locator(TITLE)).not.toHaveText("Welcome to AgenticOS");

    // Closing writes `onboarding_completed_at` through PATCH /users/me. Waiting on
    // the write rather than on the overlay disappearing: the overlay goes the
    // moment the store closes, which says nothing about whether it was recorded,
    // and "it came back on the next device" is the failure this persistence exists
    // to prevent.
    const written = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/users/me" &&
        response.request().method() === "PATCH" &&
        response.status() !== 401,
    );
    await page.locator(CLOSE).click();
    const response = await written;
    expect(response.ok(), `dismissing the tour answered ${response.status()}`).toBe(true);
    await expect(page.locator(POPOVER)).toBeHidden();

    // And it does not come back on the next load, which is the point of the write.
    await page.goto("/dashboard");
    await expect(pageHeading(page, "Dashboard")).toBeVisible();
    await expect(page.locator(POPOVER)).toBeHidden();
  });

  test("replays the current page's tips from the header ?, without re-onboarding", async ({
    page,
  }) => {
    // Help on demand, and it must not record completion — asking for help is not
    // finishing onboarding. The flag is *unset* for this, deliberately: with it
    // already set, `dismiss` short-circuits on the flag rather than on the mode,
    // and the assertion below would pass against a build that had lost the
    // distinction entirely. `/agents` is not where the first-run tour auto-opens,
    // so unsetting it here starts nothing.
    const reset = await page.request.patch("/api/users/me", {
      data: { onboarding_completed_at: null },
    });
    expect(reset.ok(), `resetting onboarding answered ${reset.status()}`).toBe(true);

    await page.goto("/agents");
    await expect(pageHeading(page, "Agents")).toBeVisible();

    // Raced against a deadline rather than sampled after the fact: the write, if it
    // came, is fired from an un-awaited async call, so "no request yet" a
    // millisecond after the close proves nothing.
    const stray = page
      .waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/users/me" &&
          response.request().method() === "PATCH",
        { timeout: 3_000 },
      )
      .then(() => true)
      .catch(() => false);

    await page.getByRole("button", { name: HELP }).click();
    // The Agents walk opens on its own first stop, not the first-run welcome.
    // Its first stop is the template gallery, which sits before "Build an
    // agent" because starting from one is the shorter path (#1341 shipped it).
    await expect(page.locator(TITLE)).toHaveText("Start from a template");

    await page.locator(CLOSE).click();
    await expect(page.locator(POPOVER)).toBeHidden();
    expect(await stray, "a '?' replay wrote to /users/me").toBe(false);

    // And the server agrees: still unfinished, so the first-run tour is still owed.
    const me = await (await page.request.get("/api/users/me")).json();
    expect(me.onboarding_completed_at).toBeNull();
  });

  test("offers no ? on a page the walkthrough does not cover", async ({ page }) => {
    // Every dashboard page renders the same header, and the deployment-admin
    // section has no stop in the registry — so the button there opened a walk with
    // no steps, which closed itself again. Asserted against a page that *does*
    // carry one, so an assertion passing because the header failed to render is
    // not mistaken for the refusal.
    await page.goto("/agents");
    await expect(page.getByRole("button", { name: HELP })).toBeVisible();

    // By its own title, not by "some h1": a redirect, a 403 or an error boundary
    // renders a heading too, and against `toBeVisible()` alone the count below
    // would pass without the admin header ever having been on screen.
    await page.goto("/admin/users");
    await expect(pageHeading(page, "Workspace administration")).toBeVisible();
    await expect(page.getByRole("button", { name: HELP })).toHaveCount(0);
  });
});
