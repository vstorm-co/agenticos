import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME, openAgent } from "./helpers";

test.use({ storageState: AUTH_STATE });

for (const width of [1280, 390]) {
  test(`the Builder model catalog scrolls internally and keeps keyboard selection visible at ${width}px`, async ({
    page,
  }) => {
    test.setTimeout(30_000);
    await page.setViewportSize({ width, height: 900 });
    let catalogRequests = 0;
    await page.route(/\/api\/providers\/[^/]+\/models(?:\?.*)?$/, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      catalogRequests += 1;
      await route.fulfill({
        json: {
          items: Array.from({ length: 480 }, (_, index) => ({
            id: `test/model-${index}`,
            name: `Layout model ${index}`,
          })),
          total: 480,
          source: "live",
        },
      });
    });
    await openAgent(page, SEEDED_AGENT_NAME);
    const modelPicker = page.locator('[data-tour="agent-model-picker"]');
    const trigger = modelPicker.getByRole("combobox", { name: "Model", exact: true });
    await expect(trigger).toBeVisible();
    await expect.poll(() => catalogRequests).toBeGreaterThan(0);
    const listId = await trigger.getAttribute("aria-controls");
    if (!listId) throw new Error("The model picker has no catalog list");
    const list = page.locator(`[id="${listId}"]`);
    const search = page.getByPlaceholder("Search models…", { exact: true });
    await trigger.click();
    await expect(search).toBeVisible();
    await expect(list.getByRole("option")).toHaveCount(480);
    await search.focus();
    for (let index = 0; index < 40; index += 1) await page.keyboard.press("ArrowDown");
    await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    const selected = list.locator('[cmdk-item][data-selected="true"]').first();
    await expect(selected).toBeVisible();
    const geometry = await page.evaluate((id) => {
      const listElement = document.getElementById(id);
      const option = listElement?.querySelector<HTMLElement>('[cmdk-item][data-selected="true"]');
      if (!listElement || !option) return null;
      const listBounds = listElement.getBoundingClientRect();
      const optionBounds = option.getBoundingClientRect();
      return {
        listTop: listBounds.top,
        listBottom: listBounds.bottom,
        optionTop: optionBounds.top,
        optionBottom: optionBounds.bottom,
      };
    }, listId);
    if (!geometry) throw new Error("Expected the keyboard selection inside the model list");
    expect(geometry.optionTop).toBeGreaterThanOrEqual(geometry.listTop - 1);
    expect(geometry.optionBottom).toBeLessThanOrEqual(geometry.listBottom + 1);
  });
}
