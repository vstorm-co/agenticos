import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { APP_ICON_SVG, buildAppIcon, buildLogo, buildModule, LOGO_SVG, LOGO_TS } from "./gen-logo";

/**
 * That the mark on disk is still the one the recipe draws.
 *
 * Derived files drift silently: the docs header, the README and the console all
 * still render, just a different face from the one beside them. So the files are
 * regenerated in memory and compared - `bun run gen:logo` rewrites them.
 */
describe("gen-logo", () => {
  it("keeps the docs and README mark in step with the recipe", () => {
    expect(readFileSync(LOGO_SVG, "utf8")).toBe(buildLogo());
  });

  it("keeps the console's data URI the same drawing as the file", () => {
    expect(readFileSync(LOGO_TS, "utf8")).toBe(buildModule(buildLogo()));
  });

  it("keeps the desktop icon's source the same drawing, on the dock's grid", () => {
    const icon = readFileSync(APP_ICON_SVG, "utf8");
    expect(icon).toBe(buildAppIcon(buildLogo()));
    expect(icon).toContain('<rect width="104" height="104" rx="30"');
    expect(icon).not.toContain("<title>");
  });

  it("draws a square so it fits every icon slot without letterboxing", () => {
    expect(buildLogo()).toContain('viewBox="0 0 104 104"');
  });
});
