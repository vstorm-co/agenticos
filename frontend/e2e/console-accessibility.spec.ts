import { expect, test } from "./fixtures";
import { agentCard, AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

test.use({ storageState: AUTH_STATE });

test("search retains keyboard focus in Windows high contrast", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto("/agents");
  await expect(page.getByRole("main").getByText(SEEDED_AGENT_NAME, { exact: true })).toBeVisible();
  const search = page.getByRole("textbox", { name: "Search agents" });
  await search.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(search).toBeFocused();
  await expect(search).toHaveCSS("outline-style", "solid");
  await expect(search).toHaveCSS("outline-width", "2px");
});

test("the Builder loading state fits a phone before the agent arrives", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/agents");
  const card = agentCard(page, SEEDED_AGENT_NAME);
  await expect(card).toBeVisible();
  const href = await card
    .getByRole("link", { name: `Open ${SEEDED_AGENT_NAME}`, exact: true })
    .getAttribute("href");
  if (!href) throw new Error("The seeded agent has no Builder link");
  const gate = Promise.withResolvers<void>();
  await page.route(`**/api${href}`, async (route) => {
    await gate.promise;
    await route.continue();
  });
  try {
    await page.goto(href);
    const main = page.getByRole("main");
    await expect(main.getByRole("status")).toBeVisible();
    await expect
      .poll(() => main.evaluate((element) => element.scrollWidth <= element.clientWidth))
      .toBe(true);
  } finally {
    gate.resolve();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("browser titles follow destinations after client navigation and reload", async ({ page }) => {
  await page.goto("/agents");
  await expect(page.getByRole("main").getByText(SEEDED_AGENT_NAME, { exact: true })).toBeVisible();
  await expect(page).toHaveTitle(/^Agents \| /);
  await page.reload();
  await expect(page.getByRole("main").getByText(SEEDED_AGENT_NAME, { exact: true })).toBeVisible();
  await expect(page).toHaveTitle(/^Agents \| /);
  const response = page.waitForResponse(
    (answer) =>
      new URL(answer.url()).pathname === "/api/datasets" && answer.request().method() === "GET",
  );
  await page.getByRole("link", { name: "Datasets", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page).toHaveTitle(/^Datasets \| /);
});
