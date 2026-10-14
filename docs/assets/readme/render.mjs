/**
 * Render each <section data-figure="name"> of figures.html to name.webp beside it.
 *
 *     node docs/assets/readme/render.mjs            # every figure
 *     node docs/assets/readme/render.mjs figures   # just these
 *
 * Playwright and ImageMagick come from the developer's machine: this is run by
 * hand after editing the page, like the social card, and the `.webp` files are
 * what the README links.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

const only = new Set(process.argv.slice(2));
const scratch = mkdtempSync(join(tmpdir(), "readme-figures-"));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 }, deviceScaleFactor: 2 });
await page.goto(pathToFileURL(join(here, "figures.html")).href);
await page.waitForSelector("body[data-ready]");
await page.evaluate(() => document.fonts.ready);
for (const section of await page.locator("section[data-figure]").all()) {
  const name = await section.getAttribute("data-figure");
  if (only.size > 0 && !only.has(name)) continue;
  const png = join(scratch, `${name}.png`);
  await section.screenshot({ path: png });
  // Down to 1600 wide, the size the README draws at full width.
  execFileSync("magick", [png, "-filter", "Lanczos", "-resize", "1600x", "-quality", "86", join(here, `${name}.webp`)]);
  console.log(`wrote ${name}.webp`);
}
await browser.close();
