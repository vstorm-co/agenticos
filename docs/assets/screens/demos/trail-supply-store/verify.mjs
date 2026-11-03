import { createRequire } from "node:module";
const require = createRequire(new URL("../../../../../frontend/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL ?? "chrome" });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(new URL("../trail-supply.html", import.meta.url).href);
  await page.locator("#find-fit").click();
  await page.locator("#budget").fill("129");
  await page.locator("#recommend").click();
  await expect(page.locator("#recommendation")).toContainText("No matching carry option");
  await page.locator("#budget").fill("135");
  await page.locator("#recommend").click();
  await expect(page.locator("#recommendation")).toContainText("€135");
  await expect(page.locator("#recommendation")).toContainText("€6 demo delivery");
  await page.locator("#trip").selectOption("market");
  await page.locator("#budget").fill("104");
  await page.locator("#recommend").click();
  await expect(page.locator("#recommendation h3")).toHaveText("Sunday Market Basket");
  await expect(page.locator("#recommendation")).toContainText("€82");
  await page.getByRole("button", { name: "Add suggested kit" }).click();
  await expect(page.locator(".grand")).toContainText("€82");
  await page.getByRole("button", { name: "Review demo kit" }).click();
  await expect(page.locator("#checkout-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#checkout-dialog")).not.toBeVisible();
  await expect(page.locator("#bag-shade")).toHaveClass(/open/);
  for (const width of [320, 390, 768]) {
    for (const name of ["trail-supply", "trail-supply-kit"]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(new URL(`../${name}.html`, import.meta.url).href);
      await expect(page.locator("h1")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      if (overflow) throw new Error(`${name}: horizontal overflow at ${width}px`);
      if (name === "trail-supply-kit") {
        await expect(page.locator("#total")).toHaveText("€157");
        await page.getByRole("button", { name: "Select Sunday Market Basket" }).click();
        await expect(page.locator("#total")).toHaveText("€233");
        await expect(page.locator("#status")).toContainText("over your budget");
      }
    }
  }
  process.stdout.write("Passed: delivery-inclusive budget boundaries, bag consistency, nested dialog Escape, kit arithmetic and 6 mobile layouts.\n");
} finally {
  await browser.close();
}
