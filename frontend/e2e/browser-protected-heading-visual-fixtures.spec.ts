import { expect, test } from "./fixtures";
import { BROWSER_IDS as ids } from "../src/test-utils/browser-credential-fixtures";

/**
 * Fixture-only rendering evidence for #112: a protected browse whose output has
 * loaded, so the page title and the protected window are both on screen. No
 * backend runs. The signed-in owner and the browse socket are synthetic, and the
 * socket sends one snapshot with a protected frame and no credential plan.
 *
 * The screenshot comes before the heading assertions, so a run on the unfixed
 * code still leaves the picture of the duplicate.
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
const SUMMARY =
  "Page text, images and ordinary browser controls stay hidden. Saved values may be present.";

test.describe("Browser protected heading — fixture-only visual evidence", () => {
  for (const size of SIZES) {
    test(
      "captures a loaded protected browse with one heading at " + size.name + " width",
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
              type: "browser_snapshot",
              task: "Fixture task",
              can_control: false,
              can_remember: false,
              trace: [
                {
                  kind: "browser_protected",
                  output_protected: true,
                  run_id: ids.run,
                  call_id: CALL,
                  tab_id: "main",
                  step: 1,
                },
              ],
              frame: {
                kind: "browser_frame",
                run_id: ids.run,
                call_id: CALL,
                tab_id: "main",
                step: 1,
                image: "data:image/jpeg;base64,UkFX",
                title: "Fixture page",
                url: "https://fixture.example.test/account",
              },
            }),
          );
        });

        await page.goto("/browse/" + ids.run + "/" + CALL);
        const main = page.getByRole("main");
        await expect(main.getByText(SUMMARY, { exact: true })).toBeVisible();
        await page.screenshot({
          path: testInfo.outputPath("browser-protected-view-one-heading-" + size.name + ".png"),
        });
        await expect(
          main.getByRole("heading", { level: 1, name: "Protected browser", exact: true }),
        ).toBeVisible();
        await expect(
          main.getByRole("heading", { name: "Protected browser", exact: true }),
        ).toHaveCount(1);
        await expect(main.getByText("Protected browser", { exact: true })).toHaveCount(1);
        await expect(
          main.getByRole("region", { name: "Protected browser", exact: true }),
        ).toBeVisible();
      },
    );
  }
});
