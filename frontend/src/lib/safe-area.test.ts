import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";
import { FULLSCREEN_SAFE, FULLSCREEN_SAFE_PADDED } from "./safe-area";

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

it("clears the Android gesture bar, a desktop title bar and a landscape notch", () => {
  for (const classes of [FULLSCREEN_SAFE, FULLSCREEN_SAFE_PADDED]) {
    // Android's WebView reports no safe area: the app measures its gesture bar
    // into --shell-inset-bottom, which --safe-bottom folds in.
    expect(classes).toMatch(/\bpb-\[[^\]]*var\(--safe-bottom/);
    expect(classes).toMatch(/\bpt-\[[^\]]*var\(--fullscreen-inset-top/);
    // In landscape the notch is at a side.
    expect(classes).toMatch(/\bpl-\[[^\]]*env\(safe-area-inset-left\)/);
    expect(classes).toMatch(/\bpr-\[[^\]]*env\(safe-area-inset-right\)/);
  }
  // A desktop main window reserves a title-bar row; a portalled panel is drawn
  // outside #main, where that row's height is otherwise declared.
  const css = readFileSync(join(SRC, "app", "desktop.css"), "utf8");
  expect(css).toMatch(
    /\[data-shell-window="main"\] \{\s*--fullscreen-inset-top: max\([^;]*1\.75rem\);/,
  );
  expect(css).toMatch(
    /:root \{\s*--fullscreen-inset-top: max\(var\(--shell-inset-top, 0px\), env\(safe-area-inset-top, 0px\)\);/,
  );
});
