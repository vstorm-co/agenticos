import { expect, test } from "./fixtures";
import { AUTH_STATE, OWNER_EMAIL } from "./helpers";

test.use({ storageState: AUTH_STATE });

const CASES = [
  { preference: "system", system: "no-preference", moving: true },
  { preference: "full", system: "reduce", moving: true },
  { preference: "reduce", system: "no-preference", moving: false },
] as const;

for (const { preference, system, moving } of CASES) {
  test(`Studio resolves ${preference} with OS ${system} for its actual CSS motion`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: system });
    await page.addInitScript((motion) => {
      localStorage.setItem("motion-storage", JSON.stringify({ state: { motion }, version: 0 }));
    }, preference);
    // Keep the authenticated seeded account and its permissions. A photo-free
    // presentation isolates the carousel without deleting the owner's avatar.
    await page.route("**/api/auth/me", async (route) => {
      const response = await route.fetch();
      const person: unknown = await response.json();
      if (!person || typeof person !== "object" || Array.isArray(person))
        throw new Error("Expected the authenticated account");
      await route.fulfill({ response, json: { ...person, avatar_url: null } });
    });
    const response = await page.request.get("/api/me/onboarding");
    expect(response.ok()).toBe(true);
    const state: unknown = await response.json();
    if (
      !state ||
      typeof state !== "object" ||
      !("organization_id" in state) ||
      typeof state.organization_id !== "string"
    )
      throw new Error("Expected the seeded owner's onboarding organization");
    const workspace = encodeURIComponent(state.organization_id);
    await page.goto(`/onboarding?start-step=admin.profile&workspace=${workspace}`);
    await expect(page.getByRole("textbox", { name: "Email", exact: true })).toHaveValue(
      OWNER_EMAIL,
    );
    const stage = page.locator("[data-start-content] > section:not([hidden])");
    const carousel = page.getByRole("region", { name: "Choose your look", exact: true });
    await expect(carousel).toBeVisible();
    await expect
      .poll(() => stage.evaluate((element) => getComputedStyle(element).animationName))
      .toMatch(moving ? /stage-forward/ : /^none$/);
    const track = carousel.locator(":scope > div").nth(1);
    await expect
      .poll(() => track.evaluate((element) => getComputedStyle(element).scrollBehavior))
      .toBe(moving ? "smooth" : "auto");
    await page.goto(`/onboarding?start-step=admin.subscriptions&workspace=${workspace}`);
    const visualGuide = page.locator("[data-start-guide] [aria-hidden]");
    await expect(visualGuide).toHaveCount(1);
    await expect
      .poll(() => visualGuide.evaluate((element) => getComputedStyle(element).display))
      .toBe(moving ? "block" : "none");
  });
}
