/**
 * Set a console screenshot on one of the landing page's nature photographs, the
 * way the README's highlights and the decks show the product.
 *
 *     node docs/assets/readme/frames.mjs            # every frame below
 *     node docs/assets/readme/frames.mjs projects   # just these
 *
 * Each frame names a screenshot in `sources/`, the part of it to show (CSS
 * pixels of the 1600-wide capture) and a photograph in `backgrounds/`, and is
 * written to `highlight-<name>.webp` beside this file. Playwright and
 * ImageMagick come from the developer's machine, as for render.mjs.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

/** `crop` is [x, y, width, height] in the capture's CSS pixels; it is shown at `width` px in a 1600 x 1000 frame. */
const FRAMES = [
  { name: "projects", source: "room-codex-live", background: "hero-bg", crop: [240, 0, 1360, 1000], width: 1380 },
  { name: "reply", source: "room-reply", background: "meadow-bg", crop: [240, 0, 1360, 1000], width: 1380 },
  { name: "coding", source: "room-codex-answer", background: "night", crop: [240, 300, 1360, 700], width: 1380 },
  { name: "visuals", source: "visual-roi", background: "cta", crop: [500, 40, 1100, 900], width: 1300 },
  { name: "research", source: "research-table", background: "meadow-bg", crop: [240, 0, 1360, 1000], width: 1380 },
  { name: "dashboard", source: "dashboard", background: "hero-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "subagents", source: "old-subagents", background: "meadow-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "browser", source: "old-browser", background: "night", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "builder-test", source: "old-builder-test", background: "hero-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "app", source: "old-app", background: "cta", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "mcp-servers", source: "old-mcp-servers", background: "storm", crop: [0, 0, 1600, 1000], width: 1380 },
];

const only = new Set(process.argv.slice(2));
const scratch = mkdtempSync(join(tmpdir(), "readme-frames-"));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });

for (const frame of FRAMES) {
  if (only.size && !only.has(frame.name)) continue;
  const [x, y, w, h] = frame.crop;
  // Fit the window inside the frame with room for the photograph around it.
  const scale = Math.min(frame.width / w, 880 / h);
  const shown = { width: Math.round(w * scale), height: Math.round(h * scale) };
  const top = Math.round((1000 - shown.height) / 2);
  const html = `<!doctype html><html><head><style>
    html,body{margin:0;width:1600px;height:1000px;overflow:hidden}
    body{background:#1d1931 url('${pathToFileURL(join(here, "backgrounds", `${frame.background}.webp`)).href}') center/cover}
    .glow{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 55%,rgba(255,255,255,.18),transparent 62%)}
    .win{position:absolute;left:${(1600 - shown.width) / 2}px;top:${top}px;width:${shown.width}px;height:${shown.height}px;
      border-radius:18px;overflow:hidden;background:#fff;
      box-shadow:0 60px 120px -40px rgba(10,8,30,.75),0 0 0 1px rgba(255,255,255,.35),0 0 0 9px rgba(255,255,255,.14)}
    .shot{position:absolute;left:${-x * scale}px;top:${-y * scale}px;width:${1600 * scale}px}
  </style></head><body><div class="glow"></div><div class="win"><img class="shot" src="${pathToFileURL(join(here, "sources", `${frame.source}.webp`)).href}"></div></body></html>`;
  // A page opened from disk may load the local photograph and screenshot; one set as content may not.
  const file = join(scratch, `${frame.name}.html`);
  writeFileSync(file, html);
  await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
  await page.waitForTimeout(300);
  const png = join(scratch, `${frame.name}.png`);
  await page.screenshot({ path: png });
  execFileSync("magick", [png, "-resize", "2400x", "-quality", "84", join(here, `highlight-${frame.name}.webp`)]);
  console.log(`highlight-${frame.name}.webp`);
}
await browser.close();
