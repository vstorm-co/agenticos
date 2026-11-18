import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE });

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
