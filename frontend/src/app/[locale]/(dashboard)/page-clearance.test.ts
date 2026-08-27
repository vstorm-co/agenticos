import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The room under a page is declared once, and this is what says "once" (#933).
 *
 * Four surfaces used to re-add it inside their own content, at three different
 * values, on top of a declaration in the shell that painted nothing - so how far
 * a page cleared the bottom had four answers and none of them was the one in the
 * layout. Asserting that `PageTransition` carries the padding does not catch a
 * fifth being added somewhere else, which is the regression that actually
 * happened; this reads the pages.
 *
 * Only page-clearance sizes. `last:pb-0` closing a list and `pb-1.5` inside a
 * menu are a page's own spacing and none of this file's business.
 */

const DASHBOARD = join(import.meta.dirname);
const CLEARANCE = /(?:^|["\s:])(?:sm:|md:|lg:|xl:)?pb-(?:8|10|12|16|20|24|28|32)(?:["\s]|$)/;
/** The component playground, which is not a page anybody navigates to. */
const SKIP = new Set(["dev"]);

function pageFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      if (!SKIP.has(entry)) found.push(...pageFiles(path));
    } else if (entry === "page.tsx" || entry === "layout.tsx") {
      found.push(path);
    }
  }
  return found;
}

describe("the room under a dashboard page", () => {
  it("is declared by the page wrapper, and by no page or layout under it", () => {
    const offenders = pageFiles(DASHBOARD)
      // The shell itself, which is the element that used to declare it.
      .filter((path) => path !== join(DASHBOARD, "layout.tsx"))
      .filter((path) => CLEARANCE.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(DASHBOARD.length + 1));

    expect(offenders).toEqual([]);
  });

  it("recognises the shapes that were actually there", () => {
    // The four that were removed, plus a responsive one, against the two kinds
    // of inner spacing this must not object to.
    for (const shape of ['"space-y-6 pb-8"', '"pb-12"', '"pb-20"', '"md:pb-16"']) {
      expect(CLEARANCE.test(shape), shape).toBe(true);
    }
    for (const shape of ['"py-4 first:pt-0 last:pb-0"', '"px-2 pb-1.5"']) {
      expect(CLEARANCE.test(shape), shape).toBe(false);
    }
  });
});
