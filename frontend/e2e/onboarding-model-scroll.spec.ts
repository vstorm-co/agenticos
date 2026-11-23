import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

for (const width of [1280, 390]) {
  test(`model search seals the scroll edge and keeps keyboard selection visible at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
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
      throw new Error("Expected the authenticated onboarding workspace");
    expect(
      state.agents.some(
        (agent: unknown) =>
          agent && typeof agent === "object" && "name" in agent && agent.name === SEEDED_AGENT_NAME,
      ),
    ).toBe(true);

    // Only catalog presentation is simulated; no credential or model is saved.
    await page.route(/\/api\/secrets(?:\?.*)?$/, (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: "11111111-1111-4111-8111-111111111111",
              name: "Catalog layout fixture",
              hint: "test",
              kind: "api_key",
              purpose: "openrouter",
            },
          ],
          total: 1,
        },
      }),
    );
    await page.route(/\/api\/providers\/openrouter\/models(?:\?.*)?$/, (route) =>
      route.fulfill({
        json: {
          items: Array.from({ length: 480 }, (_, index) => ({
            id: `test/model-${index}`,
            name: `Layout model ${index}`,
          })),
          total: 480,
          source: "live",
        },
      }),
    );
    await page.goto(
      `/onboarding?variant=studio&start-step=admin.models&workspace=${encodeURIComponent(state.organization_id)}`,
    );
    await page.getByRole("button", { name: "OpenRouter", exact: true }).click();
    const search = page.getByRole("combobox", { name: "Search models…", exact: true });
    await expect(search).toBeVisible();
    const viewport = page.locator("[data-start-content]");
    const toolbar = page.locator("[data-start-catalog-toolbar]");
    await viewport.hover();
    await page.mouse.wheel(0, 850);
    await expect.poll(() => viewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(700);
    await expect
      .poll(async () => {
        const edge = await viewport.boundingBox();
        const header = await toolbar.boundingBox();
        return edge && header ? Math.abs(header.y - edge.y) : Infinity;
      })
      .toBeLessThanOrEqual(1);
    await search.focus();
    await page.keyboard.press("ArrowDown");
    const selected = page.locator('[cmdk-item][data-selected="true"]').first();
    await expect(selected).toBeVisible();
    await expect
      .poll(async () => {
        const header = await toolbar.boundingBox();
        const option = await selected.boundingBox();
        return header && option ? option.y - header.y - header.height : -Infinity;
      })
      .toBeGreaterThanOrEqual(-1);
  });
}
