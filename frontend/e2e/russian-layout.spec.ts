import { test, expect } from "./fixtures";
import { scanClippedText } from "./layout-clipping";
import {
  AUTH_STATE,
  SEEDED_AGENT_NAME,
  SEEDED_KB_NAME,
  SEEDED_PROJECT_NAME,
  SEEDED_SKILL_NAME,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

/**
 * That Russian copy fits the controls it is written into.
 *
 * Russian runs about a quarter longer than English, and the console has many
 * places - buttons, tabs, badges, column headers - whose box is sized for the
 * English word. A label that does not fit is rarely a layout failure anybody
 * would see in a test: `truncate` clips it to "Опубликов…" and the page stays
 * exactly as wide as before, so `console-theme-layout.spec.ts` stays green while
 * a reader can no longer tell two buttons apart.
 *
 * So this reads the clipping itself, on the control and on the text-bearing
 * descendants that do the clipping. Only text the catalog wrote is judged: a
 * clipped element counts when its text is Cyrillic, which a seeded name never
 * is, so an agent name cut short by design does not fail it. The screenshots
 * are attached for a person to look over; the assertion is what fails a push.
 */
const catalogs = [
  ["/agents", "/api/agents", SEEDED_AGENT_NAME],
  ["/workflows", "/api/workflows", null],
  ["/routines", "/api/triggers", null],
  ["/datasets", "/api/datasets", null],
  ["/apps", "/api/apps", null],
  ["/projects", "/api/projects", SEEDED_PROJECT_NAME],
  ["/rag", "/api/kb", SEEDED_KB_NAME],
  ["/tables", "/api/tables", null],
  ["/skills", "/api/skills", SEEDED_SKILL_NAME],
] as const;

/** Controls whose label is copy and whose box is usually sized for it. */
const CONTROLS = [
  "button",
  "a",
  "label",
  "th",
  "[role=tab]",
  "[role=menuitem]",
  "[role=option]",
  "[data-slot=badge]",
  "h1",
  "h2",
  "h3",
].join(",");

for (const width of [1280, 390]) {
  test(`Russian skill file actions fit their controls at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/ru/skills");
    await expect(page.getByText(SEEDED_SKILL_NAME, { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Новый навык", exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: "Новый навык" });
    await expect(dialog).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    const actions = dialog
      .getByRole("button", { name: "Новый файл", exact: true })
      .or(dialog.locator("label").filter({ hasText: /^(Файлы|Папка)$/ }));
    await expect(actions).toHaveCount(3);

    for (const action of await actions.all()) {
      const overflow = await action.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const contents = document.createRange();
        contents.selectNodeContents(element);
        const content = contents.getBoundingClientRect();
        return Math.max(box.left - content.left, content.right - box.right);
      });
      expect(
        overflow,
        `${await action.innerText()} spills outside its control`,
      ).toBeLessThanOrEqual(1);
    }
  });

  test(`Russian copy fits its controls at ${width}px`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    for (const [path, apiPath, seededName] of catalogs) {
      await test.step(path, async () => {
        const loaded = page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname === apiPath && response.request().method() === "GET",
        );
        await page.goto(`/ru${path}`);
        const response = await loaded;
        expect(response.ok(), `${path} must read its real catalog`).toBe(true);
        await response.finished();
        await expect(page.locator("html")).toHaveAttribute("lang", "ru");
        const title = page.getByRole("main").getByRole("heading", { level: 1 });
        // Cyrillic, so the page is served from ru.json rather than English underneath.
        await expect(title).toHaveText(/[А-Яа-яЁё]/);

        // The response finishing is not the result rendering: the header and its
        // filters are already on screen while the list is still a skeleton. The
        // scan runs once, so a list measured during that skeleton proves nothing
        // about the cards it later draws. Wait for the committed result - the
        // loading status gone, and, where the seed leaves a row, that row drawn.
        const main = page.getByRole("main");
        await expect(main.locator('[aria-busy="true"]')).toHaveCount(0);
        if (seededName !== null) {
          await expect(main.getByText(seededName).first()).toBeVisible();
        }
        await page.evaluate(() => document.fonts.ready);

        const report = await page.evaluate(scanClippedText, CONTROLS);

        await test.info().attach(`ru${path.replace(/\//g, "-")}-${width}`, {
          body: await page.screenshot({ fullPage: true }),
          contentType: "image/png",
        });
        const box = await title.boundingBox();
        expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
        expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width + 1);
        expect(report.overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(1);
        expect(report.clipped, `${path} clips Russian copy`).toEqual([]);
      });
    }
  });
}

test("the scan reports a clipped label inside a control, not the control itself or a screen-reader label", async ({
  page,
}) => {
  // A short fixture rather than a page: the defect is a label clipped by a child
  // of a control that fits its box, which is the shape of the sidebar link and
  // the Select. A scan that only measures the control stays green here.
  await page.setContent(`
    <div id="clipping-fixture">
      <a href="#" style="display:block;width:120px">
        <span style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:16px sans-serif">Опубликованные</span>
      </a>
      <a href="#" style="display:block;width:320px;font:16px sans-serif">Все</a>
      <a href="#" style="display:block;width:320px;font:16px sans-serif">
        <span style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap">Переключить меню</span>
      </a>
    </div>
  `);

  const report = await page.evaluate(scanClippedText, "#clipping-fixture a");

  expect(report.clipped).toHaveLength(1);
  expect(report.clipped[0]).toContain("span");
  expect(report.clipped[0]).toContain("Опубликованные");
});
