import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * One dark mapping, written in three places.
 *
 * `globals.css` repeats the dark palette three times on purpose - the OS
 * preference (`prefers-color-scheme`), the explicit toggle (`:root.dark`) and a
 * subtree that pins its own theme (`.theme-dark`) - because a CSS custom
 * property cannot be aliased across those without one of them losing to
 * specificity. The file says "three places, one mapping" and nothing enforced
 * it, so editing two of the three is a silent drift: the product looks right
 * with the toggle and wrong for whoever never touched it, or a pinned panel
 * disagrees with the page around it.
 *
 * These compare the blocks *to each other*, never to a colour. Retheming is a
 * token edit (see `accent-roles.test.tsx` on why no test pins a value); what
 * must not vary is which of the three you happened to edit.
 */

const CSS = readFileSync(join(__dirname, "globals.css"), "utf8");

/**
 * The declarations inside the rule `marker` opens.
 *
 * Anchored to the start of a line, because every one of these selectors is also
 * written in the file's own prose: matching the first *mention* of
 * `.theme-dark` found the sentence explaining it and then read the accent ramp
 * that follows as its body.
 */
function block(marker: string): Map<string, string> {
  const opener = new RegExp(`^${marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{`, "m");
  const start = CSS.search(opener);
  expect(start, `${marker} is no longer a rule in globals.css`).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", start + marker.length);
  let depth = 0;
  let end = open;
  for (let i = open; i < CSS.length; i += 1) {
    if (CSS[i] === "{") depth += 1;
    if (CSS[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = CSS.slice(open + 1, end);
  const declarations = new Map<string, string>();
  // The `?? ""` rather than destructuring the groups: a match always has both,
  // and TypeScript types them optional either way.
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    declarations.set(match[1] ?? "", (match[2] ?? "").trim().replace(/\s+/g, " "));
  }
  expect(declarations.size, `${marker} declares nothing`).toBeGreaterThan(0);
  return declarations;
}

const preference = block("@media (prefers-color-scheme: dark)");
const toggled = block(":root.dark");
const pinned = block(".theme-dark");

describe("the dark mapping's three copies", () => {
  it("gives the OS preference and the toggle the same tokens", () => {
    expect(Object.fromEntries(toggled)).toEqual(Object.fromEntries(preference));
  });

  it("gives a pinned-dark subtree the values the page would have", () => {
    // A subset by design - `.theme-dark` repoints what a panel needs, not every
    // role - so what is asserted is that nothing it declares disagrees.
    for (const [name, value] of pinned) {
      expect(toggled.get(name), `${name} disagrees between .theme-dark and :root.dark`).toBe(value);
    }
  });
});
