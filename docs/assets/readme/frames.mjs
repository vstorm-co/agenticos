/**
 * Set a console screenshot on one of the landing page's nature photographs, the
 * way the README's highlights and the decks show the product.
 *
 *     node docs/assets/readme/frames.mjs            # every frame below
 *     node docs/assets/readme/frames.mjs projects   # just these
 *
 * Each frame names a complete screenshot in `sources/` and a photograph in
 * `backgrounds/`, and is
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
 * Each capture keeps its full bounds and is fitted into a 1600 x 1000 frame.
 * `badges` float brand marks beside the window, from marks.json (paths copied from the landing's brand glyphs).
 * `heading` adds an editorial title above the window; the screenshot itself stays unchanged.
 */
const FRAMES = [
  {
    name: "manufacturing",
    source: "app-northline-operations",
    background: "storm",
    width: 1450,
  },
  {
    name: "motor",
    source: "app-motor-atlas",
    background: "night",
    width: 1450,
  },
  {
    name: "revenue",
    source: "app-revenue-pulse",
    background: "meadow-bg",
    width: 1450,
  },
  {
    name: "launch-room",
    source: "app-launch-room",
    background: "meadow-bg",
    width: 1450,
  },
  {
    name: "shopping",
    source: "app-trail-supply",
    background: "cta",
    width: 1450,
  },
  {
    name: "kit",
    source: "app-trail-kit",
    background: "meadow-bg",
    width: 1450,
  },
  {
    name: "widget",
    source: "store-widget",
    background: "cta",
    width: 1450,
  },
  {
    name: "workflows",
    source: "workflows",
    background: "hero-bg",
    width: 1500,
  },
  {
    name: "tables",
    source: "table-kanban",
    background: "meadow-bg",
    width: 1480,
  },
  {
    name: "mcp-server",
    source: "mcp-server",
    background: "storm",
    width: 1380,
  },
  {
    name: "hero",
    source: "chat-revenue-dark",
    background: "hero-bg",
    width: 1380,
  },
  {
    name: "projects",
    source: "room-codex-live",
    background: "hero-bg",
    width: 1380,
  },
  {
    name: "reply",
    source: "room-reply",
    background: "meadow-bg",
    width: 1380,
  },
  {
    name: "coding",
    source: "coding-context-dark",
    background: "night",
    width: 1450,
    heading: "Delegate the code.<br>Keep the context.",
    badges: [
      { mark: "claude_code", label: "Claude Code" },
      { mark: "codex", label: "Codex" },
    ],
  },
  {
    name: "visuals",
    source: "visual-production",
    background: "cta",
    width: 1380,
  },
  {
    name: "research",
    source: "research-table",
    background: "meadow-bg",
    width: 1380,
  },
  {
    name: "dashboard",
    source: "dashboard",
    background: "hero-bg",
    width: 1380,
  },
  {
    name: "subagents",
    source: "subagents",
    background: "meadow-bg",
    width: 1380,
  },
  {
    name: "browser",
    source: "old-browser",
    background: "night",
    width: 1380,
  },
  {
    name: "builder-test",
    source: "builder-test",
    background: "hero-bg",
    width: 1380,
  },
  {
    name: "app",
    source: "app-northline-operations",
    background: "cta",
    width: 1380,
  },
  {
    name: "mcp-servers",
    source: "mcp-servers",
    background: "storm",
    width: 1380,
  },
];

const MARKS = JSON.parse(readFileSync(join(here, "marks.json"), "utf8"));
const only = new Set(process.argv.slice(2));
const scratch = mkdtempSync(join(tmpdir(), "readme-frames-"));
const browser = await chromium.launch({
  channel: process.env.BROWSER_CHANNEL ?? "chrome",
});
const page = await browser.newPage({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 2,
});

for (const frame of FRAMES) {
  if (only.size && !only.has(frame.name)) continue;
  const source = join(here, "sources", `${frame.source}.webp`);
  const [nativeWidth, nativeHeight] = execFileSync("magick", ["identify", "-format", "%w %h", source], { encoding: "utf8" }).trim().split(" ").map(Number);
  // Every figure preserves the complete application viewport, including navigation.
  const [x, y, w, h] = [0, 0, 1600, 1600 * nativeHeight / nativeWidth];
  // Fit the window inside the frame with room for the photograph around it.
  // Badges sit on the sky above the window, so a frame with badges leaves room for them.
  const scale = Math.min(frame.width / w, (frame.badges ? 700 : 880) / h);
  const shown = { width: Math.round(w * scale), height: Math.round(h * scale) };
  const top = frame.badges ? 240 : Math.round((1000 - shown.height) / 2);
  const left = (1600 - shown.width) / 2;
  const badges = (frame.badges ?? [])
    .map((badge, index, all) => {
      const mark = MARKS[badge.mark];
      // Leave the title its own column when present; otherwise centre the marks.
      const x = frame.heading
        ? 970 + index * 300
        : 800 - (all.length * 300) / 2 + index * 300 + 20;
      return `<div class="badge" style="left:${x}px;top:${frame.heading ? 124 : top - 108}px"><span class="tile"><svg viewBox="0 0 24 24"><path fill-rule="evenodd" fill="${mark.color ?? "#111"}" d="${mark.d}"/></svg></span>${badge.label}</div>`;
    })
    .join("");
  const html = `<!doctype html><html><head><style>
    html,body{margin:0;width:1600px;height:1000px;overflow:hidden}
    body{background:#1d1931 url('${pathToFileURL(join(here, "backgrounds", `${frame.background}.webp`)).href}') center/cover}
    .heading{position:absolute;left:80px;top:75px;margin:0;color:#fff;font:600 48px/1.08 Inter,system-ui,sans-serif;letter-spacing:-.045em}
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
  </style></head><body><div class="glow"></div><div class="win"><img class="shot" src="${pathToFileURL(join(here, "sources", `${frame.source}.webp`)).href}"></div>${badges}${frame.heading ? `<h1 class="heading">${frame.heading}</h1>` : ""}</body></html>`;
  // A page opened from disk may load the local photograph and screenshot; one set as content may not.
  const file = join(scratch, `${frame.name}.html`);
  writeFileSync(file, html);
  await page.goto(pathToFileURL(file).href, { waitUntil: "load" });
  await page.waitForTimeout(300);
  const png = join(scratch, `${frame.name}.png`);
  await page.screenshot({ path: png });
  execFileSync("magick", [
    png,
    "-resize",
    "3200x",
    "-quality",
    "94",
    join(here, `highlight-${frame.name}.webp`),
  ]);
  console.log(`highlight-${frame.name}.webp`);
}
await browser.close();
