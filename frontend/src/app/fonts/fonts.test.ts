import { existsSync, readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

import { describe, expect, it } from "vitest";

/**
 * That `next build` asks nothing of a CDN.
 *
 * `next/font/google` reads its `.woff2` from `fonts.gstatic.com` at build time,
 * so a 404 there is a failed build - and gstatic 404d twice in one push window
 * on 2026-08-10, taking down `test-frontend` on #570 and `e2e` on #544, neither
 * of which had touched the frontend. Nothing in the repository made the fonts
 * reachable; every green build until then was luck of the CDN (#572).
 *
 * A build input has to be in the tree, so this asserts both halves: that no
 * module reaches for the helper again, and that every file the local
 * declarations name is actually vendored - a path typo in `layout.tsx` is the
 * one way to reintroduce a build that fails for want of a font.
 */

const SRC = join(__dirname, "..", "..");
const FONTS = __dirname;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === "node_modules" ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry) ? [path] : [];
  });
}

/**
 * The import statement, not the name. Both this file and `layout.tsx` say what
 * they are avoiding, and a substring match would read those sentences as the
 * offence they describe.
 */
const GOOGLE_FONT_IMPORT = /from\s+"next\/font\/google"/;

describe("vendored fonts", () => {
  it("no module imports the Google Fonts helper", () => {
    const offenders = sourceFiles(SRC).filter((path) =>
      GOOGLE_FONT_IMPORT.test(readFileSync(path, "utf8")),
    );
    expect(offenders).toEqual([]);
  });

  it("every font the layout declares is vendored", () => {
    const layout = readFileSync(join(SRC, "app", "layout.tsx"), "utf8");
    // `slice(1)` rather than destructuring the one group: a match always has it,
    // and TypeScript types it optional either way.
    const declared = [...layout.matchAll(/src:\s*"\.\/fonts\/([^"]+)"/g)].flatMap((match) =>
      match.slice(1),
    );

    expect(declared.length).toBeGreaterThan(0);
    for (const file of declared) {
      expect(existsSync(join(FONTS, file)), `${file} is declared but not vendored`).toBe(true);
    }
  });

  it("the licence names every vendored family", () => {
    const licence = readFileSync(join(FONTS, "OFL.txt"), "utf8");

    for (const family of ["Inter", "Bricolage Grotesque", "Geist"]) {
      expect(licence).toContain(family);
    }
  });
});
