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
    // The returning user's path: help on demand. It must not write completion —
    // asking for help is not finishing onboarding — so any PATCH here is a bug.
    await page.goto("/agents");
    await expect(pageHeading(page, "Agents")).toBeVisible();

    const patched: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "PATCH" && new URL(request.url()).pathname === "/api/users/me") {
        patched.push(request.url());
      }
    });

    await page.getByRole("button", { name: HELP }).click();
    // The Agents walk opens on its own first stop, not the first-run welcome.
    await expect(page.locator(TITLE)).toHaveText("Build an agent");

    await page.locator(CLOSE).click();
    await expect(page.locator(POPOVER)).toBeHidden();
    expect(patched, "a '?' replay recorded onboarding as finished").toEqual([]);
  });

  test("offers no ? on a page the walkthrough does not cover", async ({ page }) => {
    // Every dashboard page renders the same header, and the deployment-admin
    // section has no stop in the registry — so the button there opened a walk with
    // no steps, which closed itself again. Asserted against a page that *does*
    // carry one, so an assertion passing because the header failed to render is
    // not mistaken for the refusal.
    await page.goto("/agents");
    await expect(page.getByRole("button", { name: HELP })).toBeVisible();

    await page.goto("/admin/users");
    await expect(pageHeading(page)).toBeVisible();
    await expect(page.getByRole("button", { name: HELP })).toHaveCount(0);
  });
});
