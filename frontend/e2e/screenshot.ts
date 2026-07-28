/**
 * Ad-hoc screenshot harness for design work - not part of the test suite.
 *
 * Usage:
 *   bun e2e/screenshot.ts <outDir> <path> [path...]        # light theme
 *   THEME=dark bun e2e/screenshot.ts <outDir> <path> ...   # dark theme
 *
 * Logs in as the bootstrap owner once per invocation, then captures each
 * given app path full-page into <outDir>/<slug>.<theme>.png.
 */
import { chromium } from "@playwright/test";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const EMAIL = process.env.E2E_OWNER_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "admin123";
const THEME = process.env.THEME === "dark" ? "dark" : "light";

const [outDir, ...paths] = process.argv.slice(2);
if (!outDir || paths.length === 0) {
  console.error("usage: bun e2e/screenshot.ts <outDir> <path> [path...]");
  process.exit(1);
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  colorScheme: THEME,
});
const page = await context.newPage();

await page.goto(`${BASE}/login`);
await page.getByLabel("Email").fill(EMAIL);
await page.getByLabel("Password").fill(PASSWORD);
await page.getByRole("button", { name: "Login" }).click();
await page.waitForURL(/\/(chat|dashboard)(\?.*)?$/, { timeout: 30000 });

for (const path of paths) {
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState("networkidle");
  // Let the entrance transition and any skeletons settle.
  await page.waitForTimeout(700);
  const slug = path.replaceAll("/", "_").replace(/^_/, "") || "root";
  await page.screenshot({ path: `${outDir}/${slug}.${THEME}.png`, fullPage: true });
  console.log(`captured ${path} -> ${slug}.${THEME}.png`);
}

await browser.close();
