import { expect, test } from "./fixtures";

import { AUTH_STATE, DASHBOARD_GREETING, pageHeading } from "./helpers";

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
    await expect(pageHeading(page, DASHBOARD_GREETING)).toBeVisible();
    await expect(page.locator(POPOVER)).toBeHidden();
  });

  test("leaves a browser extension's prompt clickable, and the page under the tour not", async ({
    page,
  }) => {
    // driver.css turns pointer events off for everything under <body> while the
    // tour runs, which reached into what extensions inject there: a password
    // manager's save prompt sat on screen, unclosable, for the whole walk. The
    // prompt is stood in for the way those extensions build theirs - a custom
    // element under <body>, its button in a shadow root, stacked at the top.
    const reset = await page.request.patch("/api/users/me", {
      data: { onboarding_completed_at: null },
    });
    expect(reset.ok(), `resetting onboarding answered ${reset.status()}`).toBe(true);
    await page.goto("/dashboard");
    await expect(page.locator(TITLE)).toHaveText("Welcome to AgenticOS");

    await page.evaluate(() => {
      const host = document.createElement("extension-prompt");
      host.style.cssText = "position:fixed;top:12px;right:12px;z-index:2147483647";
      const button = document.createElement("button");
      button.textContent = "Dismiss";
      button.addEventListener("click", () => host.remove());
      host.attachShadow({ mode: "open" }).appendChild(button);
      document.body.appendChild(host);
    });
    await page.locator("extension-prompt").getByRole("button", { name: "Dismiss" }).click();
    await expect(page.locator("extension-prompt")).toHaveCount(0);

    // The product itself is still held. Asserted on what the click reached rather
    // than on the URL or the caption: both still read the same in the moment
    // before a navigation the click had started would land. Anything a click hits
    // that is not one of the tour's own layers is the page, and must not be hit.
    await page.evaluate(() => {
      const reached: string[] = [];
      (window as Window & { reached?: string[] }).reached = reached;
      document.addEventListener(
        "click",
        (event) => {
          const target = event.target as Element;
          if (!target.closest(".tour-spotlight, .driver-overlay, .driver-popover")) {
            reached.push(target.outerHTML.slice(0, 120));
          }
        },
        true,
      );
    });
    const reachedPage = () =>
      page.evaluate(() => (window as Window & { reached?: string[] }).reached);

    const agents = page.getByRole("navigation", { name: "Primary" }).getByRole("link", {
      name: "Agents",
    });
    const link = await agents.boundingBox();
    expect(link, "the sidebar's Agents link is on screen").not.toBeNull();
    await page.mouse.click(link!.x + link!.width / 2, link!.y + link!.height / 2);
    expect(await reachedPage(), "a click on the sidebar reached the page").toEqual([]);

    // And inside the light's padding, beside the control it frames. driver's
    // overlay has a hole there, so only the tour's own shield stands between the
    // click and whatever sits next to the control.
    await page.locator(NEXT).click();
    await expect(page.locator(TITLE)).toHaveText("Slice the dashboard");
    const lit = page.locator('.driver-active-element[data-tour="dashboard-filters"]');
    await expect(page.locator(".tour-spotlight-ring.is-visible")).toBeVisible();
    const control = await lit.boundingBox();
    expect(control, "the lit control is on screen").not.toBeNull();
    await page.mouse.click(control!.x - 4, control!.y + control!.height / 2);
    expect(await reachedPage(), "a click in the light's padding reached the page").toEqual([]);
    await expect(page.locator(TITLE)).toHaveText("Slice the dashboard");
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
        (response) => {
          const request = response.request();
          if (new URL(response.url()).pathname !== "/api/users/me" || request.method() !== "PATCH")
            return false;
          // Profile initialization may save the browser's time zone in parallel.
          // Only an onboarding write would incorrectly finish this page replay.
          const body: unknown = request.postDataJSON();
          return typeof body === "object" && body !== null && "onboarding_completed_at" in body;
        },
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
    await expect(pageHeading(page, "Administration")).toBeVisible();
    await expect(page.getByRole("button", { name: HELP })).toHaveCount(0);
  });
});
