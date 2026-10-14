/**
 * Write the AgenticOS mark from the one recipe that draws it.
 *
 * The mark is the blob the name "agenticos" draws - the same face every agent in
 * the console wears, from the same `blobatar` - lightened, on a deep violet tile.
 * The surfaces that need it cannot share a file: MkDocs and the README want a
 * path, the console draws it inside a `next/og` image where only a data URI
 * survives, a desktop icon sits on the platform's own grid, and the README shows
 * it moving. All four are written here, so none of them is a second drawing.
 *
 * `gen-logo.test.ts` fails when a re-run would change any of them. The desktop
 * app's icon set is rasterised from the last:
 *
 *     bun run gen:logo
 *     cd ../desktop && bunx tauri icon src-tauri/app-icon.svg -o src-tauri/icons
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { blobatar } from "blobatar";

const here = dirname(fileURLToPath(import.meta.url));
export const LOGO_SVG = join(here, "..", "..", "docs", "assets", "logo.svg");
export const LOGO_TS = join(here, "..", "src", "lib", "logo.generated.ts");
export const APP_ICON_SVG = join(here, "..", "..", "desktop", "src-tauri", "app-icon.svg");
export const ANIMATED_SVG = join(here, "..", "..", "docs", "assets", "logo-animated.svg");

/** The tile: the violet the blob is drawn in, taken down to ink. */
const TILE = "#2b2547";
/** The tile's side, and the blob's inset on it, in the mark's own units. */
const SIDE = 104;
const INSET = 10;
/** What `blobatar` draws on: its paths are in a 100-unit box. */
const BLOB_BOX = 100;

/** The blob's paths, with the `<svg>` that wraps them taken off. */
function blobBody(): string {
  const svg = blobatar("agenticos", { background: false, hue: 265, tone: 0.1 });
  const body = /^<svg[^>]*>([\s\S]*)<\/svg>$/.exec(svg)?.[1];
  if (body === undefined) throw new Error(`blobatar returned an unexpected shape: ${svg}`);
  return body;
}

/** The mark, as a standalone square SVG. */
export function buildLogo(): string {
  const scale = (SIDE - 2 * INSET) / BLOB_BOX;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SIDE} ${SIDE}" width="${SIDE}" height="${SIDE}"` +
    ' role="img" aria-label="AgenticOS">\n' +
    "  <title>AgenticOS</title>\n" +
    `  <rect width="${SIDE}" height="${SIDE}" rx="30" fill="${TILE}"/>\n` +
    `  <g transform="translate(${INSET} ${INSET}) scale(${scale})">${blobBody()}</g>\n` +
    "</svg>\n"
  );
}

/**
 * The mark, alive: the blob breathes, blinks and glances aside, for the README.
 *
 * CSS inside the SVG, which GitHub runs in an `<img>` where it runs no script.
 * Blobatar draws the body and the eyes as one group each, in that order, so
 * those two groups are what move. A reader who asked for reduced motion gets
 * the still mark - the same drawing - because the rules are additive.
 */
export function buildAnimated(): string {
  const scale = (SIDE - 2 * INSET) / BLOB_BOX;
  const groups = blobBody().split("<g ");
  if (groups.length !== 3)
    throw new Error("blobatar no longer draws a body group and an eyes group");
  const body = `<g class="ao-body" ${groups[1]}`;
  const eyes = `<g class="ao-eyes" ${groups[2]}`;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SIDE} ${SIDE}" width="${SIDE}" height="${SIDE}"` +
    ' role="img" aria-label="AgenticOS">\n' +
    "  <title>AgenticOS</title>\n" +
    "  <style>\n" +
    "    .ao-float, .ao-body, .ao-eyes, .ao-look { transform-box: fill-box; transform-origin: center; }\n" +
    "    .ao-float { animation: ao-float 3.6s ease-in-out infinite; }\n" +
    "    .ao-body { animation: ao-breathe 3.6s ease-in-out infinite; }\n" +
    "    .ao-look { animation: ao-glance 9s ease-in-out infinite; }\n" +
    "    .ao-eyes { animation: ao-blink 4.8s ease-in-out infinite; }\n" +
    "    @keyframes ao-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }\n" +
    "    @keyframes ao-breathe { 0%, 100% { transform: scale(1, 1); } 50% { transform: scale(1.02, 0.985); } }\n" +
    "    @keyframes ao-glance { 0%, 30%, 100% { transform: translateX(0); } 38%, 52% { transform: translateX(-3px); } 60%, 74% { transform: translateX(3px); } 82% { transform: translateX(0); } }\n" +
    "    @keyframes ao-blink { 0%, 92%, 100% { transform: scaleY(1); } 95% { transform: scaleY(0.1); } }\n" +
    "    @media (prefers-reduced-motion: reduce) { .ao-float, .ao-body, .ao-eyes, .ao-look { animation: none; } }\n" +
    "  </style>\n" +
    `  <rect width="${SIDE}" height="${SIDE}" rx="30" fill="${TILE}"/>\n` +
    `  <g transform="translate(${INSET} ${INSET}) scale(${scale})">${groups[0]}<g class="ao-float">${body}<g class="ao-look">${eyes}</g></g></g>\n` +
    "</svg>\n"
  );
}

/**
 * The mark on the macOS icon grid: a 1024 canvas with the tile at 824.
 *
 * A dock draws every icon at one size and expects the margin to be in the
 * artwork, so a tile that fills its canvas reads a size larger than the icons
 * beside it.
 */
export function buildAppIcon(logo: string): string {
  const inner = logo
    .replace(/^<svg[^>]*>\n {2}<title>AgenticOS<\/title>\n/, "")
    .replace(/<\/svg>\n$/, "");
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">\n' +
    `  <g transform="translate(100 100) scale(${824 / SIDE})">\n${inner}  </g>\n` +
    "</svg>\n"
  );
}

/** The same mark as a data URI, for the surfaces that cannot load a file. */
export function buildModule(logo: string): string {
  // Percent-encoded rather than base64: a client component and Satori inside
  // `next/og` both read this, and neither `btoa` nor `Buffer` exists in both.
  const uri = `data:image/svg+xml,${encodeURIComponent(logo.split(/\s+/).join(" ").trim())}`;
  return (
    "// Generated by scripts/gen-logo.ts - do not edit.\n\n" +
    "/** The AgenticOS mark: the built-in logo, as a data URI. */\n" +
    `export const LOGO_DATA_URI =\n  "${uri}";\n`
  );
}

function main(): number {
  const logo = buildLogo();
  const wanted: [string, string][] = [
    [LOGO_SVG, logo],
    [LOGO_TS, buildModule(logo)],
    [APP_ICON_SVG, buildAppIcon(logo)],
    [ANIMATED_SVG, buildAnimated()],
  ];
  for (const [path, text] of wanted) {
    let current: string | null = null;
    try {
      current = readFileSync(path, "utf8");
    } catch {
      // Not written yet; the write below creates it.
    }
    if (current === text) continue;
    writeFileSync(path, text);
    console.log(`wrote ${path}`);
  }
  return 0;
}

const entry = process.argv[1];
if (entry !== undefined && import.meta.url === pathToFileURL(entry).href) {
  process.exit(main());
}
