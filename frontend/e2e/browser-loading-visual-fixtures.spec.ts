import { expect, test } from "./fixtures";
import { BROWSER_IDS as ids } from "../src/test-utils/browser-credential-fixtures";

/**
 * Fixture-only rendering evidence for #112: a protected browse whose output is
 * still loading. No backend runs. The signed-in owner and the browse socket are
 * synthetic, and the socket sends one protected frame and never a snapshot, so
 * the page stays in its loading state.
 */
const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;
const CALL = "browser-call";
const OWNER = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "fixture-owner@example.test",
  full_name: "Fixture owner",
  email_verified: true,
};

test.describe("Browser protected loading — fixture-only visual evidence", () => {
  for (const size of SIZES) {
    test(
      "captures a protected browse while its output loads at " + size.name + " width",
      async ({ page }, testInfo) => {
        await page.setViewportSize(size);
        // Registered first so the specific routes below take precedence. Every
        // other API call answers 404: a 5xx would fail the apiFailures fixture.
        await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
        await page.route("**/api/auth/me", (route) =>
          route.fulfill({ json: { ...OWNER, access_token: "fixture-access-token" } }),
        );
        await page.routeWebSocket(new RegExp("/api/v1/ws/browse/" + ids.run + "/" + CALL), (ws) => {
          ws.send(
            JSON.stringify({
              kind: "browser_protected",
              output_protected: true,
              run_id: ids.run,
              call_id: CALL,
              tab_id: "main",
              step: 2,
              credential_plan_id: ids.plan,
              credential_operation: "fill",
            }),
          );
        });

        await page.goto("/browse/" + ids.run + "/" + CALL);
        const main = page.getByRole("main");
        const title = main.getByRole("heading", { level: 1, name: /^(Live|Protected) browser$/ });
        await expect(title).toBeVisible();
        await page.screenshot({
          path: testInfo.outputPath("browser-protected-loading-" + size.name + ".png"),
        });
        await expect(title).toHaveText("Protected browser");
        await expect(main.getByRole("heading", { name: "Live browser", exact: true })).toHaveCount(
          0,
        );
      },
    );
  }
});
