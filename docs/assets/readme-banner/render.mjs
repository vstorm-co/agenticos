/**
 * Render the README's banner, docs/assets/readme-banner.webp.
 *
 *     node docs/assets/readme-banner/render.mjs            # the banner
 *     node docs/assets/readme-banner/render.mjs --social   # docs/assets/social-preview.png
 *
 * The cards are the Toolbox's own: their scenes and stylesheet are read from
 * frontend/src/components/agents/capability-art at render time, so a changed
 * illustration reaches the banner by running this again rather than by
 * redrawing it. The blobs float and blink on periods that divide the six-second
 * loop, and every card animation is stepped to a period that does too, so the
 * banner repeats without a seam; a drift much slower than the loop holds still.
 *
 * An animated WebP at twice the size it is shown, rather than a GIF: a GIF's 256
 * colours dithered the dark ground into noise and its 1x frames went soft on a
 * high-density screen.
 *
 * Playwright comes from frontend/ and img2webp (libwebp) from the developer's
 * machine: this is run by hand, like the social card, and the `.webp` is what the
 * README links.
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
  ["knowledge", "Knowledge search", "From the HR handbook"],
  ["browser_use", "Web browser", "A supplier's portal"],
  ["subagents", "Subagents", "Topics side by side"],
  ["sandbox", "Sandbox", "Tidy a spreadsheet"],
  ["charts", "Charts", "Sales by region"],
  ["artifacts", "Apps", "A weekly sales page"],
  ["skills", "Skills", "Proposals your way"],
  ["guardrails", "Guardrails", "Card numbers kept out"],
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
// Four columns of cards: two deep in the banner, three in the taller social card,
// going round the list again where it runs out.
const rows = process.argv.includes("--social") ? 3 : 2;
const columns = [0, 1, 2, 3]
  .map((col) => {
    const cards = Array.from({ length: rows }, (_, row) => CARDS[(col * rows + row) % CARDS.length]);
    return `<div class="col c${col}">${cards.map(card).join("")}</div>`;
  })
  .join("");

// The social card is the same composition at GitHub's 1280x640, still: its
// template is docs/assets/social-preview.html.
const social = process.argv.includes("--social");
const size = social ? { width: 1280, height: 640 } : { width: 1200, height: 400 };
const template = social ? join(here, "../social-preview.html") : join(here, "template.html");

const scratch = mkdtempSync(join(tmpdir(), "readme-banner-"));
const page_ = join(scratch, "banner.html");
writeFileSync(
  page_,
  readFileSync(template, "utf8")
    .replace("/*CAPCSS*/", readFileSync(join(art, "capability-art.css"), "utf8"))
    .replace("<!--CARDS-->", columns)
    // Vstorm's colour logo with its wordmark lightened for the dark ground,
    // from content-os's tools/brand/logo_vstorm_color.svg.
    .replace("<!--VSTORM-->", readFileSync(join(here, "vstorm.svg"), "utf8"))
    // The landing page's dusk over the mountains, the photograph the README's figures sit on.
    .replaceAll("/*PHOTO*/", `file://${join(here, "../readme/backgrounds/hero-bg.webp")}`),
);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: size, deviceScaleFactor: 2 });
await page.goto(`file://${page_}`);
await page.waitForLoadState("networkidle");
await page.evaluate(() => document.fonts.ready);
// `--still out.png` renders the first frame alone, to judge the layout.
const still = process.argv.indexOf("--still");
if (still !== -1 || social) {
  // Every animation at its own start, so the still is the same on every run.
  await page.evaluate(() => document.getAnimations().forEach((a) => { a.pause(); a.currentTime = 0; }));
  const shot = still !== -1 ? process.argv[still + 1] : join(scratch, "card@2x.png");
  await page.locator(".card").screenshot({ path: shot });
  await browser.close();
  if (social) {
    // Rendered at 2x and brought down with Lanczos: sharper type than a 1x render.
    execFileSync("ffmpeg", ["-v", "error", "-y", "-i", shot, "-vf", "scale=1280:640:flags=lanczos", join(here, "../social-preview.png")]);
    console.log("-> docs/assets/social-preview.png");
  }
  process.exit(0);
}
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

const frameFiles = Array.from({ length: frames }, (_, i) => join(scratch, `f${String(i).padStart(3, "0")}.png`));
// Near-lossless: lossy VP8 broke the blobs' smooth gradients into visible blocks
// at every quality tried, and fully lossless was 14 MB for no visible gain.
execFileSync("img2webp", [
  "-loop", "0", "-near_lossless", "40", "-m", "6", "-d", String(Math.round(1000 / FPS)),
  ...frameFiles, "-o", join(here, "../readme-banner.webp"),
]);
console.log(`${frames} frames -> docs/assets/readme-banner.webp`);
