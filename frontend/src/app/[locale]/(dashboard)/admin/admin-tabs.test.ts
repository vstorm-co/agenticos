import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { ADMIN_TABS } from "./admin-tabs";

/**
 * The admin tab row is the section's index, and this suite is what keeps it one.
 *
 * The same pairing `settings-tabs.test.ts` holds, for the same reason: a
 * hand-written list beside a directory of routes drifts the moment somebody adds
 * a page, and the two failures are a page no tab leads to and a link that 404s.
 *
 * `/admin/page.tsx` is deliberately not in the list. It is the section index and
 * redirects to the first tab rather than being one - it used to render an
 * Overview whose six figures were the `platform` widget again and whose three
 * links were three of these tabs (#922).
 */

const ADMIN_DIR = path.join(process.cwd(), "src/app/[locale]/(dashboard)/admin");

/** Every route segment under `/admin/` that actually renders a page. */
function adminRouteSegments(): string[] {
  return readdirSync(ADMIN_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .filter((entry) =>
      readdirSync(path.join(ADMIN_DIR, entry.name)).some((file) => file === "page.tsx"),
    )
    .map((entry) => entry.name)
    .sort();
}

/** The segment a tab points at, or `null` if the tab leaves the section. */
function tabSegment(href: string): string | null {
  const match = /^\/admin\/([^/]+)$/.exec(href);
  return match?.[1] ?? null;
}

describe("the admin tab row", () => {
  it("leads to every page under /admin", () => {
    const tabbed = ADMIN_TABS.map((tab) => tabSegment(tab.href))
      .filter((segment): segment is string => segment !== null)
      .sort();

    expect(tabbed).toEqual(adminRouteSegments());
  });

  it("does not offer the index as a tab", () => {
    // An Overview tab beside the pages it linked to was a third of that page
    // spent on navigation to where the reader already was.
    expect(ADMIN_TABS.map((tab) => tab.href)).not.toContain("/admin");
  });

  it("stays inside the section it indexes", () => {
    expect(ADMIN_TABS.filter((tab) => tabSegment(tab.href) === null)).toEqual([]);
  });

  it("names each destination once", () => {
    const hrefs = ADMIN_TABS.map((tab) => tab.href);

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
