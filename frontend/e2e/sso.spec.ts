import { expect, test } from "./fixtures";

/**
 * Signing in through the deployment's own identity provider (#1419).
 *
 * The provider is a real Keycloak, not a stub: the point of this spec is the
 * part no unit test reaches — the browser leaving for a host we do not control,
 * a consent-free authorization code coming back, and a session existing
 * afterwards. Everything below the redirect is authlib's and is covered by
 * `backend/tests/test_oidc_sign_in.py`.
 *
 * It is opt-in, because it needs a stack the other specs do not:
 *
 * ```bash
 * docker compose -f docker-compose-dev.yml --profile sso up -d keycloak
 * # backend/.env
 * #   OIDC_ISSUER=http://localhost:8081/realms/agenticos
 * #   OIDC_CLIENT_ID=agenticos
 * #   OIDC_CLIENT_SECRET=e2e-client-secret
 * # frontend
 * #   OAUTH_PROVIDERS=google,oidc
 * E2E_OIDC=1 make test-e2e
 * ```
 *
 * Without `E2E_OIDC` it skips rather than fails: a deployment with no identity
 * provider is the normal one, and a spec that reddens the suite for a container
 * nobody started teaches nothing.
 *
 * The realm is imported from `e2e-fixtures/keycloak/agenticos-realm.json`, so
 * the two accounts are the same on every machine — one whose address the
 * provider has verified, and one whose address it has not.
 */

const CONFIGURED = process.env.E2E_OIDC === "1";

const VERIFIED = { username: "ada", password: "e2e-password" };
const UNVERIFIED = { username: "unverified", password: "e2e-password" };

test.describe("Single sign-on", () => {
  test.skip(!CONFIGURED, "needs the keycloak profile and OIDC_* on the backend");

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/login");
  });

  test("the button says what the deployment calls its provider", async ({ page }) => {
    // Not "Continue with OIDC": a protocol acronym in front of somebody looking
    // for their employer's login is the failure this label exists to avoid.
    await expect(page.getByRole("link", { name: /continue with/i }).last()).toBeVisible();
  });

  test("a verified account signs in and lands in the console", async ({ page }) => {
    await page.getByRole("link", { name: /continue with (sso|keycloak|acme)/i }).click();

    // The browser is now at the provider, on a host this app does not serve.
    await page.waitForURL(/\/realms\/agenticos\//);
    await page.getByLabel(/username|email/i).fill(VERIFIED.username);
    await page.getByLabel(/password/i).fill(VERIFIED.password);
    await page.getByRole("button", { name: /sign in|log in/i }).click();

    // Back through the backend's callback, which redirects to `/auth/callback`
    // with a single-use code the frontend swaps for the token pair.
    await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });
    // No token ever appeared in the address bar on the way here.
    expect(page.url()).not.toMatch(/access_token|refresh_token/);
  });

  test("an account whose address the provider has not verified is refused", async ({ page }) => {
    // The domain allow-list and every invitation are keyed on an address meaning
    // something. A provider that lets somebody set an unverified one is a
    // provider on which anybody claims anybody's work address.
    await page.getByRole("link", { name: /continue with (sso|keycloak|acme)/i }).click();

    await page.waitForURL(/\/realms\/agenticos\//);
    await page.getByLabel(/username|email/i).fill(UNVERIFIED.username);
    await page.getByLabel(/password/i).fill(UNVERIFIED.password);
    await page.getByRole("button", { name: /sign in|log in/i }).click();

    await page.waitForURL(/\/login\?/, { timeout: 30_000 });
    await expect(page.getByText(/cannot be used to sign in/i)).toBeVisible();
  });
});
