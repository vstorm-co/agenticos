import { version } from "../package.json";
import { test, expect } from "./fixtures";

test("release notes appear after sign-in and stay dismissed on this device", async ({ page }) => {
  await page.route("**/api/releases/current", (route) =>
    route.fulfill({
      json: {
        release: {
          version,
          url: `https://github.com/vstorm-co/agenticos/releases/tag/v${version}`,
          body: "## Release improvements\n\nA deterministic release for this journey.",
        },
      },
    }),
  );
  await page.goto("/dashboard");
  const notes = page.getByRole("dialog", { name: `What’s new in ${version}` });
  await expect(notes).toBeVisible();
  await expect(notes).toContainText("A deterministic release for this journey.");
  await notes.getByRole("button", { name: "Got it", exact: true }).click();
  await expect(notes).toBeHidden();
  await page.reload();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(notes).toBeHidden();
});
