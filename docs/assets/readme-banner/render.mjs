/**
 * Render the README's banner, docs/assets/readme-banner.gif.
 *
 *     node docs/assets/readme-banner/render.mjs
 *
 * The cards are the Toolbox's own: their scenes and stylesheet are read from
 * frontend/src/components/agents/capability-art at render time, so a changed
 * illustration reaches the banner by running this again rather than by
 * redrawing it. The blobs float and blink on periods that divide the six-second
 * loop, and every card animation is stepped to a period that does too, so the
 * GIF repeats without a seam; a drift much slower than the loop holds still.
 *
 * Playwright comes from frontend/ and ffmpeg from the developer's machine: this
 * is run by hand, like the social card, and the `.gif` is what the README links.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const art = join(here, "../../../frontend/src/components/agents/capability-art");
const require = createRequire(join(here, "../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

// [capability id, the name the Toolbox shows, an example from its guide]
const CARDS = [
  ["knowledge", "Knowledge search", "Answer from the HR handbook"],
  ["browser_use", "Web browser", "Check a supplier's portal"],
  ["subagents", "Subagents", "Research topics side by side"],
  ["sandbox", "Sandbox", "Clean up a spreadsheet"],
  ["charts", "Charts", "Sales by region, as bars"],
  ["artifacts", "Apps", "A weekly sales summary page"],
  ["skills", "Skills", "Write a proposal your way"],
  ["guardrails", "Guardrails", "Keep card numbers out"],
];
const LOOP_MS = 6000;
const FPS = 15;

// The generated module is two object literals behind TypeScript annotations.
const source = readFileSync(join(art, "art.generated.ts"), "utf8")
  .replace(/export const (\w+): [^=]+=/g, "exports.$1 =");
const exports = {};
new Function("exports", source)(exports);
const { CAPABILITY_ART, CAPABILITY_HUE } = exports;

const card = ([id, name, does]) => `
  <div class="cardx">
    <div class="cap-art" style="--h:${CAPABILITY_HUE[id]}"><div class="stage v-B" style="aspect-ratio:16/9">${CAPABILITY_ART[id]}</div></div>
    <div class="lbl"><b>${name}</b><span>${does}</span></div>
  </div>`;
const columns = [0, 2, 4, 6]
  .map((start, i) => `<div class="col c${i}">${CARDS.slice(start, start + 2).map(card).join("")}</div>`)
  .join("");

const scratch = mkdtempSync(join(tmpdir(), "readme-banner-"));
const page_ = join(scratch, "banner.html");
writeFileSync(
  page_,
  readFileSync(join(here, "template.html"), "utf8")
    .replace("/*CAPCSS*/", readFileSync(join(art, "capability-art.css"), "utf8"))
    .replace("<!--CARDS-->", columns),
);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 480 }, deviceScaleFactor: 1 });
await page.goto(`file://${page_}`);
await page.waitForLoadState("networkidle");
await page.evaluate(() => document.fonts.ready);
await page.evaluate((loop) => {
  window.__anims = document.getAnimations().map((a) => {
    const timing = a.effect.getTiming();
    const d = Number(timing.duration);
    const delay = Number(timing.delay || 0);
    a.pause();
    return {
      a,
      d,
      delay,
      dLoop: d > 2 * loop ? Infinity : loop / Math.max(1, Math.round(loop / d)),
      p0: ((((-delay) % d) + d) % d) / d,
    };
  });
}, LOOP_MS);
const frames = Math.round((LOOP_MS / 1000) * FPS);
for (let i = 0; i < frames; i++) {
  await page.evaluate((t) => {
    for (const x of window.__anims) x.a.currentTime = x.delay + x.d * (1000 + ((x.p0 + t / x.dLoop) % 1));
  }, (i * LOOP_MS) / frames);
  await page.locator(".card").screenshot({ path: join(scratch, `f${String(i).padStart(3, "0")}.png`) });
}
await browser.close();

execFileSync("ffmpeg", [
  "-v", "error", "-y", "-framerate", String(FPS), "-i", join(scratch, "f%03d.png"),
  "-vf", "split[a][b];[a]palettegen=max_colors=256:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
  "-loop", "0", join(here, "../readme-banner.gif"),
]);
console.log(`${frames} frames -> docs/assets/readme-banner.gif`);
