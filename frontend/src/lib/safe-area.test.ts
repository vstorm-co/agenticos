import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/**
 * Covers the screen without being a surface anybody reads or taps at its top
 * edge: dimmed backdrops, the resize blocker, the drop target, the tour's
 * spotlight. Everything else that is `fixed inset-0` draws its header there.
 */
const NOT_A_SURFACE = [/bg-black/, /backdrop-blur/, /cursor-col-resize/, /z-\[1000000000\]/];

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !/\.(test|stories)\.tsx?$/.test(entry) ? [path] : [];
  });
}

it("clears the status bar and home indicator on every surface that covers the screen", () => {
  // A side panel on a phone, an expanded view: the page is drawn beneath the
  // status bar (`viewportFit: "cover"`), and a header without the inset put its
  // close button beneath the clock, out of reach.
  const missing = sources(SRC).filter((file) => {
    const text = readFileSync(file, "utf8");
    const surfaces = [...text.matchAll(/["'`][^"'`]*\bfixed inset-0\b[^"'`]*["'`]/g)].filter(
      ([classes]) => !NOT_A_SURFACE.some((pattern) => pattern.test(classes)),
    );
    return surfaces.length > 0 && !text.includes("FULLSCREEN_SAFE");
  });
  expect(missing.map((file) => relative(SRC, file))).toEqual([]);
});
