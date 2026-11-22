import { expect, test } from "./fixtures";
import { AUTH_STATE, DRAFT_AGENT_NAME, openAgent } from "./helpers";

test.use({ storageState: AUTH_STATE });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "motion-storage",
      JSON.stringify({ state: { motion: "system" }, version: 0 }),
    );
  });
});

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`service disclosures preserve drafts and keyboard access with motion=${reducedMotion}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion });
    await page.goto("/orgs");
    await page
      .getByRole("link", { name: /^Open / })
      .first()
      .click();
    await page.getByRole("tab", { name: "AI & services", exact: true }).click();
    const trigger = page.getByRole("button", { name: "Speech to text", exact: true });
    const panelId = await trigger.getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    const panel = page.locator(`[id="${panelId}"]`);
    await trigger.click();
    const length = page.getByRole("textbox", { name: "Max recording length", exact: true });
    const original = await length.inputValue();
    const edited = original === "7" ? "8" : "7";
    await length.fill(edited);
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(panel).toHaveAttribute("inert", "");
    await expect(panel).toHaveCSS("visibility", "hidden");
    await expect(length).toBeHidden();
    await expect(trigger).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(length).toHaveValue(edited);
    await expect(length).toBeVisible();
    await length.fill(original);
    if (reducedMotion === "reduce") {
      await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");
      await expect
        .poll(() =>
          panel.evaluate((element) =>
            Math.max(
              ...getComputedStyle(element)
                .transitionDuration.split(",")
                .map((duration) => Number.parseFloat(duration)),
            ),
          ),
        )
        .toBeLessThanOrEqual(0.001);
    }
  });
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`builder tab transitions respect motion=${reducedMotion}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion });
    await openAgent(page, DRAFT_AGENT_NAME);
    const toolbox = page.getByRole("tab", { name: "Toolbox", exact: true });
    await toolbox.click();
    const panel = page.getByRole("tabpanel", { name: "Toolbox", exact: true });
    await expect(panel).toBeVisible();
    await expect(panel).toHaveCSS(
      "animation-name",
      reducedMotion === "reduce" ? "none" : "tab-panel-enter",
    );
    await expect(toolbox).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("Enter");
    const build = page.getByRole("tab", { name: "Build", exact: true });
    await expect(build).toHaveAttribute("aria-selected", "true");
    await expect(build).toBeFocused();
    await expect(page.getByRole("tabpanel", { name: "Build", exact: true })).toBeVisible();
    await expect(panel).toBeHidden();
  });
}
