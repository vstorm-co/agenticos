import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

const CASES = [
  { preference: null, system: "reduce", moving: true },
  { preference: "system", system: "no-preference", moving: true },
  { preference: "full", system: "reduce", moving: true },
  { preference: "reduce", system: "no-preference", moving: false },
] as const;

for (const { preference, system, moving } of CASES) {
  test(`the dashboard tip carousel resolves ${preference} with OS ${system}`, async ({ page }) => {
    await page.clock.install();
    await page.emulateMedia({ reducedMotion: system });
    await page.addInitScript((motion) => {
      localStorage.removeItem("agenticos:discover-tips:dismissed");
      if (motion === null) localStorage.removeItem("motion-storage");
      else
        localStorage.setItem("motion-storage", JSON.stringify({ state: { motion }, version: 0 }));
    }, preference);
    const response = await page.request.get("/api/me/onboarding");
    expect(response.ok()).toBe(true);
    const state: unknown = await response.json();
    if (
      !state ||
      typeof state !== "object" ||
      !("organization_id" in state) ||
      typeof state.organization_id !== "string" ||
      !("agents" in state) ||
      !Array.isArray(state.agents)
    )
      throw new Error("Expected the seeded owner's dashboard workspace");
    expect(
      state.agents.some(
        (agent: unknown) =>
          agent && typeof agent === "object" && "name" in agent && agent.name === SEEDED_AGENT_NAME,
      ),
    ).toBe(true);

    await page.goto("/dashboard?view=me");
    await expect(page.locator('[data-dashboard-view="me"]')).toBeVisible();
    const active = page.locator("article[data-lit]");
    await expect(active).toHaveCount(1);
    await expect(active).toBeVisible();
    const tileCount = await active.evaluate(
      (element) => element.parentElement?.querySelectorAll("article[aria-label]").length ?? 0,
    );
    expect(tileCount).toBeGreaterThan(1);
    const initialTitle = await active.getAttribute("aria-label");
    if (!initialTitle) throw new Error("Expected the active dashboard tip to have a title");

    if (moving) await expect(page.locator("html")).not.toHaveAttribute("data-motion", "reduce");
    else await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");

    await page.clock.runFor(5_001);
    if (moving) {
      await expect
        .poll(() => page.locator("article[data-lit]").getAttribute("aria-label"))
        .not.toBe(initialTitle);
    } else {
      await expect(page.locator("article[data-lit]")).toHaveAttribute("aria-label", initialTitle);
    }
  });
}
