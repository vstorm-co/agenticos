import { test, expect } from "./fixtures";
import { AUTH_STATE, readAppearanceAs } from "./helpers";

test.use({ storageState: AUTH_STATE });
const catalogs = [
  ["/agents", "Agents", "/api/agents"],
  ["/workflows", "Workflows", "/api/workflows"],
  ["/routines", "Routines", "/api/triggers"],
  ["/datasets", "Datasets", "/api/datasets"],
  ["/apps", "Pages", "/api/apps"],
  ["/projects", "Projects", "/api/projects"],
  ["/rag", "Knowledge bases", "/api/kb"],
  ["/tables", "Tables", "/api/tables"],
  ["/skills", "Skills", "/api/skills"],
] as const;

for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`resource surfaces remain readable in ${theme} at ${width}px`, async ({ page }) => {
      test.setTimeout(90_000);
      await page.setViewportSize({ width, height: 900 });
      await readAppearanceAs(page, theme);
      for (const [path, heading, apiPath] of catalogs) {
        await test.step(path, async () => {
          const loaded = page.waitForResponse((response) => {
            const url = new URL(response.url());
            // The sidebar's pinned-apps read shares the Apps path and is cancelled by
            // the navigation; only the page's own catalog read proves the page loaded.
            return (
              url.pathname === apiPath &&
              !url.searchParams.has("favourites") &&
              response.request().method() === "GET"
            );
          });
          await page.goto(path);
          const response = await loaded;
          expect(response.ok(), `${path} must read its real catalog`).toBe(true);
          const title = page
            .getByRole("main")
            .getByRole("heading", { name: heading, exact: true, level: 1 });
          // Several surfaces share a catalog path with a sidebar or dashboard read that the
          // navigation cancels; a cancelled body never finishes, so the heading ends the wait.
          await Promise.race([
            response.finished().then(
              () => undefined,
              () => undefined,
            ),
            title.waitFor({ state: "visible" }),
          ]);
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
