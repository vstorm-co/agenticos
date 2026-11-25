import { expect, test } from "./fixtures";
import { agentCard, AUTH_STATE, openBuilderTab, SEEDED_AGENT_NAME } from "./helpers";

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
  // Datasets is not pinned, so it lives in More; the sidebar label is "Test data".
  // The trigger also names a connection that needs attention, so match its first word.
  await page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("button", { name: /^More\b/ })
    .click();
  await page
    .getByRole("dialog", { name: "More" })
    .getByRole("link", { name: "Test data", exact: true })
    .click();
  expect((await response).status()).toBe(200);
  await expect(page).toHaveTitle(/^Datasets \| /);
});

test("prompt variables retain readable contrast when console and OS themes disagree", async ({
  page,
}) => {
  await page.goto("/agents");
  await agentCard(page, SEEDED_AGENT_NAME)
    .getByRole("link", { name: `Open ${SEEDED_AGENT_NAME}`, exact: true })
    .click();
  // A card opens an agent needing attention on its Evals tab; the prompt is on Build.
  await openBuilderTab(page, "Build");
  const variable = page.locator("pre").getByText("{{agent_name}}", { exact: true }).first();
  await expect(variable).toBeVisible();
  for (const system of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: system });
    for (const consoleTheme of ["light", "dark"] as const) {
      const contrast = await variable.evaluate((element, theme) => {
        document.documentElement.classList.remove("light", "dark");
        document.documentElement.classList.add(theme);
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 1;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("No color conversion context");
        const luminance = (color: string) => {
          context.fillStyle = color;
          context.fillRect(0, 0, 1, 1);
          return Array.from(context.getImageData(0, 0, 1, 1).data)
            .slice(0, 3)
            .reduce((sum, value, index) => {
              const channel = value / 255;
              const linear =
                channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
              return sum + linear * (index === 0 ? 0.2126 : index === 1 ? 0.7152 : 0.0722);
            }, 0);
        };
        const style = getComputedStyle(element);
        const ink = luminance(style.color);
        const background = luminance(style.backgroundColor);
        return (Math.max(ink, background) + 0.05) / (Math.min(ink, background) + 0.05);
      }, consoleTheme);
      expect(contrast, `${consoleTheme} console / ${system} OS`).toBeGreaterThanOrEqual(4.5);
    }
  }
});
