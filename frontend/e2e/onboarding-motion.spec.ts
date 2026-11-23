import { expect, test } from "./fixtures";
import { AUTH_STATE, OWNER_EMAIL } from "./helpers";

test.use({ storageState: AUTH_STATE });

const CASES = [
  { preference: null, system: "reduce", moving: true },
  { preference: "system", system: "no-preference", moving: true },
  { preference: "full", system: "reduce", moving: true },
  { preference: "reduce", system: "no-preference", moving: false },
] as const;

for (const { preference, system, moving } of CASES) {
  test(`Studio resolves ${preference} with OS ${system} for its scene and carousel`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: system });
    await page.addInitScript((motion) => {
      if (motion === null) localStorage.removeItem("motion-storage");
      else
        localStorage.setItem("motion-storage", JSON.stringify({ state: { motion }, version: 0 }));
    }, preference);
    // Keep the authenticated seeded account and its permissions. A photo-free
    // presentation isolates the carousel without deleting the owner's avatar.
    await page.route("**/api/auth/me", async (route) => {
      const response = await route.fetch();
      const person: unknown = await response.json();
      if (!person || typeof person !== "object" || Array.isArray(person))
        throw new Error("Expected the authenticated account");
      await route.fulfill({ response, json: { ...person, avatar_url: null, avatar_color: null } });
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
    const stage = page.locator("[data-start-content]");
    const carousel = page.getByRole("region", { name: "Choose your look", exact: true });
    await expect(carousel).toBeVisible();
    await expect.poll(() => stage.evaluate((element) => element.getAnimations().length)).toBe(0);
    const viewport = carousel.locator("[data-avatar-carousel-viewport]");
    const track = carousel.locator("[data-avatar-carousel-track]");
    await expect(viewport).toHaveAttribute("data-motion", moving ? "spring" : "instant");
    const before = await track.evaluate((element) => getComputedStyle(element).transform);
    await carousel.getByRole("button", { name: "Next look", exact: true }).click();
    await expect(carousel.locator('[data-current="true"] button')).toHaveAccessibleName("Colour 1");
    await expect
      .poll(() => track.evaluate((element) => getComputedStyle(element).transform))
      .not.toBe(before);
    // Browsing previews must not select or save an avatar colour.
    await expect(
      carousel.getByRole("button", { name: "Automatic colour", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(viewport).toHaveCSS("overflow", "clip");
    const footer = page.locator("[data-start-navigation]");
    const footerBefore = await footer.boundingBox();
    if (!footerBefore) throw new Error("Expected the onboarding footer");
    await page.getByRole("textbox", { name: "Display name", exact: true }).fill("Unsaved preview");
    const [sceneMoved] = await Promise.all([
      stage.evaluate(async (element) => {
        const until = performance.now() + 800;
        while (performance.now() < until) {
          if (element.getAnimations().some((animation) => animation.playState === "running"))
            return true;
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        }
        return false;
      }),
      footer.getByRole("button", { name: "Back", exact: true }).click(),
    ]);
    expect(sceneMoved).toBe(moving);
    const footerAfter = await footer.boundingBox();
    if (!footerAfter) throw new Error("Expected the onboarding footer after changing step");
    expect(Math.abs(footerAfter.y - footerBefore.y)).toBeLessThan(2);
    await page
      .getByRole("navigation", { name: "Your workspace, coming together", exact: true })
      .getByRole("button", { name: /About you/ })
      .click();
    await expect(page.getByRole("textbox", { name: "Display name", exact: true })).toHaveValue(
      "Unsaved preview",
    );
    await page.goto(`/onboarding?start-step=admin.subscriptions&workspace=${workspace}`);
    const visualGuide = page.locator(
      "[data-start-content] > section:not([hidden]) [data-start-guide] [aria-hidden]",
    );
    await expect(visualGuide).toHaveCount(1);
    await expect
      .poll(() => visualGuide.evaluate((element) => getComputedStyle(element).display))
      .toBe(moving ? "block" : "none");
  });
}
