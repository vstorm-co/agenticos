import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_AGENT_NAME } from "./helpers";

declare global {
  interface Window {
    keyboardViewportFixture: { setGeometry(height: number, offsetTop: number): void };
  }
}

test.use({ storageState: AUTH_STATE, viewport: { width: 390, height: 844 } });

// Controls viewport measurements, not a real OS keyboard. This regression checks
// the product's layout when Safari's measurements change without timely events.
test("keeps the focused composer and header in a panned visual viewport before typing", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const viewport = new (class extends EventTarget {
      height = 844;
      offsetTop = 0;
      scale = 1;
    })();
    Object.defineProperty(window, "visualViewport", { value: viewport });
    window.keyboardViewportFixture = {
      setGeometry(height, offsetTop) {
        viewport.height = height;
        viewport.offsetTop = offsetTop;
      },
    };
  });
  await page.goto("/chat?answerer=agenticos");
  await expect(
    page.getByRole("button", { name: `Agent: ${SEEDED_AGENT_NAME}`, exact: true }),
  ).toBeVisible();
  const composer = page.locator(".composer-box");
  const editor = composer.getByRole("textbox");
  await expect(editor).toBeEditable();
  await editor.focus();
  await page.evaluate(() => window.keyboardViewportFixture.setGeometry(420, 70));
  const shell = page.locator('[class*="top-[var(--app-top"]');
  await expect.poll(async () => (await shell.boundingBox())?.y).toBe(70);
  await expect.poll(async () => (await shell.boundingBox())?.height).toBe(420);
  const box = await composer.boundingBox();
  if (!box) throw new Error("The focused composer must have visible bounds");
  expect(box.y).toBeGreaterThanOrEqual(70);
  expect(box.y + box.height).toBeLessThanOrEqual(490);
  expect(
    (await page.getByRole("button", { name: "Toggle menu", exact: true }).boundingBox())?.y,
  ).toBeGreaterThanOrEqual(70);
  await expect(editor).toBeEmpty();
  await editor.fill("An unsent draft");
  await expect.poll(async () => (await composer.boundingBox())?.y).toBeCloseTo(box.y, 0);
  await editor.evaluate((element) => element.blur());
  await page.evaluate(() => window.keyboardViewportFixture.setGeometry(844, 0));
  await expect.poll(async () => (await shell.boundingBox())?.y).toBe(0);
  await expect.poll(async () => (await shell.boundingBox())?.height).toBe(844);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
  ).toBe(0);
});
