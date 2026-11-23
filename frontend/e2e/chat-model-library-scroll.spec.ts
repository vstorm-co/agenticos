import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

for (const width of [1440, 390]) {
  test(`model library keeps its header while its lists scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    // The real seeded agent proves the backend is present. Only the vendor's
    // variable-length catalog is controlled for this layout regression.
    const items = Array.from({ length: 40 }, (_, index) => ({
      id: `gpt-layout-${index + 1}`,
      name: `Layout model ${index + 1}`,
      context_length: 128_000,
    }));
    await page.route("**/api/providers/openai/models*", (route) =>
      route.fulfill({ json: { items, total: items.length, source: "live" } }),
    );
    await page.goto("/chat?answerer=agenticos");
    await expect(
      page.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
    ).toBeVisible();
    await page.locator("[data-chat-model]").click();
    const picker = page.locator("[data-chat-popover]");
    const providers = picker.getByRole("group", { name: "Provider", exact: true });
    await providers.getByRole("button", { name: "OpenAI", exact: true }).click();
    const search = picker.getByRole("combobox", { name: "Search models…", exact: true });
    await expect(search).toBeHidden();
    const toolbar = picker.locator("[data-model-toolbar]");
    const modelHeight = await picker
      .getByRole("listbox")
      .evaluate((element) => element.clientHeight);
    await toolbar.getByRole("button", { name: "Search models…", exact: true }).click();
    await expect(search).toBeVisible();
    await expect(search).toBeFocused();
    expect(
      await picker.getByRole("listbox").evaluate((element) => element.clientHeight),
    ).toBeLessThan(modelHeight);
    const list = picker.getByRole("listbox");
    await expect(list.getByRole("option", { name: /Layout model 40/ })).toHaveCount(1);
    await expect
      .poll(() => picker.evaluate((element) => element.scrollHeight - element.clientHeight))
      .toBeLessThanOrEqual(1);
    const initialSearch = await search.boundingBox();
    if (!initialSearch) throw new Error("Expected the model search in the open picker");
    await list.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    await expect(list.getByRole("option").last()).toBeInViewport();
    await providers.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    expect((await search.boundingBox())?.y).toBeCloseTo(initialSearch.y, 0);
    expect(await picker.evaluate((element) => element.scrollTop)).toBe(0);
    await expect(picker.getByRole("button", { name: "Close", exact: true })).toBeInViewport();
    await page.keyboard.press("Escape");
    await expect(search).toBeHidden();
    await expect(
      toolbar.getByRole("button", { name: "Search models…", exact: true }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(picker).toHaveCount(0);
    await expect(page.locator("[data-chat-model]")).toBeFocused();
  });
}
