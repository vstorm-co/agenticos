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
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

/**
 * `crop` is [x, y, width, height] in the capture's CSS pixels; it is shown at `width` px in a 1600 x 1000 frame.
 * `badges` float brand marks beside the window, from marks.json (paths copied from the landing's brand glyphs).
 */
const FRAMES = [
  { name: "hero", source: "dark-room-reply", background: "hero-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "projects", source: "room-codex-live", background: "hero-bg", crop: [240, 0, 1360, 1000], width: 1380 },
  { name: "reply", source: "room-reply", background: "meadow-bg", crop: [240, 0, 1360, 1000], width: 1380 },
  {
    name: "coding",
    source: "room-codex-answer",
    background: "night",
    crop: [430, 290, 1130, 720],
    width: 1180,
    badges: [
      { mark: "claude_code", label: "Claude Code" },
      { mark: "codex", label: "Codex" },
    ],
  },
  { name: "visuals", source: "visual-roi", background: "cta", crop: [500, 40, 1100, 900], width: 1300 },
  { name: "research", source: "research-table", background: "meadow-bg", crop: [240, 0, 1360, 1000], width: 1380 },
  { name: "dashboard", source: "dashboard", background: "hero-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "subagents", source: "subagents", background: "meadow-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "browser", source: "old-browser", background: "night", crop: [300, 0, 1300, 1000], width: 1380 },
  { name: "builder-test", source: "builder-test", background: "hero-bg", crop: [0, 0, 1600, 1000], width: 1380 },
  { name: "app", source: "app-roi", background: "cta", crop: [0, 0, 1600, 840], width: 1380 },
  { name: "mcp-servers", source: "mcp-servers", background: "storm", crop: [0, 0, 1600, 1000], width: 1380 },
];

const MARKS = JSON.parse(readFileSync(join(here, "marks.json"), "utf8"));
const only = new Set(process.argv.slice(2));
const scratch = mkdtempSync(join(tmpdir(), "readme-frames-"));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });

for (const frame of FRAMES) {
  if (only.size && !only.has(frame.name)) continue;
  const [x, y, w, h] = frame.crop;
  // Fit the window inside the frame with room for the photograph around it.
  // Badges sit on the sky above the window, so a frame with badges leaves room for them.
  const scale = Math.min(frame.width / w, (frame.badges ? 760 : 880) / h);
  const shown = { width: Math.round(w * scale), height: Math.round(h * scale) };
  const top = frame.badges ? 1000 - shown.height - 60 : Math.round((1000 - shown.height) / 2);
  const left = (1600 - shown.width) / 2;
  const badges = (frame.badges ?? [])
    .map((badge, index, all) => {
      const mark = MARKS[badge.mark];
      // Centred as a row over the window, 300 px apart.
      const x = 800 - (all.length * 300) / 2 + index * 300 + 20;
      return `<div class="badge" style="left:${x}px;top:${top - 108}px"><span class="tile"><svg viewBox="0 0 24 24"><path fill-rule="evenodd" fill="${mark.color ?? "#111"}" d="${mark.d}"/></svg></span>${badge.label}</div>`;
    })
    .join("");
  const html = `<!doctype html><html><head><style>
    html,body{margin:0;width:1600px;height:1000px;overflow:hidden}
    body{background:#1d1931 url('${pathToFileURL(join(here, "backgrounds", `${frame.background}.webp`)).href}') center/cover}
    .glow{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 55%,rgba(255,255,255,.18),transparent 62%)}
    .win{position:absolute;left:${left}px;top:${top}px;width:${shown.width}px;height:${shown.height}px;
      border-radius:18px;overflow:hidden;background:#fff;
      box-shadow:0 60px 120px -40px rgba(10,8,30,.75),0 0 0 1px rgba(255,255,255,.35),0 0 0 9px rgba(255,255,255,.14)}
    .shot{position:absolute;left:${-x * scale}px;top:${-y * scale}px;width:${1600 * scale}px}
    .badge{position:absolute;z-index:3;display:flex;align-items:center;gap:14px;padding:12px 26px 12px 12px;border-radius:999px;
      background:rgba(255,255,255,.95);font:600 26px/1 Inter,system-ui,sans-serif;color:#16141f;letter-spacing:-.01em;
      box-shadow:0 30px 60px -20px rgba(5,4,15,.7),0 0 0 1px rgba(255,255,255,.6)}
    .badge .tile{display:flex;width:56px;height:56px;border-radius:16px;background:#f4f2ee;align-items:center;justify-content:center}
    .badge svg{width:34px;height:34px}
  </style></head><body><div class="glow"></div><div class="win"><img class="shot" src="${pathToFileURL(join(here, "sources", `${frame.source}.webp`)).href}"></div>${badges}</body></html>`;
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
