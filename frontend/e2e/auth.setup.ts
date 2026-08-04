import { test as setup, expect } from "@playwright/test";

import { AUTH_STATE, OWNER_EMAIL, OWNER_PASSWORD } from "./helpers";

/**
 * Sign in once, and prove it worked.
 *
 * Every other spec reuses the session this writes, so a setup that "succeeds"
 * without authenticating is the most expensive failure in the suite: the whole
 * suite then runs against /login, where the headings and buttons it asserts on
 * are the sign-in page's. That is not hypothetical — the previous version of
 * this file waited for text matching /welcome/i, which the sign-in page itself
 * renders ("Welcome back"), so it passed in under 200ms without ever posting
 * the form, and the suite silently tested the login screen for months.
 *
 * The credentials are the ones `agenticos cmd bootstrap` creates. The suite is
 * meaningless against a database that command has not touched, so defaulting to
 * anything else would only hide the misconfiguration.
 */
setup("authenticate as the bootstrapped owner", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Email").fill(OWNER_EMAIL);
  await page.getByLabel("Password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Login" }).click();

  // Login lands on /dashboard for every role — one landing page, shared by
  // every sign-in path. Arriving there is proof the credentials were accepted;
  // staying on /login is proof they were not.
  //
  // The timeout is raised from the 5s default because this is the run's first
  // navigation into the dashboard, and against `bun run dev` that route is
  // compiled on demand — the whole setup takes ~5.5s on an idle machine, so the
  // default sat just under the line and failed whenever anything else was
  // running. It failed *here*, at the first assertion after the click, which
  // reads exactly like rejected credentials; the login request had in fact
  // returned 200 and the redirect was still compiling. Raising it does not
  // weaken the check: staying on /login for 30s is still a failure.
  await expect(page).toHaveURL(/\/dashboard(\?.*)?$/, { timeout: 30_000 });

  // A URL change alone would also be satisfied by a client-side redirect that
  // bounces straight back. The dashboard shell renders behind `AuthGuard`, so
  // its navigation is only on screen once the session survived a real /auth/me.
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible({
    timeout: 30_000,
  });

  await page.context().storageState({ path: AUTH_STATE });
});
