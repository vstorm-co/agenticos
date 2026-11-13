import { test, expect } from "./fixtures";
import { AUTH_STATE, nowListed, submitDialog } from "./helpers";

test.use({ storageState: AUTH_STATE, hasTouch: true, isMobile: true, reducedMotion: "reduce" });

test("phone table controls fit, switch formats and persist a default view", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/tables");
  await page.getByRole("button", { name: "New table", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  const name = `Phone controls ${Date.now().toString(36)}`;
  await dialog.getByRole("textbox", { name: /^Name/ }).fill(name);
  await submitDialog(page, {
    dialog,
    submit: dialog.getByRole("button", { name: "Create table", exact: true }),
    path: "/api/tables",
  });
  await nowListed(page.request, "/api/tables", "name", name);
  await expect(page).toHaveURL(/\/tables\/[^/?]+$/);
  const path = new URL(page.url()).pathname;
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    const format = page.getByRole("combobox", { name: "Format", exact: true });
    const view = page.getByRole("combobox", { name: "Select a table view", exact: true });
    const create = page.getByRole("button", { name: "Save as a new view", exact: true });
    const bounds = await Promise.all([format, view, create].map((item) => item.boundingBox()));
    for (const box of bounds) {
      expect(box).not.toBeNull();
      expect(box?.height).toBeGreaterThanOrEqual(43.99);
      expect(box?.y).toBeCloseTo(bounds[0]!.y, 0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    }
    expect(
      await view
        .locator("span")
        .first()
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    expect(
      await format
        .locator("span")
        .first()
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    const actions = page.locator("[data-table-view-toolbar]");
    const row = await Promise.all(
      ["Filter", "Sort", "View settings"].map((action) =>
        actions.getByRole("button", { name: action, exact: true }).boundingBox(),
      ),
    );
    for (const box of row) {
      expect(box?.height).toBeGreaterThanOrEqual(43.99);
      expect(box?.y).toBeCloseTo(row[0]!.y, 0);
    }
  }
  await page.getByRole("combobox", { name: "Format", exact: true }).click();
  await page.getByRole("option", { name: "List", exact: true }).click();
  await page.getByRole("button", { name: "View settings", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Set as default", exact: true })
    .click();
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api${path}`);
      expect(response.ok()).toBe(true);
      const saved: { default_view_id: string | null } = await response.json();
      return saved.default_view_id;
    })
    .toBeTruthy();
  await page.goto(path);
  await expect(page.getByRole("combobox", { name: "Format", exact: true })).toHaveText("List");
  await page.setViewportSize({ width: 320, height: 844 });
  const format = await page.getByRole("combobox", { name: "Format", exact: true }).boundingBox();
  const picker = await page
    .getByRole("combobox", { name: "Select a list view", exact: true })
    .boundingBox();
  expect(picker?.y).toBeCloseTo(format!.y, 0);
  await page.getByRole("button", { name: "Views", exact: true }).click();
  await page.getByRole("menuitem", { name: "Rename", exact: true }).click();
  const rename = page.getByRole("dialog");
  await rename.getByRole("textbox").fill("Phone view");
  await submitDialog(page, {
    dialog: rename,
    submit: rename.getByRole("button", { name: "Save", exact: true }),
    path: `/api${path}/views`,
    method: "PATCH",
  });
  await expect(page.getByRole("combobox", { name: "Select a list view", exact: true })).toHaveText(
    "Phone view",
  );
  expect((await page.request.post(`/api${path}/archive`)).ok()).toBe(true);
});

test("phone catalog filters leave room for search and keep their accessible state", async ({
  page,
}) => {
  test.setTimeout(90_000);
  for (const path of ["/agents", "/skills", "/context", "/workflows", "/tables"]) {
    await page.goto(path);
    const response = await page.request.get(`/api${path}`);
    expect(response.ok(), `${path} must load its real resource`).toBe(true);
    const search = page.locator("[data-search-input]").first();
    await expect(search).toBeVisible();
    const filters =
      path === "/agents"
        ? page.getByRole("combobox", { name: "Filter by status" })
        : page.getByRole("button", { name: /^Filters/ }).first();
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 });
      const box = await filters.boundingBox();
      const input = await search.boundingBox();
      expect(box?.height).toBeGreaterThanOrEqual(43.99);
      expect(box?.width).toBeGreaterThanOrEqual(43.99);
      expect(input?.height).toBeCloseTo(box!.height, 0);
      await expect
        .poll(async () => {
          const [field, button] = await Promise.all([search.boundingBox(), filters.boundingBox()]);
          return Math.abs(field!.y - button!.y);
        })
        .toBeLessThan(0.5);
      expect(input?.width).toBeGreaterThan(path === "/agents" ? 80 : 120);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width - 12);
    }
    await filters.click();
    if (path === "/agents") {
      const published = page.getByRole("option", { name: "Published", exact: true });
      await expect(published).toBeVisible();
      await published.click();
      await expect(filters).toHaveAttribute("aria-expanded", "false");
      await expect(filters).toContainText("Published");
      continue;
    }
    await expect(filters).toHaveAttribute("aria-expanded", "true");
    const panelId = await filters.getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    await expect(page.locator(`[id="${panelId}"]`)).not.toHaveAttribute("hidden");
    await filters.click();
    await expect(filters).toHaveAttribute("aria-expanded", "false");
  }
});
