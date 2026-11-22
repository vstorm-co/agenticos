import { test, expect } from "./fixtures";
import { AUTH_STATE, readAppearanceAs } from "./helpers";

test.use({ storageState: AUTH_STATE });
const catalogs = [
  ["/agents", "Agents", "/api/agents"],
  ["/workflows", "Workflows", "/api/workflows"],
  ["/routines", "Routines", "/api/triggers"],
  ["/datasets", "Datasets", "/api/datasets"],
  ["/apps", "Apps", "/api/apps"],
  ["/projects", "Projects", "/api/projects"],
  ["/rag", "Knowledge bases", "/api/kb"],
  ["/tables", "Tables", "/api/tables"],
  ["/skills", "Skills", "/api/skills"],
] as const;

for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`resource surfaces remain readable in ${theme} at ${width}px`, async ({ page }) => {
      test.setTimeout(180_000);
      await page.setViewportSize({ width, height: 900 });
      await readAppearanceAs(page, theme);
      for (const [path, heading, apiPath] of catalogs) {
        await test.step(path, async () => {
          const loaded = page.waitForResponse(
            (response) =>
              new URL(response.url()).pathname === apiPath && response.request().method() === "GET",
          );
          await page.goto(path);
          const response = await loaded;
          expect(response.ok(), `${path} must read its real catalog`).toBe(true);
          await response.finished();
          const title = page
            .getByRole("main")
            .getByRole("heading", { name: heading, exact: true, level: 1 });
          await expect(title).toBeVisible();
          await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${theme}\\b`));
          const geometry = await title.evaluate((element) => {
            const rect = element.getBoundingClientRect();
            return {
              left: rect.left,
              right: rect.right,
              overflow: document.documentElement.scrollWidth - window.innerWidth,
            };
          });
          expect(geometry.left).toBeGreaterThanOrEqual(0);
          expect(geometry.right).toBeLessThanOrEqual(width + 1);
          expect(geometry.overflow).toBeLessThanOrEqual(1);
          await test.info().attach(`${path.slice(1)}-${theme}-${width}`, {
            body: await page.screenshot(),
            contentType: "image/png",
          });
        });
      }
    });
  }
}
