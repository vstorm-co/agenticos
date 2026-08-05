import { expect, test } from "./fixtures";

import type { Page } from "@playwright/test";

import { AUTH_STATE, OWNER_EMAIL, OWNER_PASSWORD } from "./helpers";

/**
 * The way out, at the foot of the sidebar.
 *
 * It used to be an unnamed button in the top bar, found by taking the last one
 * there. There is no top bar above `md` any more, and the trigger now says who
 * it belongs to — which is a better handle than a position.
 */
function accountMenu(page: Page) {
  return page.getByRole("complementary").getByRole("button", { name: new RegExp(OWNER_EMAIL) });
}

/**
 * The door.
 *
 * Signing in is exercised for real by `auth.setup.ts`, which the whole suite
 * depends on. What is left here is the behaviour around it: where an
 * unauthenticated visitor lands, what a refused sign-in says, and that a
 * refusal is a refusal from the backend rather than a message the form made up.
 */

test.describe("Authentication", () => {
  // There is no landing page — a self-hosted deployment has nothing to market —
  // so the root is a door into the app and must open on the sign-in form.
  test("the root lands on the sign-in form", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/");

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: /sign in|log in/i })).toBeVisible();
  });

  test("the root keeps the locale it was reached on", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/pl");

    await expect(page).toHaveURL(/\/pl\/login$/);
  });

  test("a deep link survives the login round trip, fragment included", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/agents?tab=all#list");

    // Landing on the default page after signing in would mean the link the
    // visitor followed - from an email, a doc - was silently swallowed. The
    // query and the fragment are part of the link: an anchored section that
    // comes back unanchored was swallowed too, just more quietly.
    await expect(page).toHaveURL(/\/login\?returnTo=%2Fagents%3Ftab%3Dall%23list/, {
      timeout: 30_000,
    });

    await page.getByLabel("Email").fill(OWNER_EMAIL);
    await page.getByLabel("Password").fill(OWNER_PASSWORD);
    await page.getByRole("button", { name: "Login" }).click();

    await expect(page).toHaveURL(/\/agents\?tab=all#list$/, { timeout: 30_000 });
  });

  test.describe("Login Page", () => {
    test("displays the sign-in form", async ({ page }) => {
      await page.goto("/login");

      await expect(page.getByRole("heading", { name: /sign in|log in/i })).toBeVisible();
      await expect(page.getByLabel("Email")).toBeVisible();
      await expect(page.getByLabel("Password")).toBeVisible();
      await expect(page.getByRole("button", { name: "Login" })).toBeVisible();
    });

    test("does not submit an empty form", async ({ page }) => {
      await page.goto("/login");

      let attempted = false;
      page.on("request", (request) => {
        if (new URL(request.url()).pathname === "/api/auth/login") attempted = true;
      });

      await page.getByRole("button", { name: "Login" }).click();

      // Both fields are `required`, so the browser refuses the submit itself.
      // Asserting the request was never made is the only way to tell that apart
      // from a submit that happened and failed.
      await expect(page).toHaveURL(/\/login$/);
      expect(attempted, "an empty sign-in form was posted to the backend").toBe(false);
    });

    test("a wrong password is refused by the backend, and said so", async ({ page }) => {
      await page.goto("/login");

      const refusal = page.waitForResponse(
        (response) => new URL(response.url()).pathname === "/api/auth/login",
      );

      await page.getByLabel("Email").fill("invalid@example.com");
      await page.getByLabel("Password").fill("wrongpassword");
      await page.getByRole("button", { name: "Login" }).click();

      // 401, not 500: the message on screen has to be the backend refusing the
      // credentials, not the frontend reporting that it could not reach it. The
      // two read almost identically to a user and mean opposite things to
      // whoever is on call.
      expect((await refusal).status()).toBe(401);
      await expect(page.getByText("Login failed").first()).toBeVisible();
      await expect(page).toHaveURL(/\/login$/);
    });

    test("has a link to registration", async ({ page }) => {
      await page.goto("/login");

      await expect(
        page.getByRole("link", { name: /sign up|register|create account/i }),
      ).toBeVisible();
    });
  });

  test.describe("Registration Page", () => {
    test("displays the registration form", async ({ page }) => {
      await page.goto("/register");

      await expect(page.getByRole("heading", { name: /sign up|register|create/i })).toBeVisible();
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/password/i).first()).toBeVisible();
      await expect(page.getByRole("button", { name: /sign up|register|create/i })).toBeVisible();
    });

    test("refuses a password shorter than the backend would accept", async ({ page }) => {
      await page.goto("/register");

      await page.getByLabel("Email").fill("newuser@example.com");
      // Both boxes, because they are `required`: leaving the confirmation empty
      // would have the browser block the submit and this would be testing HTML
      // rather than the rule.
      await page.getByLabel("Password", { exact: true }).fill("weak");
      await page.getByLabel("Confirm Password").fill("weak");
      await page.getByRole("button", { name: "Register" }).click();

      // Refused here rather than by a 422 from the API. The number is the
      // backend's — `UserCreate` sets min_length=8 — so this is the frontend
      // agreeing with it, not inventing a rule of its own.
      await expect(page.getByText("Password must be at least 8 characters")).toBeVisible();
    });

    test("has a link to login", async ({ page }) => {
      await page.goto("/register");

      await expect(page.getByRole("link", { name: "Login" })).toBeVisible();
    });
  });

  test.describe("Authenticated user", () => {
    test.use({ storageState: AUTH_STATE });

    test("the account block names who is signed in", async ({ page }) => {
      await page.goto("/dashboard");

      // At the foot of the column, and readable without opening anything. The
      // address comes from /auth/me, so a shell rendered without a session
      // cannot produce it.
      await expect(accountMenu(page)).toBeVisible();
    });

    test("signing out ends the session, not just the page", async ({ page }) => {
      await page.goto("/dashboard");
      await accountMenu(page).click();

      await page.getByRole("menuitem", { name: /log out|sign out/i }).click();
      await expect(page).toHaveURL(/\/login/);

      // The redirect alone would also happen if only client state were cleared.
      // Asking for a protected page again is what proves the cookie is gone.
      await page.goto("/agents");
      await expect(page).toHaveURL(/\/login/);
    });
  });
});

/**
 * The credentials the rest of the suite runs on actually work.
 *
 * `auth.setup.ts` proves this too, but it runs once and its failure reads as
 * "setup failed" rather than "sign-in is broken". Kept here so the suite says
 * which of the two happened.
 */
test("the bootstrapped owner can sign in", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(OWNER_EMAIL);
  await page.getByLabel("Password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Login" }).click();

  await expect(page).toHaveURL(/\/dashboard(\?.*)?$/);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
});
